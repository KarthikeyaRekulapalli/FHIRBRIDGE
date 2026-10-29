"""Fetch the clinical picture for explicitly selected records, concurrently.
A failed resource type is recorded in `fetch_errors` (never replaced by mock
data); a missing patient is an error for the whole selection."""
from __future__ import annotations

import asyncio

from .fhir_client import FHIRError
from .logging_config import get_logger
from .models import PatientClinicalSummary, Selection
from .providers import EHRProvider

log = get_logger(__name__)

RESOURCES = ("conditions", "medications", "allergies", "observations", "encounters")


class RecordsError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


async def fetch_one(provider: EHRProvider, patient_id: str) -> PatientClinicalSummary:
    errors: list[str] = []
    truncated: list[str] = []

    async def guarded(name: str):
        try:
            items, cut = await getattr(provider, f"get_{name}")(patient_id)
        except FHIRError as exc:
            log.warning("%s: %s unavailable (%s)", provider.source, name, exc.kind)
            errors.append(name)
            return []
        if cut:
            truncated.append(name)
        return items

    try:
        patient = await provider.get_patient(patient_id)
    except FHIRError as exc:
        raise RecordsError(str(exc), 502) from exc  # never 401: that means "sign in" to the UI
    if patient is None:
        raise RecordsError(f"{provider.source}: patient record not found", 404)
    results = await asyncio.gather(*(guarded(r) for r in RESOURCES))
    log.info("%s: fetched %s (errors=%d, truncated=%d)", provider.source,
             ", ".join(f"{r}={len(v)}" for r, v in zip(RESOURCES, results)), len(errors), len(truncated))
    return PatientClinicalSummary(patient=patient, fetch_errors=errors, truncated=truncated,
                                  **dict(zip(RESOURCES, results)))


async def fetch_records(providers: dict[str, EHRProvider], selections: list[Selection]) -> list[PatientClinicalSummary]:
    for s in selections:
        if s.source not in providers:
            raise RecordsError(f"source '{s.source}' is not configured", 400)
    return list(await asyncio.gather(*(fetch_one(providers[s.source], s.patient_id) for s in selections)))
