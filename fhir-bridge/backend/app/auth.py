"""OAuth 2.0 client-credentials token acquisition for the EHR token endpoints.

Methods (EHRConfig.auth_method):
  client_secret_basic  - client id/secret in an HTTP Basic header
  private_key_jwt      - SMART Backend Services: signed JWT client assertion,
                         verified by the EHR against the registered JWKS
  none                 - no token (open sandboxes; development only)

Cerner / Oracle Health verifies assertions signed with RS384 or ES384;
athenahealth accepts RS384. RS256 is the most common cause of Cerner
`invalid-signature` errors, so RS384 is the default.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx
import jwt  # PyJWT

from .config import EHRConfig
from .logging_config import get_logger

log = get_logger(__name__)

JWT_BEARER = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


class AuthError(Exception):
    """Token acquisition failed. The message is safe to show to an operator."""


def build_client_assertion(
    *, client_id: str, token_endpoint: str, private_key_pem: str, kid: str,
    alg: str = "RS384", lifetime_seconds: int = 300,
) -> str:
    """Signed JWT per SMART Backend Services: iss=sub=client_id, aud=token
    endpoint, short exp, unique jti. `kid` must match the published JWKS."""
    now = int(time.time())
    claims = {
        "iss": client_id, "sub": client_id, "aud": token_endpoint,
        "iat": now, "exp": now + lifetime_seconds, "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, private_key_pem, algorithm=alg, headers={"kid": kid})


def _sanitize_token_error(resp: httpx.Response) -> str:
    """Return `error` / `error_description` from an OAuth error body, never the raw body."""
    try:
        body = resp.json()
        err = str(body.get("error", "")).strip()
        desc = str(body.get("error_description", "")).strip()
        detail = ": ".join(x for x in (err, desc) if x)
    except (ValueError, AttributeError):
        detail = ""
    return f"token endpoint returned HTTP {resp.status_code}" + (f" ({detail[:200]})" if detail else "")


class TokenProvider:
    """Acquires and caches one bearer token for one EHR configuration."""

    def __init__(self, cfg: EHRConfig, *, refresh_margin: float = 60.0) -> None:
        self.cfg = cfg
        self.refresh_margin = refresh_margin
        self._token: str | None = None
        self._expiry: float = 0.0
        self._private_key: str | None = None

    @property
    def requires_token(self) -> bool:
        return self.cfg.auth_method != "none"

    def invalidate(self) -> None:
        """Drop the cached token (called after an upstream 401)."""
        self._token, self._expiry = None, 0.0

    def _key(self) -> str:
        if self._private_key is None:
            self._private_key = Path(self.cfg.private_key_path).read_text(encoding="utf-8")
        return self._private_key

    def _form(self) -> tuple[dict[str, str], tuple[str, str] | None]:
        data = {"grant_type": "client_credentials", "scope": self.cfg.scope}
        if self.cfg.auth_method == "client_secret_basic":
            return data, (self.cfg.client_id, self.cfg.client_secret)
        if self.cfg.auth_method == "private_key_jwt":
            data["client_assertion_type"] = JWT_BEARER
            data["client_assertion"] = build_client_assertion(
                client_id=self.cfg.client_id, token_endpoint=self.cfg.token_url,
                private_key_pem=self._key(), kid=self.cfg.kid, alg=self.cfg.alg,
            )
            return data, None
        raise AuthError(f"unsupported auth method: {self.cfg.auth_method}")

    async def token(self, client: httpx.AsyncClient) -> str | None:
        if not self.requires_token:
            return None
        if self._token and time.time() < self._expiry - self.refresh_margin:
            return self._token
        data, basic = self._form()
        try:
            resp = await client.post(
                self.cfg.token_url, data=data, auth=basic,
                headers={"Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise AuthError("token endpoint timed out") from exc
        except httpx.TransportError as exc:
            raise AuthError(f"token endpoint unreachable ({type(exc).__name__})") from exc
        if resp.status_code != 200:
            msg = _sanitize_token_error(resp)
            log.warning("%s: %s", self.cfg.name, msg)
            raise AuthError(msg)
        try:
            payload = resp.json()
            token = payload["access_token"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AuthError("token endpoint returned an unexpected body") from exc
        self._token = str(token)
        self._expiry = time.time() + float(payload.get("expires_in", 300))
        log.info("%s: token acquired (%s), expires_in=%s", self.cfg.name, self.cfg.auth_method,
                 payload.get("expires_in"))
        return self._token
