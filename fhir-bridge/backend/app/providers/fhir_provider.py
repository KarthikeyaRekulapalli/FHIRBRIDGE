"""EHR adapters backed by a FHIR R4 server.

FHIRProvider holds the shared FHIR R4 / US Core behaviour. The two vendor
subclasses carry only the documented differences:

  CernerProvider  - Condition search requires `category`; searches run against
                    https://fhir-ehr.cerner.com/r4/<tenant> with a token from
                    authorization.cerner.com (SMART Backend Services).
  AthenaProvider  - with system (2-legged) scopes every search except `_id`
                    must carry `ah-practice=Organization/a-1.Practice-<id>`;
                    patient ids look like `a-<practice>.E-<n>`.
"""
from __future__ import annotations

from ..config import EHRConfig
from ..fhir_client import FHIRClient, FHIRError
from ..mapping import (
    allergy_item,
    condition_item,
    encounter_item,
    medication_item,
    observation_item,
    patient_card,
)
from ..models import (
    AllergyItem,
    ConditionItem,
    EncounterItem,
    MedicationItem,
    ObservationItem,
    PatientSummaryCard,
    Source,
)
from .base import EHRProvider


class FHIRProvider(EHRProvider):
    source: Source
    condition_categories: tuple[str | None, ...] = (None,)

    def __init__(self, cfg: EHRConfig, client: FHIRClient) -> None:
        self.cfg = cfg
        self.label = cfg.label
        self.client = client

    def _search_params(self, params: dict[str, str]) -> dict[str, str]:
        """Hook for vendor-wide search parameters."""
        return params

    async def _search(self, resource: str, params: dict[str, str]) -> tuple[list[dict], bool]:
        r = await self.client.search(resource, self._search_params(params))
        return r.resources, r.truncated

    async def search_patients(self, *, given=None, family=None, birth_date=None, gender=None,
                              max_results=25) -> tuple[list[PatientSummaryCard], bool]:
        if not (given or family or birth_date):
            raise FHIRError("invalid_response", "at least one of given / family / birth_date is required")
        params = {"_count": str(max_results)}
        if given:
            params["given"] = given
        if family:
            params["family"] = family
        if birth_date:
            params["birthdate"] = birth_date
        if gender:
            params["gender"] = gender
        resources, truncated = await self._search("Patient", params)
        seen: set[str] = set()
        cards: list[PatientSummaryCard] = []
        for r in resources:
            card = patient_card(r, self.source)
            if card.source_id and card.source_id not in seen:
                seen.add(card.source_id)
                cards.append(card)
        if len(cards) > max_results:
            cards, truncated = cards[:max_results], True
        return cards, truncated

    async def get_patient(self, patient_id: str) -> PatientSummaryCard | None:
        res = await self.client.read("Patient", patient_id)
        return patient_card(res, self.source) if res else None

    async def get_conditions(self, patient_id: str) -> tuple[list[ConditionItem], bool]:
        out: list[ConditionItem] = []
        truncated = False
        for cat in self.condition_categories:
            params = {"patient": patient_id}
            if cat:
                params["category"] = cat
            resources, t = await self._search("Condition", params)
            out.extend(condition_item(r, self.source) for r in resources)
            truncated = truncated or t
        return out, truncated

    async def get_medications(self, patient_id: str) -> tuple[list[MedicationItem], bool]:
        resources, t = await self._search("MedicationRequest", {"patient": patient_id})
        return [medication_item(r, self.source) for r in resources], t

    async def get_allergies(self, patient_id: str) -> tuple[list[AllergyItem], bool]:
        resources, t = await self._search("AllergyIntolerance", {"patient": patient_id})
        return [allergy_item(r, self.source) for r in resources], t

    async def get_observations(self, patient_id: str) -> tuple[list[ObservationItem], bool]:
        # Vital signs: a required US Core category both vendors support.
        resources, t = await self._search(
            "Observation", {"patient": patient_id, "category": "vital-signs", "_count": "50"})
        return [observation_item(r, self.source) for r in resources], t

    async def get_encounters(self, patient_id: str) -> tuple[list[EncounterItem], bool]:
        resources, t = await self._search("Encounter", {"patient": patient_id, "_count": "50"})
        return [encounter_item(r, self.source) for r in resources], t

    async def test_auth(self) -> tuple[bool, str]:
        return await self.client.test_auth()

    async def aclose(self) -> None:
        await self.client.aclose()


class CernerProvider(FHIRProvider):
    source = "cerner"
    # Cerner rejects Condition searches without a category.
    condition_categories = ("problem-list-item", "encounter-diagnosis")


class AthenaProvider(FHIRProvider):
    source = "athena"

    def _search_params(self, params: dict[str, str]) -> dict[str, str]:
        practice = self.cfg.extra.get("practice_id", "")
        return {**params, "ah-practice": f"Organization/a-1.Practice-{practice}"}


PROVIDER_CLASSES: dict[str, type[FHIRProvider]] = {"cerner": CernerProvider, "athena": AthenaProvider}
