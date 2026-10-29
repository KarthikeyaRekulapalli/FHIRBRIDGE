"""Map raw FHIR R4 / US Core resources into our normalized models.

Both Cerner and Athenahealth expose FHIR R4 + US Core, so the same mapping
logic works for both; the caller just passes the right `source` tag.
"""
from __future__ import annotations

from typing import Any, Optional

from .models import (
    AllergyItem,
    ConditionItem,
    EncounterItem,
    MedicationItem,
    ObservationItem,
    PatientSummaryCard,
    Source,
)


def _human_name(resource: dict) -> tuple[str, Optional[str], Optional[str]]:
    """Return (full, family, given) preferring the official/current name."""
    names = resource.get("name") or []
    chosen = None
    for n in names:
        if isinstance(n, dict) and n.get("use") == "official":
            chosen = n
            break
    if chosen is None:
        # avoid "old" names if a current one exists
        current = [n for n in names if isinstance(n, dict) and n.get("use") != "old"]
        chosen = (current or names or [{}])[0]
    family = chosen.get("family")
    given_list = chosen.get("given") or []
    given = given_list[0] if given_list else None
    if chosen.get("text"):
        full = chosen["text"]
    else:
        parts = [" ".join(given_list)] if given_list else []
        if family:
            parts.append(family)
        full = " ".join(p for p in parts if p).strip() or "(unnamed)"
    return full, family, given


def _mrn(resource: dict) -> Optional[str]:
    for ident in resource.get("identifier", []) or []:
        coding = (((ident.get("type") or {}).get("coding")) or [{}])[0]
        if coding.get("code") == "MR" or "mrn" in (ident.get("system", "").lower()):
            return ident.get("value")
    return None  # never label another identifier type as the MRN


def _address(resource: dict) -> Optional[str]:
    addrs = resource.get("address") or []
    if not addrs:
        return None
    a = addrs[0]
    bits = []
    if a.get("line"):
        bits.append(", ".join(a["line"]))
    for key in ("city", "state", "postalCode"):
        if a.get(key):
            bits.append(a[key])
    return ", ".join(bits) or None


def _phone(resource: dict) -> Optional[str]:
    for t in resource.get("telecom", []) or []:
        if t.get("system") == "phone":
            return t.get("value")
    return None


def _cc_text(cc: Any) -> Optional[str]:
    """Extract human text from a CodeableConcept (or list of them)."""
    if not cc:
        return None
    if isinstance(cc, list):
        for item in cc:
            txt = _cc_text(item)
            if txt:
                return txt
        return None
    if isinstance(cc, dict):
        if cc.get("text"):
            return cc["text"]
        for coding in cc.get("coding", []) or []:
            if coding.get("display"):
                return coding["display"]
            if coding.get("code"):
                return coding["code"]
    return None


def patient_card(resource: dict, source: Source) -> PatientSummaryCard:
    full, family, given = _human_name(resource)
    return PatientSummaryCard(
        source=source,
        source_id=resource.get("id", ""),
        full_name=full,
        family_name=family,
        given_name=given,
        birth_date=resource.get("birthDate"),
        gender=resource.get("gender"),
        mrn=_mrn(resource),
        address=_address(resource),
        phone=_phone(resource),
    )


def condition_item(resource: dict, source: Source) -> ConditionItem:
    return ConditionItem(
        source=source,
        text=_cc_text(resource.get("code")) or "(unspecified condition)",
        clinical_status=_cc_text(resource.get("clinicalStatus")),
        category=_cc_text(resource.get("category")),
        onset=resource.get("onsetDateTime") or _cc_text(resource.get("onsetString")),
        recorded_date=resource.get("recordedDate"),
    )


def medication_item(resource: dict, source: Source) -> MedicationItem:
    text = _cc_text(resource.get("medicationCodeableConcept"))
    if not text and resource.get("medicationReference"):
        text = resource["medicationReference"].get("display")
    dosage = None
    di = resource.get("dosageInstruction") or []
    if di:
        dosage = di[0].get("text")
    return MedicationItem(
        source=source,
        text=text or "(unspecified medication)",
        status=resource.get("status"),
        authored_on=resource.get("authoredOn"),
        dosage=dosage,
    )


def allergy_item(resource: dict, source: Source) -> AllergyItem:
    reaction = None
    reactions = resource.get("reaction") or []
    if reactions:
        manifestations = reactions[0].get("manifestation") or []
        reaction = _cc_text(manifestations)
    return AllergyItem(
        source=source,
        text=_cc_text(resource.get("code")) or "(unspecified allergy)",
        clinical_status=_cc_text(resource.get("clinicalStatus")),
        criticality=resource.get("criticality"),
        reaction=reaction,
    )


def observation_item(resource: dict, source: Source) -> ObservationItem:
    value = None
    if "valueQuantity" in resource:
        q = resource["valueQuantity"]
        value = f"{q.get('value', '')} {q.get('unit', '')}".strip()
    elif "valueString" in resource:
        value = resource["valueString"]
    elif "valueCodeableConcept" in resource:
        value = _cc_text(resource["valueCodeableConcept"])
    return ObservationItem(
        source=source,
        text=_cc_text(resource.get("code")) or "(unspecified observation)",
        value=value,
        effective=resource.get("effectiveDateTime") or resource.get("issued"),
        category=_cc_text(resource.get("category")),
    )


def encounter_item(resource: dict, source: Source) -> EncounterItem:
    period = resource.get("period") or {}
    text = _cc_text(resource.get("type")) or _cc_text(resource.get("class")) or "Encounter"
    return EncounterItem(
        source=source,
        text=text,
        status=resource.get("status"),
        period_start=period.get("start"),
        period_end=period.get("end"),
    )
