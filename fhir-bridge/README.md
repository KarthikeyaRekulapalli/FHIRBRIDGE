# FHIR EHR Bridge

Authors: Claude and Karthi.

A small service that searches **Cerner / Oracle Health** and **athenahealth** over
FHIR R4, shows candidate cross-EHR patient matches with the evidence for each,
lets a user review and confirm which records belong together, and generates an
AI summary of exactly those records. Python 3.11+ / FastAPI backend, static
HTML/JS frontend, no build step. Deployment target: Ubuntu (systemd).

Status: **not verified against live EHRs.** Configuration, authentication and
retrieval code are covered by network-free tests; live checks need credentials
(see the "Verify" section below).

| Document | Contents |
|---|---|
| ARCHITECTURE.md | Components, sequence diagrams, data boundaries |
| AUTH_SETUP.md | EHR keys, JWKS, token flow, portal settings |
| SSO_SETUP.md | Microsoft Entra (Azure AD) sign-in: app registration, who may sign in, settings |
| AI_PROVIDERS.md | Summarization providers, settings, what data leaves the host |
| DEPLOY_UBUNTU.md | Install, service, permissions, health, logs, troubleshooting |
| CODE_GUIDE.md | What each file does |
| DECISIONS.md | Removed files and important decisions |

## Run locally (development)

```bash
cp backend/.env.example .env      # fill in the EHR blocks you have credentials for
./run.sh                          # http://127.0.0.1:8000
```

Windows (PowerShell): `cd backend; py -3.13 -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt; .\.venv\Scripts\python -m uvicorn app.main:app`.

No EHR, tenant, patient or user is selected by default. An EHR whose block is
incomplete shows as *not configured* in the UI with the missing variable names.
To try the UI without credentials, run `python backend/tools/dev_fake_server.py`
(synthetic in-memory records, development only).

## Verify a deployment (read-only, staged)

```bash
cd backend
python tools/live_check.py --stage config
python tools/live_check.py --stage token
python tools/live_check.py --stage search --family <name>
python tools/live_check.py --stage records --source cerner --patient <id from the search>
python tools/live_check.py --stage ai        # pings the AI provider; sends no patient data
```

## API

All `/api/*` routes except `/api/health` require a signed-in Microsoft Entra user
(session cookie from `/auth/login`; see SSO_SETUP.md). SSO is mandatory in
production; in development with no `SSO_*` settings the API is open.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness, whether SSO is on |
| GET | `/api/config` | provider states, AI provider and data destination, limits, config problems |
| GET | `/api/auth/test/{source}` | acquire an EHR token only |
| GET | `/auth/login`, `/auth/callback`, `/auth/logout` | Microsoft sign-in / sign-out |
| GET | `/api/search?given=&family=&birth_date=&gender=&sources=&max_results=` | search, rank, group candidates |
| POST | `/api/records` | clinical data for selected records, no AI |
| POST | `/api/summary` | records + AI summary; `confirmed_same_person: true` required for more than one record |

## Tests

```bash
cd backend && pip install pytest ruff
pytest -q && ruff check app tools tests
```

All tests are network-free (httpx mock transports, fake providers). Live
connectivity is covered by `tools/live_check.py`, which must be run by an
operator with credentials.

## Clinical safety

Summaries are labelled AI-generated for clinician review, keep attribution to
each EHR, separate documented facts from conflicts and missing information, and
are always shown with the source records. Patient matching never merges records
on name alone and always requires user confirmation. This is not a certified
clinical system; see DEPLOY_UBUNTU.md for remaining operational prerequisites.
