"""Normalized, source-tagged API models. Every record keeps its `source` and the
EHR's own `source_id`, so provenance survives matching and summarization."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Source = Literal["cerner", "athena"]


class PatientSummaryCard(BaseModel):
    source: Source
    source_id: str
    full_name: str
    family_name: Optional[str] = None
    given_name: Optional[str] = None
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    mrn: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    match_score: float = 0.0   # 0..1 agreement with the search terms


class MatchCluster(BaseModel):
    """Records from different EHRs that are *candidates* for being one person.
    The user must still confirm before records are combined."""
    cluster_id: str
    display_name: str
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    members: list[PatientSummaryCard]
    confidence: Optional[float] = None   # only for multi-source candidates
    evidence: list[str] = Field(default_factory=list)   # fields that agree
    conflicts: list[str] = Field(default_factory=list)  # fields that disagree or are missing


class SearchResponse(BaseModel):
    query: dict
    results: list[PatientSummaryCard]
    clusters: list[MatchCluster] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)    # per-source failures (sanitized)
    truncated: list[str] = Field(default_factory=list)  # sources that hit the page cap


class ConditionItem(BaseModel):
    source: Source
    text: str
    clinical_status: Optional[str] = None
    category: Optional[str] = None
    onset: Optional[str] = None
    recorded_date: Optional[str] = None


class MedicationItem(BaseModel):
    source: Source
    text: str
    status: Optional[str] = None
    authored_on: Optional[str] = None
    dosage: Optional[str] = None


class AllergyItem(BaseModel):
    source: Source
    text: str
    clinical_status: Optional[str] = None
    criticality: Optional[str] = None
    reaction: Optional[str] = None


class ObservationItem(BaseModel):
    source: Source
    text: str
    value: Optional[str] = None
    effective: Optional[str] = None
    category: Optional[str] = None


class EncounterItem(BaseModel):
    source: Source
    text: str
    status: Optional[str] = None
    period_start: Optional[str] = None
    period_end: Optional[str] = None


class PatientClinicalSummary(BaseModel):
    """Everything pulled for one patient record from one source."""
    patient: PatientSummaryCard
    conditions: list[ConditionItem] = Field(default_factory=list)
    medications: list[MedicationItem] = Field(default_factory=list)
    allergies: list[AllergyItem] = Field(default_factory=list)
    observations: list[ObservationItem] = Field(default_factory=list)
    encounters: list[EncounterItem] = Field(default_factory=list)
    fetch_errors: list[str] = Field(default_factory=list)   # resource types that failed
    truncated: list[str] = Field(default_factory=list)      # resource types cut at the page cap


class Selection(BaseModel):
    source: Source
    patient_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")  # goes into the URL path


class RecordsRequest(BaseModel):
    selections: list[Selection] = Field(min_length=1)


class SummaryRequest(RecordsRequest):
    # Required when more than one record is selected: the user has reviewed the
    # candidate match and asserts these records belong to the same person.
    confirmed_same_person: bool = False


class SummaryResponse(BaseModel):
    sources: list[Source]
    per_source: list[PatientClinicalSummary]
    narrative: str
    provider: str          # e.g. "anthropic:claude-sonnet-5-5"
    data_destination: str  # where the facts were sent (host or "local process")
    omitted: list[str] = Field(default_factory=list)  # items not sent due to the input limit
    disclaimer: str
