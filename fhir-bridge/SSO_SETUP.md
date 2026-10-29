# Sign-in with Microsoft Entra ID (Azure AD)

Authors: Claude and Karthi.

Users sign in with their organisation Microsoft account. There are no roles in
the app: anyone Entra lets through may search and summarize. Who that is, and
MFA/conditional access, is managed in Entra, not here.

## 1. Register the app in Entra (admin, once)

Entra admin center → **App registrations → New registration**:

| Field | Value |
|---|---|
| Name | FHIR EHR Bridge |
| Supported account types | **Accounts in this organizational directory only** (single tenant) |
| Redirect URI | platform **Web**, `https://<your host>/auth/callback` (must equal `SSO_BASE_URL` + `/auth/callback`; for local testing add `http://localhost:8000/auth/callback`) |

After creating it:

1. **Overview**: copy *Application (client) ID* → `SSO_CLIENT_ID`, *Directory (tenant) ID* → `SSO_TENANT_ID`.
2. **Certificates & secrets → New client secret**: copy the secret **Value** (not the Secret ID) → `SSO_CLIENT_SECRET`. Note the expiry; rotate before then (create a new secret, update `.env`, restart, delete the old one).
3. **Authentication**: under *Implicit grant and hybrid flows* leave both boxes **unticked**; under *Front-channel logout URL* optionally set `https://<your host>/`.
4. **API permissions**: the default `User.Read` (Microsoft Graph, delegated) is enough. Click *Grant admin consent* so users are not prompted.
5. **Token configuration**: nothing to add; the app reads `name` and `preferred_username` from the standard id_token.

## 2. Decide who can sign in

Entra admin center → **Enterprise applications → FHIR EHR Bridge → Properties**:
set **Assignment required? = Yes**. Then **Users and groups → Add** the AD
group(s) that may use the bridge. Everyone else gets Entra's own
"AADSTS50105: not assigned" page and never reaches the app. Conditional access
and MFA policies apply as for any other Entra app.

## 3. Configure the service

In `/etc/fhir-bridge/.env` (Ubuntu) or `.env` (development):

```
SSO_TENANT_ID=<Directory (tenant) ID>
SSO_CLIENT_ID=<Application (client) ID>
SSO_CLIENT_SECRET=<secret value>
SSO_BASE_URL=https://<your host>
SESSION_SECRET=<output of: openssl rand -hex 32>
SESSION_HOURS=8
```

`SSO_BASE_URL` is the URL users type; the reverse proxy must forward
`/auth/*` and `/api/*` to the service unchanged. The redirect URI registered in
Entra must match `SSO_BASE_URL/auth/callback` exactly (scheme, host, port, path).

Production refuses to start when any of the five values is missing
(`journalctl -u fhir-bridge` shows which). In development, leaving all five
empty runs the app with no login at all.

## 4. How it works

```
browser  --GET /api/config (no cookie)-->  app  --401-->  browser  --GET /auth/login-->  app
app --302--> login.microsoftonline.com/<tenant>/oauth2/v2.0/authorize (state cookie set)
Entra --302 /auth/callback?code&state--> app
app --POST .../oauth2/v2.0/token (code + client secret)--> Entra --id_token--> app
app verifies the id_token signature (tenant JWKS), audience (client id) and issuer,
    sets an HttpOnly session cookie (HS256, SESSION_SECRET, SESSION_HOURS) and redirects to /
```

* The cookie carries only the Entra object id, display name and UPN. No Entra
  token is stored or forwarded; the app never calls Microsoft Graph.
* `/auth/logout` clears the cookie and signs out of Entra, returning to `SSO_BASE_URL`.
* `/api/health` stays public and reports `"sso": true`.

## 5. Verify

1. `curl -s https://<host>/api/health` → `{"status":"ok","sso":true}`.
2. Open `https://<host>/` in a private window: you are sent to Microsoft, sign in, and return to the search page with your name in the header.
3. Try an account that is not assigned: Entra blocks it before the app.
4. `curl -s https://<host>/api/config` without a cookie → HTTP 401.

## Troubleshooting

| Message | Check |
|---|---|
| `AADSTS50011` redirect URI mismatch | Entra redirect URI vs `SSO_BASE_URL/auth/callback`, including trailing slash and port |
| `AADSTS7000215` invalid client secret | you pasted the Secret ID instead of the Value, or the secret expired |
| `AADSTS50105` | user/group not assigned to the enterprise application |
| `sign-in failed: state mismatch` | cookies blocked, or more than 10 minutes between redirect and return; start again at `/auth/login` |
| `sign-in failed: id_token rejected` | `SSO_TENANT_ID` / `SSO_CLIENT_ID` do not match the registration |
| loop between `/` and `/auth/login` | `SSO_BASE_URL` is `https://` but the proxy reaches the app over plain http on the same host name is fine; the cookie is `Secure`, so the browser must be on https |
