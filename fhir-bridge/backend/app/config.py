"""Runtime configuration, read from environment variables (optionally a .env file).

Nothing here selects a tenant, patient, or user by default. An EHR is registered
only when its connection and credentials are fully configured; otherwise the app
starts with that EHR marked `not_configured` and lists what is missing. In
production (APP_ENV=production) incomplete configuration is a startup error.

Authors: Claude and Karthi.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

AUTH_METHODS = ("client_secret_basic", "private_key_jwt", "none")
DEFAULT_SCOPE = (
    "system/Patient.read system/Condition.read system/MedicationRequest.read "
    "system/AllergyIntolerance.read system/Observation.read system/Encounter.read"
)


def load_dotenv(path: str | os.PathLike | None = None) -> None:
    """Load KEY=VALUE lines from a .env file into os.environ without overriding
    variables that are already set (so systemd / shell exports win)."""
    candidates = [Path(path)] if path else [Path(".env"), Path(__file__).resolve().parents[2] / ".env"]
    for p in candidates:
        if not p.is_file():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.split(" #", 1)[0].strip()  # drop an inline comment
            os.environ.setdefault(key.strip(), value.strip('"').strip("'"))
        return


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, "").strip() or default


@dataclass
class EHRConfig:
    """Connection + credentials for one EHR. `extra` holds vendor-specific values."""

    name: str
    label: str
    enabled: bool = True
    base_url: str = ""
    auth_method: str = "private_key_jwt"
    token_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    scope: str = DEFAULT_SCOPE
    private_key_path: str = ""
    kid: str = ""
    alg: str = "RS384"
    extra: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, name: str, label: str, extra_keys: tuple[str, ...] = ()) -> "EHRConfig":
        p = name.upper()
        return cls(
            name=name, label=label,
            enabled=_bool(f"{p}_ENABLED", True),
            base_url=_str(f"{p}_BASE_URL").rstrip("/"),
            auth_method=_str(f"{p}_AUTH_METHOD", "private_key_jwt"),
            token_url=_str(f"{p}_TOKEN_URL"),
            client_id=_str(f"{p}_CLIENT_ID"),
            client_secret=_str(f"{p}_CLIENT_SECRET"),
            scope=_str(f"{p}_SCOPE", DEFAULT_SCOPE),
            private_key_path=_str(f"{p}_PRIVATE_KEY_PATH"),
            kid=_str(f"{p}_KID"),
            alg=_str(f"{p}_ALG", "RS384"),
            extra={k: _str(f"{p}_{k.upper()}") for k in extra_keys},
        )

    def problems(self, production: bool) -> list[str]:
        """Human-readable list of what is missing or wrong. Empty = usable."""
        p = self.name.upper()
        out: list[str] = []
        if not self.base_url.startswith("https://"):
            out.append(f"{p}_BASE_URL must be an https URL")
        if self.auth_method not in AUTH_METHODS:
            out.append(f"{p}_AUTH_METHOD must be one of {', '.join(AUTH_METHODS)}")
            return out
        if self.auth_method == "none":
            if production:
                out.append(f"{p}_AUTH_METHOD=none is not allowed when APP_ENV=production")
        else:
            if not self.token_url.startswith("https://"):
                out.append(f"{p}_TOKEN_URL must be an https URL")
            if not self.client_id:
                out.append(f"{p}_CLIENT_ID is required")
            if not self.scope:
                out.append(f"{p}_SCOPE is required")
        if self.auth_method == "client_secret_basic" and not self.client_secret:
            out.append(f"{p}_CLIENT_SECRET is required for client_secret_basic")
        if self.auth_method == "private_key_jwt":
            if not self.private_key_path:
                out.append(f"{p}_PRIVATE_KEY_PATH is required for private_key_jwt")
            elif not Path(self.private_key_path).is_file():
                out.append(f"{p}_PRIVATE_KEY_PATH does not exist: {self.private_key_path}")
            if not self.kid:
                out.append(f"{p}_KID is required for private_key_jwt")
            if self.alg not in ("RS384", "ES384", "RS256"):
                out.append(f"{p}_ALG must be RS384, ES384 or RS256")
        for key, value in self.extra.items():
            if not value:
                out.append(f"{p}_{key.upper()} is required")
        return out


@dataclass
class AIConfig:
    """Summarization provider. See AI_PROVIDERS.md for each provider's settings."""

    provider: str = "extractive"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    timeout: float = 90.0
    max_output_tokens: int = 700
    max_input_chars: int = 24000
    temperature: float = 0.1
    snowflake_account: str = ""      # Snowflake only, e.g. ab12345.us-east-1
    anthropic_version: str = "2023-06-01"

    @classmethod
    def from_env(cls) -> "AIConfig":
        return cls(
            provider=_str("AI_PROVIDER", "extractive").lower(),
            model=_str("AI_MODEL"),
            base_url=_str("AI_BASE_URL").rstrip("/"),
            api_key=_str("AI_API_KEY"),
            timeout=float(_str("AI_TIMEOUT", "90")),
            max_output_tokens=int(_str("AI_MAX_OUTPUT_TOKENS", "700")),
            max_input_chars=int(_str("AI_MAX_INPUT_CHARS", "24000")),
            temperature=float(_str("AI_TEMPERATURE", "0.1")),
            snowflake_account=_str("SNOWFLAKE_ACCOUNT"),
            anthropic_version=_str("ANTHROPIC_VERSION", "2023-06-01"),
        )


