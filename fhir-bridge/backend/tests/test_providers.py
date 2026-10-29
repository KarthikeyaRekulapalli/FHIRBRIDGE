import asyncio

import httpx

from app.fhir_client import FHIRClient
from app.providers import build_providers
from app.providers.fhir_provider import AthenaProvider, CernerProvider
from tests.conftest import ehr_cfg, make_settings


def _provider(cls, name):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "T", "expires_in": 3600})
        rtype = request.url.path.rsplit("/", 1)[-1]
        if rtype == "Patient":
            return httpx.Response(200, json={"resourceType": "Bundle", "entry": [
                {"resource": {"resourceType": "Patient", "id": "p1", "name": [{"family": "Doe", "given": ["Jane"]}],
                              "birthDate": "1980-01-01", "gender": "female"}},
                {"resource": {"resourceType": "Patient", "id": "p1", "name": [{"family": "Old"}]}},
            ]})
        return httpx.Response(200, json={"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": rtype, "id": "r1", "code": {"text": "X"}}}]})

    cfg = ehr_cfg(name)
    return cls(cfg, FHIRClient(cfg, transport=httpx.MockTransport(handler))), seen


def test_cerner_condition_search_uses_both_categories():
    p, seen = _provider(CernerProvider, "cerner")
    items, _ = asyncio.run(p.get_conditions("p1"))
    cats = [r.url.params.get("category") for r in seen if r.url.path.endswith("/Condition")]
    assert cats == ["problem-list-item", "encounter-diagnosis"]
    assert all(r.url.params["patient"] == "p1" for r in seen if r.url.path.endswith("/Condition"))
    assert len(items) == 2 and items[0].source == "cerner"


def test_athena_searches_carry_ah_practice_and_cerner_does_not():
    a, seen_a = _provider(AthenaProvider, "athena")
    cards, _ = asyncio.run(a.search_patients(family="Doe", gender="female"))
    req = [r for r in seen_a if r.url.path.endswith("/Patient")][0]
    assert req.url.params["ah-practice"] == "Organization/a-1.Practice-12345"
    assert req.url.params["family"] == "Doe" and req.url.params["gender"] == "female"
    assert len(cards) == 1 and cards[0].source_id == "p1" and cards[0].source == "athena"  # de-duplicated
    asyncio.run(a.get_medications("p1"))
    assert all("ah-practice" in r.url.params for r in seen_a if not r.url.path.endswith("/token"))

    c, seen_c = _provider(CernerProvider, "cerner")
    asyncio.run(c.search_patients(given="Jane"))
    assert "ah-practice" not in [r for r in seen_c if r.url.path.endswith("/Patient")][0].url.params


def test_search_requires_a_demographic_term():
    p, _ = _provider(CernerProvider, "cerner")
    try:
        asyncio.run(p.search_patients(gender="female"))
        raise AssertionError("expected FHIRError")
    except Exception as exc:
        assert "required" in str(exc)


def test_build_providers_skips_unconfigured_and_disabled():
    s = make_settings()
    s.athena = ehr_cfg("athena", client_id="")
    assert list(build_providers(s)) == ["cerner"]
    s.cerner.enabled = False
    assert build_providers(s) == {}
