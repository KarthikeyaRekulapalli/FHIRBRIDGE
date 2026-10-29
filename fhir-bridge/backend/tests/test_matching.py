from app.matching import assess_pair, cluster_across_sources, score_against_query
from tests.conftest import card


def multi(clusters):
    return [c for c in clusters if len(c.members) > 1]


def test_exact_demographics_are_a_candidate_with_evidence():
    a, b = card("cerner", "1", "Jane", "Doe", "1980-01-01"), card("athena", "2", "Jane", "Doe", "1980-01-01")
    cl = cluster_across_sources([a, b])
    assert len(multi(cl)) == 1
    c = multi(cl)[0]
    assert c.confidence and c.confidence >= 0.9
    assert "birth date 1980-01-01" in c.evidence and "name" in c.evidence and "gender" in c.evidence
    assert c.conflicts == []
    assert {m.source_id for m in c.members} == {"1", "2"}  # source ids preserved


def test_similar_name_different_dob_is_not_merged():
    a, b = card("cerner", "1", "Jane", "Doe", "1980-01-01"), card("athena", "2", "Jane", "Doe", "1981-01-01")
    assert multi(cluster_across_sources([a, b])) == []
    pa = assess_pair(a, b)
    assert not pa.candidate and any("birth date differs" in c for c in pa.conflicts)


def test_missing_dob_never_merges():
    a, b = card("cerner", "1", "Jane", "Doe", None), card("athena", "2", "Jane", "Doe", "1980-01-01")
    assert multi(cluster_across_sources([a, b])) == []
    assert any("missing" in c for c in assess_pair(a, b).conflicts)


def test_same_dob_different_name_is_not_merged():
    a, b = card("cerner", "1", "Jane", "Doe", "1980-01-01"), card("athena", "2", "Mary", "Smith", "1980-01-01")
    assert multi(cluster_across_sources([a, b])) == []


def test_gender_conflict_stays_visible():
    a = card("cerner", "1", "Jane", "Doe", "1980-01-01", gender="female")
    b = card("athena", "2", "Jane", "Doe", "1980-01-01", gender="male")
    c = multi(cluster_across_sources([a, b]))[0]
    assert any("gender differs" in x for x in c.conflicts)
    assert c.confidence < 0.95


def test_same_source_never_grouped_and_names_normalised():
    a, b = card("cerner", "1", "Jane", "Doe", "1980-01-01"), card("cerner", "2", "Jane", "Doe", "1980-01-01")
    assert multi(cluster_across_sources([a, b])) == []
    c = card("athena", "3", "JANE", "DOE", "1980-01-01")
    assert len(multi(cluster_across_sources([a, b, c]))) == 1


def test_query_score():
    c = card("cerner", "1", "John", "Adam", "1981-07-04", gender="male")
    assert score_against_query(c, given="John", family="Adam", birth_date="1981-07-04", gender="male") == 1.0
    assert score_against_query(c, given=None, family="Adam", birth_date="1990-01-01", gender=None) == 0.5
