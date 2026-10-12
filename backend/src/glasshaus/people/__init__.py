"""Reporting lines (who reports to whom) and the My team page for managers.

Managers come from the identity provider: SCIM provisioning (the enterprise extension's ``manager``,
which Microsoft Entra ID sends) and, for people SCIM does not cover, a nightly Microsoft Graph sync.
"""
