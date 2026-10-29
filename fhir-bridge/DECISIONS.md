# Decisions and removed files

Authors: Claude and Karthi. Date of this pass: 2026-10-27.

## Removed (moved to `.removed/`, git-ignored, delete after review)

| File | Why |
|---|---|
| `run.ps1`, `deploy/windows/*`, `DEPLOY_WINDOWS.md` | Target is Ubuntu; replaced by `run.sh`, `deploy/ubuntu/`, `DEPLOY_UBUNTU.md`. Nothing else referenced them. |
| `backend/keys/jwks.json`, `backend/keys/public_key.pem`, `docs/.well-known/jwks.json` | Demo keypair whose private key had been published; must never be registered with an EHR. |
| `MODELS.md` | Replaced by `AI_PROVIDERS.md` (provider set changed). |

Deleted outright (superseded code): `backend/app/summarize.py` (now `app/ai/`),
`backend/tools/token_demo.py` (printed a live client assertion to stdout; `live_check.py --stage token` covers it),
`backend/tools/check_setup.py` (defaulted to searching family name "Smart"; replaced by `live_check.py`, which requires explicit terms),
`backend/tests/test_smoke.py` (replaced by the suite in `backend/tests/`).

Two stale copies of `CODE_GUIDE.md` and `MODELS.md` one level above this folder
were removed before open-sourcing; the current versions are `CODE_GUIDE.md` and `AI_PROVIDERS.md` here.

## Defaults removed from production workflows

* Cerner no longer defaults to the public open sandbox tenant with `auth_method=open`; every EHR must be configured explicitly, and `none` is refused in production.
* athenahealth no longer defaults to the preview token URL.
* UI: removed placeholder names, "Try: Sandy Smart / Fred Smart / John Adam" example searches, and the pre-checked source toggles; sources now come from `/api/config` and only ready providers are selectable.
* UI: removed the per-request summary-engine dropdown; the provider is a server decision and the UI shows which one and where data goes.
* `tools/check_setup.py` sample search (`--family Smart`) removed.

## Design decisions

* **Separate adapters per EHR** (`CernerProvider`, `AthenaProvider`) over one generic FHIR provider with flags, because athenahealth needs `ah-practice` on every system-scope search and Cerner needs Condition categories.
* **Candidate matching requires an identical birth date and name similarity >= 0.8.** Names alone never group; a missing birth date never groups; gender conflicts are shown, not hidden. Confirmation is explicit (`confirmed_same_person`) and the UI shows evidence/conflicts before asking.
* **No AI fallback.** A failing provider yields a 502; records stay available via `/api/records`. Switching providers silently would change where patient data is sent.
* **Hugging Face and generic OpenAI merged into `openai_compat`**: same protocol, different base URL.
* **Microsoft Entra sign-in, no roles** (2026-10-28, replaced the shared API key): who may use the app is an Entra assignment; the app only verifies the id_token and keeps an HttpOnly session cookie. Entra endpoints are the fixed v2.0 URLs for the tenant, so no discovery call. CORS support was deleted (same-origin UI only).
* **Startup fails in production on invalid configuration**; in development the app starts and lists problems in `/api/config` and the UI.
* **Partial results are flagged**, not hidden: `truncated` on search and per resource type, `fetch_errors` per record, `omitted` on summaries.
* **Logging** never includes names, identifiers or query strings; uvicorn's access log is disabled in the unit for the same reason.
* **Tools requested but unavailable**: `Graphify` and `Python Pywrites` exist neither as installed plugins nor on PyPI; diagrams are Mermaid in `ARCHITECTURE.md`. Ponytail (lazy senior dev mode) was active for the whole pass. Type checking: the `pyright-lsp` plugin is enabled, but no `pyright`/`mypy` binary is installed locally, so no type-check run is recorded.

## Verified in this pass

* `pytest`: 51 tests, network-free (config, auth, FHIR client, providers, matching, AI, API). `ruff`: clean. `node --check frontend/app.js`: clean.
* UI workflow exercised in a browser against `tools/dev_fake_server.py`: search, candidate grouping with evidence/conflicts, review panel, confirmed summary with provider/destination, source records, stale output cleared when the selection changes.

## Not verified

* A real Microsoft sign-in (no Entra app registration on the development machine; the flow is covered by tests with the token exchange stubbed).
* Any live EHR call (no credentials, keys or `.env` on the development machine).
* Any live AI provider call.
* Ubuntu install script and unit (written for systemd; not executed on an Ubuntu host from here).
