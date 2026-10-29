"""Deterministic, in-process summary. No model, no network. Useful when no AI
provider is approved yet; always labelled as rule-based in the output."""
from __future__ import annotations

from ..models import PatientClinicalSummary


def _capped(items: set[str], cap: int = 10, empty: str = "none recorded") -> str:
    if not items:
        return empty
    ordered = sorted(items)
    return ", ".join(ordered[:cap]) + (f", and {len(ordered) - cap} more" if len(ordered) > cap else "")


def extractive_summary(per_source: list[PatientClinicalSummary]) -> str:
    sources = ", ".join(sorted({s.patient.source for s in per_source}))
    conditions = {c.text for s in per_source for c in s.conditions}
    meds = {m.text for s in per_source for m in s.medications
            if (m.status or "active").lower() in {"active", "completed", "intended", "on-hold", ""}}
    allergies = {a.text for s in per_source for a in s.allergies
                 if (a.clinical_status or "active").lower() == "active"}
    parts = [
        f"Documented facts (rule-based, from {sources}).",
        "Problems: " + _capped(conditions) + ".",
        "Medications: " + _capped(meds) + ".",
        "Allergies: " + _capped(allergies, empty="no active allergies recorded") + ".",
    ]
    if len(per_source) > 1:
        cond_sets = {s.patient.source: {c.text for c in s.conditions} for s in per_source}
        only = {src: vals - set().union(*(v for o, v in cond_sets.items() if o != src))
                for src, vals in cond_sets.items()}
        only = {k: v for k, v in only.items() if v}
        parts.append("Conflicts between sources: " + (
            "; ".join(f"{src}-only problems: {', '.join(sorted(v))}" for src, v in only.items()) or "none identified") + ".")
    missing = [f"{s.patient.source} {', '.join(s.fetch_errors)} unavailable" for s in per_source if s.fetch_errors]
    parts.append("Missing information: " + ("; ".join(missing) if missing else "none identified") + ".")
    return " ".join(parts)


class ExtractiveSummarizer:
    name = "extractive:rule-based"
    data_destination = "local process"

    async def complete(self, system: str, user: str) -> str:  # pragma: no cover - not used
        raise NotImplementedError("extractive summarizer works on structured records, see summarize()")
