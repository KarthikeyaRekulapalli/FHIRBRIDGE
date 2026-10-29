from fastapi.testclient import TestClient

from app import ai, security
from app.config import SSOConfig
from app.fhir_client import FHIRError
from app.main import app, configure
from tests.conftest import FakeSummarizer, card, make_settings


def test_health_is_public_and_config_lists_state(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["sso"] is False
    cfg = client.get("/api/config").json()
    assert cfg["providers"]["cerner"]["state"] == "ready"
    assert cfg["ai"]["name"] == "fake:model" and cfg["ai"]["data_destination"] == "ai.example"
    assert cfg["max_selections"] == 4


def test_search_validation_and_ranking(client):
    assert client.get("/api/search").status_code == 400
    assert client.get("/api/search", params={"family": "Doe", "sources": "epic"}).status_code == 400
    assert client.get("/api/search", params={"birth_date": "01/01/1980"}).status_code == 422
    r = client.get("/api/search", params={"family": "Doe", "given": "Jane", "birth_date": "1980-01-01"}).json()
    assert [x["source_id"] for x in r["results"][:2]] == ["c1", "a-1.E-1"] or \
           [x["source_id"] for x in r["results"][:2]] == ["a-1.E-1", "c1"]
    multi = [c for c in r["clusters"] if len(c["members"]) > 1]
    assert len(multi) == 1 and multi[0]["evidence"] and r["errors"] == []
    assert r["query"]["sources"] == ["cerner", "athena"]


def test_search_reports_per_source_failure_without_mock_data(providers):
    providers["athena"].fail = FHIRError("auth", "athena: authentication rejected by the EHR")
    configure(app, make_settings(), providers=providers, summarizer=FakeSummarizer())
    with TestClient(app) as c:
        r = c.get("/api/search", params={"family": "Doe"}).json()
    assert all(x["source"] == "cerner" for x in r["results"])
    assert r["errors"] == ["athena: authentication rejected by the EHR"]


def test_records_returns_source_tagged_data_and_errors(client):
    r = client.post("/api/records", json={"selections": [{"source": "cerner", "patient_id": "c1"}]})
    assert r.status_code == 200
    rec = r.json()["records"][0]
    assert rec["patient"]["source_id"] == "c1" and rec["conditions"][0]["source"] == "cerner"
    assert rec["truncated"] == ["observations"] and rec["fetch_errors"] == []
    assert client.post("/api/records", json={"selections": [{"source": "cerner", "patient_id": "nope"}]}).status_code == 404
    assert client.post("/api/records", json={"selections": []}).status_code == 422
    too_many = [{"source": "cerner", "patient_id": str(i)} for i in range(5)]
    assert client.post("/api/records", json={"selections": too_many}).status_code == 400
    dup = [{"source": "cerner", "patient_id": "c1"}] * 2
    assert client.post("/api/records", json={"selections": dup}).status_code == 400


def test_summary_requires_confirmation_for_multiple_records(client):
    sels = [{"source": "cerner", "patient_id": "c1"}, {"source": "athena", "patient_id": "a-1.E-1"}]
    assert client.post("/api/summary", json={"selections": sels}).status_code == 400
    r = client.post("/api/summary", json={"selections": sels, "confirmed_same_person": True})
    assert r.status_code == 200
    body = r.json()
    assert body["sources"] == ["cerner", "athena"] and body["narrative"] == "SUMMARY"
    assert body["provider"] == "fake:model" and body["data_destination"] == "ai.example"
    assert [p["patient"]["source_id"] for p in body["per_source"]] == ["c1", "a-1.E-1"]
    single = client.post("/api/summary", json={"selections": sels[:1]})
    assert single.status_code == 200


def test_summary_failure_is_an_error_not_a_fallback(providers):
    configure(app, make_settings(), providers=providers, summarizer=FakeSummarizer(error=ai.AIError("model down")))
    with TestClient(app) as c:
        r = c.post("/api/summary", json={"selections": [{"source": "cerner", "patient_id": "c1"}]})
    assert r.status_code == 502 and "model down" in r.json()["detail"]
    configure(app, make_settings(), providers=providers, summarizer=FakeSummarizer())
    app.state.summarizer = None
    app.state.problems["ai"] = ["AI_MODEL is required"]
    with TestClient(app) as c:
        r = c.post("/api/summary", json={"selections": [{"source": "cerner", "patient_id": "c1"}]})
    assert r.status_code == 503


SSO = SSOConfig(tenant_id="tenant-1", client_id="client-1", client_secret="s", base_url="https://bridge.example",
                session_secret="x" * 32)


def test_sso_enforced_when_configured(providers, monkeypatch):
    configure(app, make_settings(sso=SSO), providers=providers, summarizer=FakeSummarizer())
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as c:  # secure cookies
        assert c.get("/api/health").json()["sso"] is True
        assert c.get("/api/config").status_code == 401
        assert c.get("/").status_code == 200  # static UI loads, then sends the browser to /auth/login
        c.cookies.set(security.SESSION_COOKIE, "forged")
        assert c.get("/api/config").status_code == 401
        c.cookies.set(security.SESSION_COOKIE, security.session_cookie(SSO, {"sub": "oid-1", "name": "Dr Test"}))
        r = c.get("/api/config")
        assert r.status_code == 200 and r.json()["user"] == "Dr Test"
        c.cookies.clear()

        r = c.get("/auth/login")
        assert r.status_code == 302 and r.headers["location"].startswith(
            "https://login.microsoftonline.com/tenant-1/oauth2/v2.0/authorize?client_id=client-1")
        assert "redirect_uri=https%3A%2F%2Fbridge.example%2Fauth%2Fcallback" in r.headers["location"]
        state = c.cookies[security.STATE_COOKIE]
        assert c.get("/auth/callback", params={"code": "abc", "state": "other"}).status_code == 400
        assert c.get("/auth/callback", params={"error": "access_denied", "error_description": "no"}).status_code == 400
        monkeypatch.setattr(security, "_id_token_claims", lambda cfg, code: {"sub": "oid-1", "name": "Dr Test"})
        r = c.get("/auth/callback", params={"code": "abc", "state": state})
        assert r.status_code == 302 and r.headers["location"] == "/"
        assert c.get("/api/config").status_code == 200
        r = c.get("/auth/logout")
        assert r.status_code == 302 and "post_logout_redirect_uri" in r.headers["location"]
        assert c.get("/api/config").status_code == 401


def test_patient_id_must_be_a_plain_identifier(client):
    bad = [{"source": "cerner", "patient_id": "../Encounter?_count=1000"}]
    assert client.post("/api/records", json={"selections": bad}).status_code == 422


def test_auth_test_endpoint(client):
    assert client.get("/api/auth/test/cerner").json() == {"source": "cerner", "ok": True, "detail": "fake"}
    assert client.get("/api/auth/test/epic").status_code == 404


def test_no_providers_configured_gives_clear_errors():
    configure(app, make_settings(), providers={}, summarizer=FakeSummarizer())
    with TestClient(app) as c:
        assert c.get("/api/search", params={"family": "Doe"}).status_code == 400
        r = c.post("/api/records", json={"selections": [{"source": "cerner", "patient_id": "x"}]})
        assert r.status_code == 400 and "not configured" in r.json()["detail"]


def test_unused_fake_card():
    assert card("cerner", "1", "A", "B", None).birth_date is None
