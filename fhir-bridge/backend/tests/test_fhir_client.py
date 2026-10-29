import asyncio

import httpx
import pytest

from app.fhir_client import FHIRClient, FHIRError
from tests.conftest import ehr_cfg


def bundle(ids, next_url=None, rtype="Patient"):
    b = {"resourceType": "Bundle", "entry": [{"resource": {"resourceType": rtype, "id": i}} for i in ids]}
    if next_url:
        b["link"] = [{"relation": "next", "url": next_url}]
    return b


def make_client(handler, **kw):
    kw.setdefault("max_pages", 3)
    return FHIRClient(ehr_cfg("cerner"), transport=httpx.MockTransport(handler), **kw)


def _token_or(handler):
    def h(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "T1", "expires_in": 3600})
        return handler(request)
    return h


def test_search_sends_bearer_and_accept_and_follows_pages():
    seen = []

    def handler(request):
        seen.append(request)
        if "page=2" in str(request.url):
            return httpx.Response(200, json=bundle(["3"]))
        return httpx.Response(200, json=bundle(["1", "2"], "https://fhir.example/cerner/Patient?page=2"))

    c = make_client(_token_or(handler))
    r = asyncio.run(c.search("Patient", {"family": "Doe", "_count": "10"}))
    assert [x["id"] for x in r.resources] == ["1", "2", "3"] and not r.truncated
    first = [s for s in seen if s.url.path.endswith("/Patient")][0]
    assert first.headers["authorization"] == "Bearer T1"
    assert first.headers["accept"] == "application/fhir+json"
    assert first.url.params["family"] == "Doe"
    second = [s for s in seen if "page=2" in str(s.url)][0]
    assert "family" not in second.url.params  # next link used verbatim


def test_pagination_cap_sets_truncated():
    def handler(request):
        return httpx.Response(200, json=bundle(["x"], "https://fhir.example/cerner/Patient?page=n"))

    r = asyncio.run(make_client(_token_or(handler), max_pages=2).search("Patient", {"family": "a"}))
    assert len(r.resources) == 2 and r.truncated


def test_retry_on_503_then_success_and_retry_after():
    n = {"calls": 0}

    def handler(request):
        n["calls"] += 1
        if n["calls"] < 3:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(200, json=bundle(["1"]))

    c = make_client(_token_or(handler), max_attempts=3)
    r = asyncio.run(c.search("Patient", {"family": "a"}))
    assert len(r.resources) == 1 and n["calls"] == 3


def test_rate_limit_exhausted_is_rate_limited_kind():
    def handler(request):
        return httpx.Response(429, headers={"Retry-After": "0"})

    with pytest.raises(FHIRError) as exc:
        asyncio.run(make_client(_token_or(handler), max_attempts=2).search("Patient", {"family": "a"}))
    assert exc.value.kind == "rate_limited"


def test_401_refreshes_token_once_then_fails_as_auth():
    tokens = iter(["T1", "T2"])
    seen = []

    def handler(request):
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": next(tokens), "expires_in": 3600})
        seen.append(request.headers["authorization"])
        return httpx.Response(401, json={"resourceType": "OperationOutcome", "issue": [{"diagnostics": "PHI?"}]})

    with pytest.raises(FHIRError) as exc:
        asyncio.run(make_client(handler).search("Patient", {"family": "a"}))
    assert seen == ["Bearer T1", "Bearer T2"]
    assert exc.value.kind == "auth" and "PHI?" not in str(exc.value)


def test_403_and_404_are_not_retried():
    n = {"calls": 0}

    def handler(request):
        n["calls"] += 1
        return httpx.Response(403)

    with pytest.raises(FHIRError) as exc:
        asyncio.run(make_client(_token_or(handler)).search("Condition", {"patient": "1"}))
    assert exc.value.kind == "forbidden" and n["calls"] == 1

    def nf(request):
        return httpx.Response(404)

    assert asyncio.run(make_client(_token_or(nf)).read("Patient", "zzz")) is None


def test_invalid_json_and_timeout():
    def bad(request):
        return httpx.Response(200, content=b"<html>not fhir</html>")

    with pytest.raises(FHIRError) as exc:
        asyncio.run(make_client(_token_or(bad)).search("Patient", {"family": "a"}))
    assert exc.value.kind == "invalid_response"

    def slow(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(FHIRError) as exc:
        asyncio.run(make_client(_token_or(slow), max_attempts=1).search("Patient", {"family": "a"}))
    assert exc.value.kind == "timeout"


def test_token_failure_surfaces_as_auth_error():
    def handler(request):
        return httpx.Response(400, json={"error": "invalid_client"})

    with pytest.raises(FHIRError) as exc:
        asyncio.run(make_client(handler).search("Patient", {"family": "a"}))
    assert exc.value.kind == "auth" and "invalid_client" in str(exc.value)
    ok, detail = asyncio.run(make_client(handler).test_auth())
    assert ok is False and "invalid_client" in detail
