# Single sign-on and SCIM provisioning

Organization owners and admins configure both under **Admin → Single sign-on** and **Admin → Provisioning**
(or `GET/POST/PATCH/DELETE /api/v1/admin/sso-providers` and `/api/v1/admin/scim-tokens`).

`GLASSHAUS_PUBLIC_URL` must be the address people use in the browser; every URL below is built from it.
Use HTTPS in production (cookies become `Secure`, and IdPs usually require HTTPS redirect URIs).

## OpenID Connect (Entra ID, Okta, Google, Authentik, Keycloak, Auth0, …)

1. Register a web application at the IdP with redirect URI
   `https://<glasshaus>/api/v1/auth/sso/oidc/callback` (shown on the provider card).
2. Add the provider in Glasshaus: issuer URL (its `/.well-known/openid-configuration` must be reachable from
   the API container), client ID and client secret. Scopes default to `openid email profile`.

Glasshaus uses the authorization code flow with PKCE (S256), `state` and `nonce`, validates the ID token
signature against the IdP's JWKS, the issuer, audience and expiry, and refuses `email_verified: false`.

## SAML 2.0 (ADFS, Entra ID, Okta, Authentik, Shibboleth, …)

1. Add the provider: IdP entity ID, IdP SSO URL (HTTP-Redirect binding) and the IdP signing certificate
   (PEM). Optionally name the attribute that holds the email (the NameID is used otherwise) and the
   display name.
2. Give the IdP the service-provider metadata URL from the provider card, or enter by hand:
   - Entity ID / audience: `https://<glasshaus>/api/v1/auth/sso/saml/<org>/<slug>/metadata`
   - ACS URL (HTTP-POST): `https://<glasshaus>/api/v1/auth/sso/saml/acs`
   - NameID format: email address

The response or the assertion must be signed with the configured certificate (SHA-256 or stronger);
only data inside the signed element is used. Destination, recipient, audience, `InResponseTo`, validity
window (3-minute skew) and single use of each assertion are checked. Encrypted assertions are not
supported.

## Accounts and enforcement

- **Linking:** a returning person is matched by their subject at the IdP. A first sign-in whose email
  matches an existing account is linked only when that is safe:
  - **members and guests:** when the IdP marks the standard `email` claim verified
    (`email_verified: true`), or when **Link existing accounts by email** is on for that provider (it needs
    allowed domains; use it for IdPs that don't send the flag, such as SAML or Entra ID);
  - **admins:** only with `email_verified: true`;
  - **owners:** never automatically.

  Anyone can link a provider themselves: **Account → Single sign-on → Link**, while signed in. Claims
  other than `email` (for example `preferred_username` or `upn`) never count as verified, because users
  can change them at some IdPs. Set **allowed domains** to limit which emails a provider can sign in or
  create.
- **Just-in-time accounts:** on by default, with the role you choose (member, guest or admin; never owner).
  Turn it off to allow only invited people.
- **Require SSO:** turns off password sign-in for everyone except owners, who keep it as break-glass
  access. API tokens and MCP OAuth keep working.
- Every SSO sign-in, refusal and account creation is in the audit log.

## SCIM 2.0

Base URL: `https://<glasshaus>/scim/v2` with `Authorization: Bearer ghs_…` (a token from Admin →
Provisioning; shown once).

| Resource | Supported |
| --- | --- |
| `/Users` | list with `filter=userName eq "…"`, `externalId eq`, `emails.value eq`; create, get, replace (PUT), PATCH (`active`, names, `externalId`, `userName`, `title`, enterprise `department` and `manager`), DELETE |
| `/Groups` | list (`displayName eq`), create, get, replace, PATCH members add/remove/replace and `displayName`, DELETE |
| `/ServiceProviderConfig`, `/ResourceTypes`, `/Schemas` | discovery |

Mapping: users are accounts (`userName` = email); deactivating or deleting a user disables the account and
ends their sessions (their history is kept).

Limits, so a leaked SCIM token or a compromised IdP cannot take over or lock out administrators:

- Owner and admin accounts are managed in Glasshaus only: SCIM cannot change their email, `active` state or
  `externalId` (re-sending unchanged values, as IdPs do on every sync, is fine).
- SCIM changes the email only of accounts it provisioned or adopted (an `externalId` is set); email
  changes end the person's sessions.
- An account an admin deactivated in Glasshaus is not reactivated through SCIM. Groups are
workspaces: members become workspace members with the member role. Deleting a group removes its members
but keeps the workspace and its projects.

Managers, job titles and departments: the enterprise extension
(`urn:ietf:params:scim:schemas:extension:enterprise:2.0:User`) `manager` and `department`, and the core
`title`, are stored and power [My team](my-team.md). The manager is the manager's SCIM `id` (or
`externalId`); a manager that would create a loop is ignored.

**Entra ID:** Enterprise application → Provisioning → Automatic; Tenant URL = the base URL, Secret token =
the SCIM token. **Okta:** SCIM 2.0 app, Bearer token authentication, unique identifier `userName`.
**Authentik:** SCIM provider with the base URL and token.
