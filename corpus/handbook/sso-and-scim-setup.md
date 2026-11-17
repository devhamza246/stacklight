# SSO and SCIM Setup Guide

Owner: Solutions Engineering
Last reviewed: 2026-08-25

SSO is available on Business and Enterprise. SCIM user provisioning is available on Enterprise only.

## SSO setup
1. An owner opens Settings > Security > Single sign-on and picks SAML 2.0 or OIDC.
2. Copy the ACS URL and Entity ID into your identity provider (Okta, Microsoft Entra ID and Google Workspace are tested).
3. Upload the IdP metadata XML or paste the issuer URL for OIDC.
4. Test with the "Test connection" button before enforcing.
5. Enable "Require SSO". Members who signed up with a password are given 7 days to link their account before password login is disabled.

Owners always keep a break-glass password login, protected by two-factor authentication.

## SCIM
The SCIM 2.0 base URL is https://api.quillbase.example/scim/v2. Generate a SCIM token in Settings > Security (tokens begin with `qb_scim_`). Deprovisioned users are suspended immediately and their API tokens revoked; their flows are reassigned to the workspace owner. SCIM syncs groups to Quillbase roles: Owner, Admin, Editor and Viewer.
