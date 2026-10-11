"""SAML 2.0 service provider: SP-initiated sign-in (HTTP-Redirect AuthnRequest, HTTP-POST response).

Signature checking uses signxml against the IdP certificate the admin configured, and only data inside
the signed element is trusted (defends against signature-wrapping). The response or the assertion
(or both) must be signed; encrypted assertions are not supported.
"""

import base64
import secrets
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from lxml import etree
from signxml.exceptions import InvalidInput as SignXmlInvalidInput
from signxml.exceptions import InvalidSignature
from signxml.verifier import SignatureConfiguration, XMLVerifier

from glasshaus.core.errors import Unauthenticated
from glasshaus.sso.models import IdentityProvider
from glasshaus.sso.service import SamlConfig, remember_once, saml_acs_url, saml_entity_id, save_state

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
}
ASSERTION = "{urn:oasis:names:tc:SAML:2.0:assertion}Assertion"
SKEW = timedelta(minutes=3)
MAX_RESPONSE_BYTES = 512 * 1024


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def metadata_xml(org: str, provider: IdentityProvider) -> str:
    entity = escape(saml_entity_id(org, provider.slug), {'"': "&quot;"})
    acs = escape(saml_acs_url(), {'"': "&quot;"})
    return (
        '<?xml version="1.0"?>\n'
        f'<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{entity}">'
        '<md:SPSSODescriptor AuthnRequestsSigned="false" WantAssertionsSigned="true" '
        'protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        "<md:NameIDFormat>urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress</md:NameIDFormat>"
        '<md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'Location="{acs}" index="0" isDefault="true"/>'
        "</md:SPSSODescriptor></md:EntityDescriptor>"
    )


async def start(
    org: str, provider: IdentityProvider, next_path: str, extra: dict[str, str] | None = None
) -> str:
    cfg = SamlConfig.model_validate(provider.config)
    request_id = "_" + secrets.token_hex(20)
    issued = _iso(_now())
    xml = (
        '<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{request_id}" Version="2.0" IssueInstant="{issued}" '
        f'Destination="{escape(str(cfg.sso_url), {chr(34): "&quot;"})}" '
        f'AssertionConsumerServiceURL="{escape(saml_acs_url(), {chr(34): "&quot;"})}" '
        'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f"<saml:Issuer>{escape(saml_entity_id(org, provider.slug))}</saml:Issuer>"
        '<samlp:NameIDPolicy Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress" '
        'AllowCreate="true"/>'
        "</samlp:AuthnRequest>"
    )
    deflated = zlib.compress(xml.encode())[2:-4]  # raw DEFLATE (strip zlib header and checksum)
    state = await save_state(
        {
            "kind": "saml",
            "tenant_id": str(provider.tenant_id),
            "provider_id": str(provider.id),
            "org": org,
            "request_id": request_id,
            "next": next_path,
            **(extra or {}),
        }
    )
    query = urlencode({"SAMLRequest": base64.b64encode(deflated).decode(), "RelayState": state})
    sep = "&" if "?" in str(cfg.sso_url) else "?"
    return f"{cfg.sso_url}{sep}{query}"


def _verify(xml: bytes, cert: str) -> Any:
    """Return the signed element: the Response (then its Assertion) or the Assertion itself."""
    for location in ("./", f"./{ASSERTION}/"):
        try:
            result = XMLVerifier().verify(
                xml, x509_cert=cert, expect_config=SignatureConfiguration(location=location)
            )
        except (InvalidSignature, SignXmlInvalidInput) as exc:
            if "Expected to find XML element Signature" in str(exc):
                continue  # no signature at this location; try the next
            raise Unauthenticated(f"SAML signature is invalid: {exc}") from exc
        signed = (result[0] if isinstance(result, list) else result).signed_xml
        if signed is None:
            continue
        if signed.tag == ASSERTION:
            return signed
        assertion = signed.find("saml:Assertion", NS)
        if assertion is not None:
            return assertion
    raise Unauthenticated("SAML response is not signed by the configured identity provider")


async def finish(
    provider: IdentityProvider, state: dict[str, Any], saml_response: str
) -> tuple[str, str | None, str | None]:
    """Validate the response. Returns (subject, email, name)."""
    cfg = SamlConfig.model_validate(provider.config)
    try:
        xml = base64.b64decode(saml_response, validate=False)
    except ValueError as exc:
        raise Unauthenticated("SAML response is not base64") from exc
    if len(xml) > MAX_RESPONSE_BYTES:
        raise Unauthenticated("SAML response is too large")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        root = etree.fromstring(xml, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise Unauthenticated("SAML response is not valid XML") from exc
    status = root.find("samlp:Status/samlp:StatusCode", NS)
    if status is None or status.get("Value") != "urn:oasis:names:tc:SAML:2.0:status:Success":
        raise Unauthenticated("the identity provider did not complete the sign-in")
    if root.get("Destination") and root.get("Destination") != saml_acs_url():
        raise Unauthenticated("SAML response was sent to a different destination")

    assertion = _verify(xml, cfg.idp_certificate)
    now = _now()
    issuer = assertion.findtext("saml:Issuer", namespaces=NS)
    if (issuer or "").strip() != cfg.idp_entity_id:
        raise Unauthenticated("SAML assertion issuer does not match the configured provider")
    conditions = assertion.find("saml:Conditions", NS)
    if conditions is None:
        raise Unauthenticated("SAML assertion has no conditions")
    not_before = _parse_time(conditions.get("NotBefore"))
    not_after = _parse_time(conditions.get("NotOnOrAfter"))
    if (not_before and now + SKEW < not_before) or (not_after and now - SKEW >= not_after):
        raise Unauthenticated("SAML assertion is expired or not yet valid")
    audiences = [a.text for a in conditions.findall("saml:AudienceRestriction/saml:Audience", NS)]
    if saml_entity_id(state["org"], provider.slug) not in audiences:
        raise Unauthenticated("SAML assertion is for a different service provider")
    confirmation = assertion.find("saml:Subject/saml:SubjectConfirmation/saml:SubjectConfirmationData", NS)
    if confirmation is None:
        raise Unauthenticated("SAML assertion has no subject confirmation")
    if confirmation.get("Recipient") != saml_acs_url():
        raise Unauthenticated("SAML assertion was issued for a different recipient")
    if confirmation.get("InResponseTo") != state["request_id"]:
        raise Unauthenticated("SAML assertion does not answer this sign-in request")
    expires = _parse_time(confirmation.get("NotOnOrAfter"))
    if expires and now - SKEW >= expires:
        raise Unauthenticated("SAML assertion is expired")
    assertion_id = assertion.get("ID") or ""
    await remember_once(
        f"{provider.id}:{assertion_id}", int(((not_after or now) - now).total_seconds()) + 300
    )

    name_id = (assertion.findtext("saml:Subject/saml:NameID", namespaces=NS) or "").strip()
    if not name_id:
        raise Unauthenticated("SAML assertion has no subject")
    attrs: dict[str, str] = {}
    for attr in assertion.findall("saml:AttributeStatement/saml:Attribute", NS):
        value = attr.findtext("saml:AttributeValue", namespaces=NS)
        if value:
            attrs[attr.get("Name", "")] = value.strip()
    email = attrs.get(cfg.email_attribute) if cfg.email_attribute else name_id
    name = attrs.get(cfg.name_attribute) if cfg.name_attribute else None
    return name_id, email, name
