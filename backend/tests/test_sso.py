"""Single sign-on: OIDC (mock provider with real RS256 tokens) and SAML (real XML signatures)."""

import base64
import hashlib
import time
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from httpx import AsyncClient
from lxml import etree
from signxml.signer import XMLSigner

from glasshaus.core.rbac import OrgRole
from glasshaus.sso import oidc
from tests.factories import PASSWORD, World, make_user, make_world

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]

ISSUER = "https://idp.example.test"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict[str, Any]:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True)
    return {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}


class FakeIdP:
    """Discovery, token and JWKS endpoints; checks PKCE and signs ID tokens."""

    def __init__(self) -> None:
        self.claims: dict[str, Any] = {}
        self.challenge = ""
        self.nonce = ""

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/jwks",
            })  # fmt: skip
        if path == "/jwks":
            return httpx.Response(200, json=_jwks())
        if path == "/token":
            form = parse_qs(request.content.decode())
            verifier = form["code_verifier"][0]
            computed = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            )
            if computed != self.challenge or form["code"][0] != "good-code":
                return httpx.Response(400, json={"error": "invalid_grant"})
            now = int(time.time())
            claims = {
                "iss": ISSUER,
                "aud": "glasshaus",
                "iat": now,
                "exp": now + 300,
                "nonce": self.nonce,
                **self.claims,
            }
            token = jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "k1"})
            return httpx.Response(200, json={"access_token": "x", "token_type": "Bearer", "id_token": token})
        return httpx.Response(404)


@pytest.fixture
def idp(monkeypatch: pytest.MonkeyPatch) -> FakeIdP:
    fake = FakeIdP()
    monkeypatch.setattr(
        oidc, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    )
    return fake


async def add_oidc(client: AsyncClient, world: World, **extra: Any) -> dict[str, Any]:
    body = {
        "name": "Example IdP", "slug": "example", "kind": "oidc", "client_secret": "s3cret",
        "oidc": {"issuer": ISSUER, "client_id": "glasshaus"}, **extra,
    }  # fmt: skip
    r = await client.post("/api/v1/admin/sso-providers", json=body, headers=world.headers)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def oidc_sign_in(
    client: AsyncClient, world: World, idp: FakeIdP, claims: dict[str, Any], **tamper: str
) -> httpx.Response:
    r = await client.get(
        f"/api/v1/auth/sso/{world.tenant.slug}/example/start", params={"next": "/projects/X"}
    )
    assert r.status_code == 302, r.text
    query = parse_qs(urlsplit(r.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"] and query["redirect_uri"][0].endswith("/oidc/callback")
    idp.challenge, idp.nonce, idp.claims = (
        query["code_challenge"][0],
        tamper.get("nonce", query["nonce"][0]),
        claims,
    )
    return await client.get(
        "/api/v1/auth/sso/oidc/callback",
        params={"state": query["state"][0], "code": tamper.get("code", "good-code")},
    )


def sso_error(r: httpx.Response) -> str:
    assert r.status_code == 303, r.text
    return unquote(parse_qs(urlsplit(r.headers["location"]).query).get("sso_error", [""])[0])


async def test_oidc_jit_link_and_errors(client: AsyncClient, idp: FakeIdP) -> None:
    world = await make_world()
    provider = await add_oidc(client, world, allowed_domains=["example.com"])
    assert provider["client_secret_set"] is True and "s3cret" not in str(provider)
    assert provider["redirect_uri"].endswith("/api/v1/auth/sso/oidc/callback")
    public = (
        await client.get("/api/v1/auth/sso/providers", params={"organization": world.tenant.slug})
    ).json()
    assert public == [
        {"name": "Example IdP", "slug": "example", "kind": "oidc", "start_url": provider["start_url"]}
    ]

    # First sign-in creates the account (JIT) and a session, then returns to `next`.
    r = await oidc_sign_in(client, world, idp, {"sub": "u-1", "email": "Ada@Example.com", "name": "Ada"})
    assert r.status_code == 303 and r.headers["location"] == "/projects/X"
    me = (await client.get("/api/v1/users/me")).json()
    assert me["email"] == "Ada@example.com" and me["org_role"] == "member" and me["name"] == "Ada"
    client.cookies.clear()

    # Same subject again: same account, even if the email changed at the IdP.
    await oidc_sign_in(client, world, idp, {"sub": "u-1", "email": "ada.l@example.com"})
    assert (await client.get("/api/v1/users/me")).json()["id"] == me["id"]
    client.cookies.clear()

    # Failures come back to the sign-in page with a reason, and no session.
    assert "domain" in sso_error(
        await oidc_sign_in(client, world, idp, {"sub": "u-2", "email": "eve@evil.test"})
    )
    assert "nonce" in sso_error(
        await oidc_sign_in(client, world, idp, {"sub": "u-3", "email": "b@example.com"}, nonce="x")
    )
    assert "refused" in sso_error(
        await oidc_sign_in(client, world, idp, {"sub": "u-3", "email": "b@example.com"}, code="bad")
    )
    unverified = {"sub": "u-4", "email": "c@example.com", "email_verified": False}
    assert "verified" in sso_error(await oidc_sign_in(client, world, idp, unverified))
    assert (await client.get("/api/v1/users/me")).status_code == 401
    # State is single-use.
    r = await client.get("/api/v1/auth/sso/oidc/callback", params={"state": "nope", "code": "good-code"})
    assert "expired" in sso_error(r)


async def test_oidc_links_existing_account_and_respects_jit_off(client: AsyncClient, idp: FakeIdP) -> None:
    world = await make_world()
    existing = await make_user(world.tenant, email=f"grace-{uuid.uuid4().hex[:6]}@example.com")
    await add_oidc(client, world, jit_provisioning=False)
    await oidc_sign_in(client, world, idp, {"sub": "g-1", "email": existing.email.upper()})
    assert (await client.get("/api/v1/users/me")).json()["id"] == str(existing.id)
    client.cookies.clear()
    assert "invite" in sso_error(
        await oidc_sign_in(client, world, idp, {"sub": "n-1", "email": "new@example.com"})
    )


async def test_enforced_sso_blocks_password_sign_in_except_owners(client: AsyncClient, idp: FakeIdP) -> None:
    world = await make_world()
    member = await make_user(world.tenant)
    await add_oidc(client, world, enforce=True)

    async def password_login(email: str) -> int:
        r = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": PASSWORD, "organization": world.tenant.slug},
        )
        client.cookies.clear()
        return r.status_code

    assert await password_login(member.email) == 401
    assert await password_login(world.owner.email) == 200  # break-glass access


async def test_provider_admin_requires_org_admin(client: AsyncClient) -> None:
    world = await make_world()
    from tests.factories import auth, token_for

    member = auth(await token_for(await make_user(world.tenant)))
    assert (await client.get("/api/v1/admin/sso-providers", headers=member)).status_code == 403
    body = {"name": "x", "slug": "x", "kind": "saml"}
    assert (
        await client.post("/api/v1/admin/sso-providers", json=body, headers=world.headers)
    ).status_code == 422


# --------------------------------------------------------------------------- SAML


def _cert() -> tuple[str, str]:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.example.test")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(KEY.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .sign(KEY, hashes.SHA256())
    )
    key_pem = KEY.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode(), key_pem.decode()