@dataclass
class LoggingConfig:
    level: str = "INFO"
    dir: str = "logs"
    file: str = "app.log"
    max_bytes: int = 2_000_000
    backup_count: int = 5
    to_console: bool = True

    @classmethod
    def from_env(cls) -> "LoggingConfig":
        return cls(
            level=_str("LOG_LEVEL", "INFO"), dir=_str("LOG_DIR", "logs"), file=_str("LOG_FILE", "app.log"),
            max_bytes=int(_str("LOG_MAX_BYTES", "2000000")), backup_count=int(_str("LOG_BACKUP_COUNT", "5")),
            to_console=_bool("LOG_TO_CONSOLE", True),
        )


@dataclass
class SSOConfig:
    """Microsoft Entra ID sign-in (see SSO_SETUP.md). All-empty = no login, development only."""

    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    base_url: str = ""          # public URL of this app, e.g. https://bridge.example.org
    session_secret: str = ""
    session_hours: int = 8

    @classmethod
    def from_env(cls) -> "SSOConfig":
        return cls(
            tenant_id=_str("SSO_TENANT_ID"), client_id=_str("SSO_CLIENT_ID"), client_secret=_str("SSO_CLIENT_SECRET"),
            base_url=_str("SSO_BASE_URL").rstrip("/"), session_secret=_str("SESSION_SECRET"),
            session_hours=int(_str("SESSION_HOURS", "8")),
        )

    @property
    def enabled(self) -> bool:
        return any((self.tenant_id, self.client_id, self.client_secret, self.base_url, self.session_secret))

    @property
    def redirect_uri(self) -> str:
        return self.base_url + "/auth/callback"

    @property
    def secure(self) -> bool:
        return self.base_url.startswith("https://")

    def problems(self, production: bool) -> list[str]:
        required = {"SSO_TENANT_ID": self.tenant_id, "SSO_CLIENT_ID": self.client_id,
                    "SSO_CLIENT_SECRET": self.client_secret, "SSO_BASE_URL": self.base_url,
                    "SESSION_SECRET": self.session_secret}
        if not self.enabled:
            return [", ".join(required) + " are required when APP_ENV=production"] if production else []
        out = [f"{k} is required" for k, v in required.items() if not v]
        if self.base_url and not self.base_url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            out.append("SSO_BASE_URL must be an https URL (http only for localhost)")
        if self.session_secret and len(self.session_secret) < 32:
            out.append("SESSION_SECRET must be at least 32 characters (openssl rand -hex 32)")
        return out


@dataclass
class Settings:
    env: str = "development"
    sso: SSOConfig = field(default_factory=SSOConfig)
    cerner: EHRConfig = field(default_factory=lambda: EHRConfig("cerner", "Cerner / Oracle Health"))
    athena: EHRConfig = field(default_factory=lambda: EHRConfig("athena", "athenahealth"))
    ai: AIConfig = field(default_factory=AIConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    http_timeout: float = 30.0
    max_results: int = 25
    max_pages: int = 5
    max_selections: int = 4
    outbound_concurrency: int = 6

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            env=_str("APP_ENV", "development").lower(),
            sso=SSOConfig.from_env(),
            cerner=EHRConfig.from_env("cerner", "Cerner / Oracle Health"),
            athena=EHRConfig.from_env("athena", "athenahealth", extra_keys=("practice_id",)),
            ai=AIConfig.from_env(),
            logging=LoggingConfig.from_env(),
            http_timeout=float(_str("HTTP_TIMEOUT", "30")),
            max_results=int(_str("MAX_RESULTS", "25")),
            max_pages=int(_str("FHIR_MAX_PAGES", "5")),
            max_selections=int(_str("MAX_SELECTIONS", "4")),
            outbound_concurrency=int(_str("OUTBOUND_CONCURRENCY", "6")),
        )

    @property
    def production(self) -> bool:
        return self.env == "production"

    @property
    def ehrs(self) -> list[EHRConfig]:
        return [self.cerner, self.athena]

    def problems(self) -> dict[str, list[str]]:
        """Configuration problems keyed by area. Empty dict = fully valid."""
        out: dict[str, list[str]] = {}
        app: list[str] = []
        if not 1 <= self.max_results <= 100:
            app.append("MAX_RESULTS must be between 1 and 100")
        if not any(e.enabled for e in self.ehrs):
            app.append("no EHR is enabled (CERNER_ENABLED / ATHENA_ENABLED)")
        if app:
            out["app"] = app
        if self.sso.problems(self.production):
            out["sso"] = self.sso.problems(self.production)
        for ehr in self.ehrs:
            if ehr.enabled:
                probs = ehr.problems(self.production)
                if probs:
                    out[ehr.name] = probs
        return out


def load_settings(dotenv: str | os.PathLike | None = None) -> Settings:
    load_dotenv(dotenv)
    return Settings.from_env()
