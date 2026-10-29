import os

from app.config import EHRConfig, Settings, SSOConfig, load_dotenv
from app.main import app, configure
from tests.conftest import ehr_cfg, make_settings


def test_unconfigured_ehr_lists_missing_fields():
    probs = EHRConfig("cerner", "Cerner").problems(production=False)
    assert any("CERNER_BASE_URL" in p for p in probs)
    assert any("CERNER_TOKEN_URL" in p for p in probs)
    assert any("CERNER_CLIENT_ID" in p for p in probs)
    assert any("CERNER_PRIVATE_KEY_PATH" in p for p in probs)
    assert any("CERNER_KID" in p for p in probs)


def test_private_key_jwt_requires_existing_key(tmp_path):
    key = tmp_path / "k.pem"
    cfg = ehr_cfg("cerner", auth_method="private_key_jwt", private_key_path=str(key), kid="k1")
    assert any("does not exist" in p for p in cfg.problems(False))
    key.write_text("x")
    assert cfg.problems(False) == []


def test_athena_requires_practice_id():
    cfg = ehr_cfg("athena", extra={"practice_id": ""})
    assert "ATHENA_PRACTICE_ID is required" in cfg.problems(False)


def test_auth_none_only_outside_production():
    cfg = ehr_cfg("cerner", auth_method="none", token_url="", client_id="", client_secret="")
    assert cfg.problems(False) == []
    assert any("not allowed" in p for p in cfg.problems(True))


def test_production_requires_sso_and_fails_startup():
    s = make_settings(env="production")
    assert "are required when APP_ENV=production" in s.problems()["sso"][0]
    partial = SSOConfig(tenant_id="t", client_id="c", client_secret="s", base_url="http://bridge.example", session_secret="x")
    assert partial.problems(False) == ["SSO_BASE_URL must be an https URL (http only for localhost)",
                                       "SESSION_SECRET must be at least 32 characters (openssl rand -hex 32)"]
    assert SSOConfig().problems(False) == []
    try:
        configure(app, s, providers={}, summarizer=None)
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


def test_no_hardcoded_tenant_or_sandbox_defaults(monkeypatch):
    for k in list(os.environ):
        if k.startswith(("CERNER_", "ATHENA_", "AI_", "APP_")):
            monkeypatch.delenv(k)
    s = Settings.from_env()
    assert s.cerner.base_url == "" and s.athena.base_url == ""
    assert s.cerner.token_url == "" and s.athena.token_url == ""
    assert s.cerner.client_id == "" and s.athena.client_id == ""
    assert "cerner" in s.problems() and "athena" in s.problems()


def test_dotenv_does_not_override_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('APP_ENV="production"\nFOO_TEST=bar\n# comment\n')
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("FOO_TEST", raising=False)
    load_dotenv(env)
    assert os.environ["APP_ENV"] == "development"
    assert os.environ["FOO_TEST"] == "bar"


def test_dotenv_strips_inline_comments(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("AI_MAX_INPUT_CHARS=24000            # facts beyond this are dropped\nCERNER_SCOPE=system/Patient.read system/Condition.read\n")
    monkeypatch.delenv("AI_MAX_INPUT_CHARS", raising=False)
    monkeypatch.delenv("CERNER_SCOPE", raising=False)
    load_dotenv(env)
    assert os.environ["AI_MAX_INPUT_CHARS"] == "24000"
    assert os.environ["CERNER_SCOPE"] == "system/Patient.read system/Condition.read"
