#!/usr/bin/env python3
"""DEVELOPMENT ONLY: serve the UI against synthetic in-memory EHR providers.

No EHR or AI provider is contacted; records are the fixtures from tests/conftest.py.
Use it to exercise the UI workflow (search, candidate review, retrieve, summarize)
without credentials. Never run this in production: it refuses APP_ENV=production.

    python tools/dev_fake_server.py            # http://127.0.0.1:8000
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn  # noqa: E402

from app.config import SSOConfig  # noqa: E402
from app.main import app, configure  # noqa: E402
from tests.conftest import FakeProvider, FakeSummarizer, card, make_settings  # noqa: E402

if os.getenv("APP_ENV", "").lower() == "production":
    sys.exit("dev_fake_server.py must not run with APP_ENV=production")

providers = {
    "cerner": FakeProvider("cerner", [
        card("cerner", "1001", "Alex", "Rivera", "1975-03-09", gender="male", mrn="MRN-C-1"),
        card("cerner", "1002", "Alexis", "Rivera", "1975-03-09", gender="female"),
        card("cerner", "1003", "Alex", "Rivera", "1990-11-30", gender="male"),
    ]),
    "athena": FakeProvider("athena", [
        card("athena", "a-1.E-501", "Alex", "Rivera", "1975-03-09", gender="male", mrn="MRN-A-9"),
        card("athena", "a-1.E-502", "Alex", "Rivera", None, gender="male"),
    ]),
}
# SSO_* variables, if set, enable real Microsoft sign-in against the fake records.
configure(app, make_settings(sso=SSOConfig.from_env()), providers=providers,
          summarizer=FakeSummarizer(text="Documented facts: synthetic summary for UI testing.\nConflicts between sources: none identified.\nMissing or unavailable information: none identified."))
uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