CERT, KEY_PEM = _cert()
IDP_ENTITY = "https://idp.example.test/saml"


def saml_response(*, request_id: str, audience: str, acs: str, email: str, sign: bool = True, recipient: str | None = None,
                  expires_in: int = 300, attrs: dict[str, str] | None = None) -> str:  # fmt: skip
    now = datetime.now(UTC)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    aid = "_a" + uuid.uuid4().hex
    attributes = "".join(
        f'<saml:Attribute Name="{k}"><saml:AttributeValue>{v}</saml:AttributeValue></saml:Attribute>'
        for k, v in (attrs or {}).items()
    )
    assertion = (
        '<saml:Assertion xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{aid}" Version="2.0" IssueInstant="{now:{fmt}}">'
        f"<saml:Issuer>{IDP_ENTITY}</saml:Issuer>"
        '<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Id="placeholder"></ds:Signature>'
        f"<saml:Subject><saml:NameID>{email}</saml:NameID>"
        '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData InResponseTo="{request_id}" Recipient="{recipient or acs}" '
        f'NotOnOrAfter="{now + timedelta(seconds=expires_in):{fmt}}"/>'
        "</saml:SubjectConfirmation></saml:Subject>"
        f'<saml:Conditions NotBefore="{now - timedelta(seconds=30):{fmt}}" '
        f'NotOnOrAfter="{now + timedelta(seconds=expires_in):{fmt}}">'
        f"<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction>"
        "</saml:Conditions>"
        f"<saml:AttributeStatement>{attributes}</saml:AttributeStatement>"
        "</saml:Assertion>"
    )
    element = etree.fromstring(assertion.encode())
    if sign:
        element = XMLSigner(c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#").sign(
            element, key=KEY_PEM, cert=CERT, reference_uri=aid
        )
    else:
        element.remove(element.find("{http://www.w3.org/2000/09/xmldsig#}Signature"))
    response = etree.fromstring(
        (
            '<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
            'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
            f'ID="_r{uuid.uuid4().hex}" Version="2.0" IssueInstant="{now:{fmt}}" Destination="{acs}" '
            f'InResponseTo="{request_id}"><saml:Issuer>{IDP_ENTITY}</saml:Issuer>'
            '<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
            "</samlp:Response>"
        ).encode()
    )
    response.append(element)
    return base64.b64encode(etree.tostring(response)).decode()


