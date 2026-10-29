# Code guide

```
fhir-bridge/
├─ backend/app/            FastAPI service
│  ├─ config.py            Settings from env/.env; EHRConfig.problems(), Settings.problems()
│  ├─ security.py          Microsoft Entra sign-in (/auth/*), session cookie, require_user
│  ├─ logging_config.py    rotating file + console; no PHI/secrets
│  ├─ models.py            pydantic API models (source-tagged, provenance kept)
│  ├─ auth.py              TokenProvider: client_secret_basic | private_key_jwt | none
│  ├─ fhir_client.py       FHIRClient: pooled httpx, retries, 401 refresh, paging, FHIRError(kind)
│  ├─ mapping.py           FHIR R4 / US Core -> models
│  ├─ matching.py          assess_pair / cluster_across_sources (evidence + conflicts)
│  ├─ aggregate.py         fetch_records: per-selection clinical fan-out
│  ├─ providers/           EHRProvider interface; FHIRProvider, CernerProvider, AthenaProvider; build_providers
│  ├─ ai/                  Summarizer protocol, build_facts (input budget), providers, summarize()
│  └─ main.py              routes, lifespan (validate config, build providers/summarizer), request log
├─ backend/tests/          network-free pytest suite (fakes + httpx MockTransport)
├─ backend/tools/          generate_keys.py, live_check.py (staged read-only checks), dev_fake_server.py (dev only)
├─ frontend/               index.html, app.js, styles.css (no build step)
├─ deploy/ubuntu/          systemd unit + install.sh
├─ docs/                   GitHub Pages root for the public JWKS
└─ .github/workflows/      ci.yml (ruff, pytest, node --check), pages.yml (publish JWKS)
```

Conventions: configuration only through environment variables; every outbound
failure becomes a typed error with an operator-safe message; nothing is logged
that identifies a patient; tests inject providers/summarizers via
`main.configure(app, settings, providers, summarizer)`.
