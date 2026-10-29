# Ubuntu deployment

Tested assumptions: Ubuntu with systemd and Python 3.11+ (`python3`,
`python3-venv`, `rsync`, `curl`). No specific release, reverse proxy or container
runtime is assumed. The service binds `127.0.0.1:8000`; put your organisation's
TLS reverse proxy in front of it for anything beyond localhost.

## Layout

| Path | Owner / mode | Purpose |
|---|---|---|
| `/opt/fhir-bridge/{backend,frontend}` | root:fhir-bridge, no world access | application code + venv |
| `/etc/fhir-bridge/.env` | root:fhir-bridge 640 | configuration and secrets |
| `/etc/fhir-bridge/keys/private_key.pem` | root:fhir-bridge 640 | signing key(s) |
| `/var/log/fhir-bridge/app.log` | fhir-bridge 750 | rotating application log |

## Install or update

```bash
sudo apt install -y python3 python3-venv rsync curl
git clone <repo> fhir-bridge && cd fhir-bridge     # or unpack a release
sudo deploy/ubuntu/install.sh
```

The script creates the `fhir-bridge` system user, copies code, builds the venv
from `requirements.txt` (pinned), writes `/etc/fhir-bridge/.env` from the
template on first run, installs `deploy/ubuntu/fhir-bridge.service`, validates
the configuration and only then (re)starts the service. Re-run it after every
update; it never overwrites an existing `.env`.

Then edit `/etc/fhir-bridge/.env` (at minimum the `SSO_*` block from SSO_SETUP.md, the Cerner block,
`CERNER_PRIVATE_KEY_PATH=/etc/fhir-bridge/keys/private_key.pem`, and the AI block)
and run `sudo deploy/ubuntu/install.sh` again.

## Operate

```bash
sudo systemctl status fhir-bridge
sudo systemctl restart fhir-bridge
sudo journalctl -u fhir-bridge -n 100          # startup errors
sudo tail -f /var/log/fhir-bridge/app.log       # application log (no PHI, no secrets)
curl -s http://127.0.0.1:8000/api/health        # {"status":"ok"|"degraded","sso":true}
curl -s http://127.0.0.1:8000/api/config        # 401 without a browser session (expected)
```

Restart policy: `Restart=on-failure`, 5 s delay. `APP_ENV=production` is set by
the unit (do not set it in `.env`; the installer refuses): startup fails fast
(visible in `journalctl`) if any `SSO_*` value is empty,
an enabled EHR is incomplete, or the AI provider is misconfigured.

Staged live check as the service user (read-only; pass explicit search terms):

```bash
cd /opt/fhir-bridge/backend
sudo -u fhir-bridge .venv/bin/python tools/live_check.py --env-file /etc/fhir-bridge/.env \
  --stage search --family <name>
```

## Troubleshooting

| Symptom | Check |
|---|---|
| service exits immediately | `journalctl -u fhir-bridge`: "invalid configuration" lists the variables |
| `/api/health` says `degraded` | `/api/config` -> `problems` per area |
| `token endpoint returned HTTP 400/401 (invalid_client ...)` | client id, `kid` vs JWKS, JWKS reachable by the EHR, `aud` = exact token URL, RS384 |
| `authentication rejected by the EHR` on FHIR calls | token valid but tenant/allow-list; open a Cerner service record |
| `the EHR denied access` (403) | scopes registered for the app vs `*_SCOPE` |
| athenahealth 400 on search | `ATHENA_PRACTICE_ID` wrong or missing |
| `Summary failed (...)` | AI host reachable from the server, key/model names, `AI_TIMEOUT` |
| browser loops to Microsoft sign-in | see SSO_SETUP.md troubleshooting (redirect URI, https, cookies) |

## Remaining prerequisites (not solved by code)

* TLS termination and network access control in front of port 8000.
* The proxy must pass `/auth/*` and `/api/*` through unchanged and serve `SSO_BASE_URL` over https (the session cookie is `Secure`).
* Organisational approval (BAA / data governance) for the chosen AI provider; the UI shows where facts are sent.
* Log retention/forwarding policy for `/var/log/fhir-bridge`.
* Key rotation procedure (AUTH_SETUP.md) and backup of `/etc/fhir-bridge`.
* Single worker process: token caches are in-process. Scale by running one instance.