async def add_saml(client: AsyncClient, world: World) -> dict[str, Any]:
    body = {
        "name": "Corp SAML", "slug": "corp", "kind": "saml",
        "saml": {"idp_entity_id": IDP_ENTITY, "sso_url": "https://idp.example.test/sso",
                 "idp_certificate": CERT, "name_attribute": "displayName"},
    }  # fmt: skip
    r = await client.post("/api/v1/admin/sso-providers", json=body, headers=world.headers)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def saml_start(client: AsyncClient, world: World) -> tuple[str, str]:
    r = await client.get(f"/api/v1/auth/sso/{world.tenant.slug}/corp/start")
    assert r.status_code == 302, r.text
    query = parse_qs(urlsplit(r.headers["location"]).query)
    request_xml = zlib.decompress(base64.b64decode(query["SAMLRequest"][0]), -15)
    request_id = etree.fromstring(request_xml).get("ID")
    return request_id, query["RelayState"][0]


async def test_saml_sign_in_and_validation(client: AsyncClient) -> None:
    world = await make_world()
    provider = await add_saml(client, world)
    meta = await client.get(provider["metadata_url"].replace("http://localhost:8470", ""))
    assert meta.status_code == 200 and provider["acs_url"] in meta.text
    audience, acs = provider["sp_entity_id"], provider["acs_url"]

    async def post(response: str, relay: str) -> httpx.Response:
        return await client.post(
            "/api/v1/auth/sso/saml/acs", data={"SAMLResponse": response, "RelayState": relay}
        )

    request_id, relay = await saml_start(client, world)
    good = saml_response(request_id=request_id, audience=audience, acs=acs, email="ops@corp.test",
                         attrs={"displayName": "Ops Lead"})  # fmt: skip
    r = await post(good, relay)
    assert r.status_code == 303 and r.headers["location"] == "/", r.headers.get("location")
    me = (await client.get("/api/v1/users/me")).json()
    assert me["email"] == "ops@corp.test" and me["name"] == "Ops Lead"
    client.cookies.clear()

    # Replaying the same response is refused (the state is spent, and the assertion id is remembered).
    assert "expired" in sso_error(await post(good, relay))

    cases: dict[str, dict[str, Any]] = {
        "not signed": {"sign": False},
        "different service provider": {"audience": "https://other.example/sp"},
        "different destination": {"acs": "https://other.example/acs"},
        "different recipient": {"recipient": "https://other.example/acs"},
        "expired": {"expires_in": -600},
    }
    for reason, overrides in cases.items():
        request_id, relay = await saml_start(client, world)
        params = {
            "request_id": request_id,
            "audience": audience,
            "acs": acs,
            "email": "x@corp.test",
            **overrides,
        }
        assert reason.split()[-1] in sso_error(await post(saml_response(**params), relay)).lower(), reason

    # Wrong request id.
    _, relay = await saml_start(client, world)
    stale = saml_response(request_id="_other", audience=audience, acs=acs, email="x@corp.test")
    assert "does not answer" in sso_error(await post(stale, relay))

    # Tampering after signing breaks the signature.
    request_id, relay = await saml_start(client, world)
    signed = base64.b64decode(
        saml_response(request_id=request_id, audience=audience, acs=acs, email="x@corp.test")
    )
    tampered = base64.b64encode(signed.replace(b"x@corp.test", b"admin@corp.test")).decode()
    assert "signature" in sso_error(await post(tampered, relay)).lower()
    assert (await client.get("/api/v1/users/me")).status_code == 401


async def test_saml_owner_role_is_never_granted_by_jit(client: AsyncClient) -> None:
    world = await make_world()
    r = await client.post(
        "/api/v1/admin/sso-providers",
        json={"name": "x", "slug": "x", "kind": "oidc", "default_role": "owner",
              "oidc": {"issuer": ISSUER, "client_id": "c"}},
        headers=world.headers,
    )  # fmt: skip
    assert r.status_code == 422
    assert OrgRole.OWNER.value == "owner"
