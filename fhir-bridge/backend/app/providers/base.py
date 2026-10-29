"""Interface every EHR adapter implements. Routes and aggregation only use this."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import (
    AllergyItem,
    ConditionItem,
    EncounterItem,
    MedicationItem,
    ObservationItem,
    PatientSummaryCard,
    Source,
)


class EHRProvider(ABC):
    source: Source
    label: str

    @abstractmethod
    async def search_patients(self, *, given: str | None = None, family: str | None = None,
                              birth_date: str | None = None, gender: str | None = None,
                              max_results: int = 25) -> tuple[list[PatientSummaryCard], bool]:
        """Return (cards, truncated)."""

    @abstractmethod
    async def get_patient(self, patient_id: str) -> PatientSummaryCard | None: ...

    @abstractmethod
    async def get_conditions(self, patient_id: str) -> tuple[list[ConditionItem], bool]: ...

    @abstractmethod
    async def get_medications(self, patient_id: str) -> tuple[list[MedicationItem], bool]: ...

    @abstractmethod
    async def get_allergies(self, patient_id: str) -> tuple[list[AllergyItem], bool]: ...

    @abstractmethod
    async def get_observations(self, patient_id: str) -> tuple[list[ObservationItem], bool]: ...

    @abstractmethod
    async def get_encounters(self, patient_id: str) -> tuple[list[EncounterItem], bool]: ...

    async def test_auth(self) -> tuple[bool, str]:
        return True, "no authentication"

    async def aclose(self) -> None:
        return None
