#!/usr/bin/env python3
"""Staged, read-only connectivity check against the configured EHRs and AI provider.

    python tools/live_check.py --stage config                  # validate configuration only
    python tools/live_check.py --stage token                   # + acquire a token per EHR
    python tools/live_check.py --stage search --family <name>  # + one patient search (explicit terms)
    python tools/live_check.py --stage records --source cerner --patient <id>   # + clinical resources
    python tools/live_check.py --stage ai                      # ping the AI provider, no patient data

Each stage prints PASS/FAIL with a sanitized reason. Nothing is written to any EHR
and no patient data is sent to the AI provider. Reads .env from the repo root or --env-file.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ai  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.models import Selection  # noqa: E402
from app.providers import build_providers  # noqa: E402

STAGES = ["config", "token", "search", "records", "ai"]


def report(ok: bool, label: str, detail: str = "") -> bool:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f": {detail}" if detail else ""))
    return ok


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=STAGES, default="token")
    ap.add_argument("--env-file", help="path to a .env file (default: ./.env or the repo root .env)")
    for flag in ("--given", "--family", "--birth-date", "--source", "--patient"):
        ap.add_argument(flag)
    args = ap.parse_args()
    upto = STAGES.index(args.stage)
    failures = 0

    settings = load_settings(args.env_file)
    problems = settings.problems()
    print(f"\n[config] env={settings.env}")
    for area, probs in problems.items():
        for p in probs:
            failures += not report(False, area, p)
    if not problems:
        report(True, "configuration complete")
    if failures and args.stage != "config":
        print("\nFix configuration before running later stages.")
        return 1
    if upto < 1:
        return 1 if failures else 0

    providers = build_providers(settings)
    try:
        print("\n[token]")
        for name, p in providers.items():
            ok, detail = await p.test_auth()
            failures += not report(ok, f"{name} token", detail)
        if upto < 2:
            return 1 if failures else 0

        print("\n[search]")
        if not (args.given or args.family or args.birth_date):
            failures += not report(False, "search", "pass --given / --family / --birth-date (no default search terms)")
        else:
            for name, p in providers.items():
                try:
                    cards, truncated = await p.search_patients(
                        given=args.given, family=args.family, birth_date=args.birth_date, max_results=5)
                    report(True, f"{name} patient search", f"{len(cards)} record(s){' (partial)' if truncated else ''}")
                except Exception as exc:  # noqa: BLE001
                    failures += not report(False, f"{name} patient search", str(exc))
        if upto < 3:
            return 1 if failures else 0

        print("\n[records]")
        if not (args.source and args.patient):
            failures += not report(False, "records", "pass --source and --patient (an id returned by the search stage)")
        elif args.source not in providers:
            failures += not report(False, "records", f"source '{args.source}' is not configured")
        else:
            from app.aggregate import RecordsError, fetch_records
            try:
                rec = (await fetch_records(providers, [Selection(source=args.source, patient_id=args.patient)]))[0]
                counts = ", ".join(f"{k}={len(getattr(rec, k))}" for k in
                                   ("conditions", "medications", "allergies", "observations", "encounters"))
                report(not rec.fetch_errors, f"{args.source} clinical resources",
                       counts + (f"; failed: {', '.join(rec.fetch_errors)}" if rec.fetch_errors else "")
                       + (f"; partial: {', '.join(rec.truncated)}" if rec.truncated else ""))
                failures += bool(rec.fetch_errors)
            except RecordsError as exc:
                failures += not report(False, f"{args.source} clinical resources", str(exc))
        if upto < 4:
            return 1 if failures else 0
    finally:
        for p in providers.values():
            await p.aclose()

    print("\n[ai]")
    try:
        s = ai.build_summarizer(settings.ai)
        if settings.ai.provider == "extractive":
            report(True, "ai provider", "extractive (local, no model)")
        else:
            text = await s.complete("Reply with the single word OK.", "Connectivity check. Reply OK.")
            report(True, f"ai provider {s.name}", f"responded ({len(text)} chars) via {s.data_destination}")
    except ai.AIError as exc:
        failures += not report(False, "ai provider", str(exc))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
