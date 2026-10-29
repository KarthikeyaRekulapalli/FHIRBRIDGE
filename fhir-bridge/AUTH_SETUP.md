# EHR authentication setup

Both EHRs are accessed as a system (2-legged / SMART Backend Services): the
service authenticates as the organisation, clinicians do not log in to the EHR
through this app. Access to the app itself is Microsoft Entra sign-in (SSO_SETUP.md).

## Methods

| `*_AUTH_METHOD` | How the token request authenticates | Needs |
|---|---|---|
| `private_key_jwt` | signed JWT client assertion verified against your published JWKS | `*_PRIVATE_KEY_PATH`, `*_KID`, `*_ALG` (RS384) |
| `client_secret_basic` | HTTP Basic `client_id:client_secret` | `*_CLIENT_SECRET` |
| `none` | no token (open sandboxes) | development only; rejected when `APP_ENV=production` |

Cerner verifies RS384 or ES384 only; athenahealth accepts RS384. RS256 is the
usual cause of Cerner `invalid-signature`.

## Keys and JWKS (private_key_jwt)

```bash
cd backend
python tools/generate_keys.py --out ./keys --kid <kid> --alg RS384
```

* `keys/private_key.pem`: secret. On Ubuntu copy to `/etc/fhir-bridge/keys/` (mode 640).
* `keys/jwks.json`: public. Publish it (for example copy to `docs/.well-known/jwks.json`;
  the Pages workflow serves it at `https://<user>.github.io/<repo>/.well-known/jwks.json`)
  and register that URL, or upload the JWKS, in each EHR portal. The EHR must be
  able to fetch it from the public internet.
* The `kid` in `.env` must equal the `kid` in the JWKS. One keypair can serve both EHRs.

Rotation: add the new key to the JWKS (keep the old), publish, switch `*_KID`,
remove the old key after its tokens expire.

## Cerner / Oracle Health

code Console app of type **System**, FHIR R4, explicit `system/<Resource>.read`
scopes. The system account in Cerner Central holds either the JWKS registration
or a secret. The customer tenant must allow-list the client id. Token endpoint from
`GET <base>/.well-known/smart-configuration`.

## athenahealth

Developer portal app with **2-Legged OAuth**, JWKS (or client secret) under
Credentials, system scopes for the FHIR resources above. You also need the
numeric practice id (`ATHENA_PRACTICE_ID`) because system-scope searches must
carry `ah-practice`. Preview and production hosts differ; see `.env.example`.

## The request the app makes

```
POST {token_url}
grant_type=client_credentials&scope=<*_SCOPE>
&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
&client_assertion=<JWT: iss=sub=client_id, aud=token_url, iat, exp=+300s, jti; header kid, alg RS384>
```

Tokens are cached in-process and renewed 60 s before expiry; an upstream 401 on
a FHIR call drops the cache and retries once. Errors are reported as
`token endpoint returned HTTP <code> (<error>: <description>)` without the body.

Test it: `python tools/live_check.py --stage token` or `GET /api/auth/test/{source}`.
