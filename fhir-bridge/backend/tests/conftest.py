"""Shared fixtures: synthetic settings, fake EHR providers and a configured app.
No network. All identifiers and names are synthetic."""
from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import AIConfig, EHRConfig, Settings
from app.fhir_client import FHIRError
from app.main import app, configure
from app.models import (
    AllergyItem,
    ConditionItem,
    EncounterItem,
    MedicationItem,
    ObservationItem,
    PatientSummaryCard,
)
from app.providers.base import EHRProvider


def ehr_cfg(name: str, **over) -> EHRConfig:
    base = dict(
        name=name, label=name, base_url=f"https://fhir.example/{name}", auth_method="client_secret_basic",
        token_url=f"https://auth.example/{name}/token", client_id="cid", client_secret="sec",
        scope="system/Patient.read",
    )
    if name == "athena":
        base["extra"] = {"practice_id": "12345"}
    base.update(over)
    return EHRConfig(**base)


def make_settings(**over) -> Settings:
    s = Settings(cerner=ehr_cfg("cerner"), athena=ehr_cfg("athena"), ai=AIConfig(provider="extractive"))
    for k, v in over.items():
        setattr(s, k, v)
    return s


def card(source, sid, given, family, dob, gender="female", **kw) -> PatientSummaryCard:
    return PatientSummaryCard(source=source, source_id=sid, full_name=f"{given} {family}", given_name=given,
                              family_name=family, birth_date=dob, gender=gender, **kw)


class FakeProvider(EHRProvider):
    """In-memory provider for API tests. `fail` raises a FHIRError on search."""

    def __init__(self, source: str, patients: list[PatientSummaryCard], fail: FHIRError | None = None):
        self.source, self.label = source, source
        self.patients = {p.source_id: p for p in patients}
        self.fail = fail
        self.calls: list[str] = []

    async def search_patients(self, *, given=None, family=None, birth_date=None, gender=None, max_results=25):
        self.calls.append("search")
        if self.fail:
            raise self.fail
        return [p for p in self.patients.values() if not family or p.family_name == family][:max_results], False

    async def get_patient(self, patient_id):
        return self.patients.get(patient_id)

    async def get_conditions(self, patient_id):
        return [ConditionItem(source=self.source, text="Hypertension", clinical_status="active")], False

    async def get_medications(self, patient_id):
        return [MedicationItem(source=self.source, text="Lisinopril 10 mg", status="active")], False

    async def get_allergies(self, patient_id):
        return [AllergyItem(source=self.source, text="Penicillin", clinical_status="active")], False

    async def get_observations(self, patient_id):
        return [ObservationItem(source=self.source, text="Heart rate", value="72 /min")], True

    async def get_encounters(self, patient_id):
        if self.fail:
            raise self.fail
        return [EncounterItem(source=self.source, text="Office visit", period_start="2025-01-02")], False

    async def test_auth(self):
        return True, "fake"


class FakeSummarizer:
    name = "fake:model"
    data_destination = "ai.example"

    def __init__(self, text="SUMMARY", error: Exception | None = None):
        self.text, self.error, self.prompts = text, error, []

    async def complete(self, system, user):
        self.prompts.append((system, user))
        if self.error:
            raise self.error
        return self.text


@pytest.fixture
def providers():
    return {
        "cerner": FakeProvider("cerner", [card("cerner", "c1", "Jane", "Doe", "1980-01-01"),
                                          card("cerner", "c2", "Janet", "Doe", "1985-05-05")]),
        "athena": FakeProvider("athena", [card("athena", "a-1.E-1", "Jane", "Doe", "1980-01-01")]),
    }


@pytest.fixture
def client(providers):
    configure(app, make_settings(), providers=providers, summarizer=FakeSummarizer())
    with TestClient(app) as c:
        yield c


def mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)
