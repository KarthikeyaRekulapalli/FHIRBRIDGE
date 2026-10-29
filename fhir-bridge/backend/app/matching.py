"""Deterministic, explainable cross-EHR patient matching.

A pair of records from *different* EHRs becomes a candidate match only when
their birth dates are identical AND their names are similar. Name similarity
alone never groups records; a missing birth date never groups records. Gender
disagreement does not block a candidate but is surfaced as a conflict. The
result is a candidate the user must review and confirm; nothing here is an
authority on identity.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .models import MatchCluster, PatientSummaryCard

NAME_THRESHOLD = 0.80


def _norm(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join("".join(ch for ch in text.lower() if ch.isalnum() or ch.isspace()).split())


def _ratio(a: str | None, b: str | None) -> float:
    a, b = _norm(a), _norm(b)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def score_against_query(card: PatientSummaryCard, *, given: str | None, family: str | None,
                        birth_date: str | None, gender: str | None) -> float:
    """0..1 agreement between a record and the search terms (for ranking only)."""
    parts = []  # (weight, similarity) for each supplied term
    if given:
        parts.append((0.30, _ratio(given, card.given_name or card.full_name)))
    if family:
        parts.append((0.30, _ratio(family, card.family_name or card.full_name)))
    if birth_date:
        parts.append((0.30, float(card.birth_date == birth_date)))
    if gender:
        parts.append((0.10, float((card.gender or "").lower() == gender.lower())))
    weights = sum(w for w, _ in parts)
    return round(sum(w * s for w, s in parts) / weights, 3) if weights else 0.0


@dataclass
class PairAssessment:
    candidate: bool
    confidence: float
    evidence: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


def assess_pair(a: PatientSummaryCard, b: PatientSummaryCard) -> PairAssessment:
    """Compare two records field by field. See module docstring for the rule."""
    name_sim = max(_ratio(a.full_name, b.full_name),
                   0.5 * _ratio(a.given_name, b.given_name) + 0.5 * _ratio(a.family_name, b.family_name))
    ev, conf = [], []
    if not a.birth_date or not b.birth_date:
        conf.append("birth date missing in one record")
        dob_ok = False
    elif a.birth_date == b.birth_date:
        ev.append(f"birth date {a.birth_date}")
        dob_ok = True
    else:
        conf.append(f"birth date differs ({a.birth_date} vs {b.birth_date})")
        dob_ok = False
    if name_sim >= NAME_THRESHOLD:
        ev.append("name" if name_sim >= 0.99 else f"name similar ({name_sim:.0%})")
    else:
        conf.append(f"name differs ({a.full_name} vs {b.full_name})")
    if a.gender and b.gender:
        (ev if a.gender == b.gender else conf).append(
            "gender" if a.gender == b.gender else f"gender differs ({a.gender} vs {b.gender})")
    else:
        conf.append("gender missing in one record")
    candidate = dob_ok and name_sim >= NAME_THRESHOLD
    confidence = round(0.6 * name_sim + 0.3 * dob_ok + 0.1 * (bool(a.gender and a.gender == b.gender)), 3)
    return PairAssessment(candidate, confidence, ev, conf)


def cluster_across_sources(cards: list[PatientSummaryCard]) -> list[MatchCluster]:
    """Greedy grouping: a record joins an existing group only if it is a candidate
    match with every member and the group has no record from the same EHR."""
    groups: list[list[PatientSummaryCard]] = []
    assessments: list[list[PairAssessment]] = []
    for card in cards:
        placed = False
        for members, pa in zip(groups, assessments):
            if any(m.source == card.source for m in members):
                continue
            results = [assess_pair(card, m) for m in members]
            if all(r.candidate for r in results):
                members.append(card)
                pa.extend(results)
                placed = True
                break
        if not placed:
            groups.append([card])
            assessments.append([])

    out = []
    for i, (members, pa) in enumerate(zip(groups, assessments)):
        anchor = max(members, key=lambda m: m.match_score)
        multi = len(members) > 1
        evidence = sorted({e for r in pa for e in r.evidence})
        conflicts = sorted({c for r in pa for c in r.conflicts})
        out.append(MatchCluster(
            cluster_id=f"cluster-{i + 1}", display_name=anchor.full_name,
            birth_date=anchor.birth_date, gender=anchor.gender, members=members,
            confidence=min(r.confidence for r in pa) if multi else None,
            evidence=evidence, conflicts=conflicts,
        ))
    out.sort(key=lambda c: (c.confidence is not None, c.confidence or 0, c.members[0].match_score), reverse=True)
    return out
