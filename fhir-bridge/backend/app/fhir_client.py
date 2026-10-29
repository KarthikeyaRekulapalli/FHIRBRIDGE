"""Vendor-neutral async FHIR R4 read/search client.

* One shared httpx connection pool per EHR, bounded concurrency
* bearer token from TokenProvider; one transparent retry after a 401
* bounded retries with backoff for 429 / 502 / 503 / 504 and transport errors
* Bundle pagination via `next` links, capped, with a `truncated` flag
* every failure is a FHIRError with a `kind` and an operator-safe message
  (never the upstream body, never query parameters, which may hold names)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx

from .auth import AuthError, TokenProvider
from .config import EHRConfig
from .logging_config import get_logger

log = get_logger(__name__)

FHIR_JSON = "application/fhir+json"
RETRYABLE = {429, 502, 503, 504}


class FHIRError(Exception):
    """kind: auth | forbidden | not_found | rate_limited | timeout | upstream | invalid_response"""

    def __init__(self, kind: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.kind, self.status = kind, status


@dataclass
class SearchResult:
    resources: list[dict] = field(default_factory=list)
    truncated: bool = False  # hit the page cap; more results exist upstream


class FHIRClient:
    def __init__(self, cfg: EHRConfig, *, timeout: float = 30.0, max_attempts: int = 3,
                 max_pages: int = 5, concurrency: int = 6,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.cfg = cfg
        self.base_url = cfg.base_url.rstrip("/")
        self.auth = TokenProvider(cfg)
        self.max_attempts = max_attempts
        self.max_pages = max_pages
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=False, transport=transport)
        self._sem = asyncio.Semaphore(concurrency)
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _headers(self) -> dict[str, str]:
        headers = {"Accept": FHIR_JSON}
        if self.auth.requires_token:
            async with self._token_lock:
                token = await self.auth.token(self._client)
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _get(self, url: str, params: dict | None, label: str) -> dict:
        """GET with bounded retries. `label` is what gets logged (never the query)."""
        last = "unknown error"
        retried_auth = False
        for attempt in range(1, self.max_attempts + 1):
            try:
                headers = await self._headers()
            except AuthError as exc:
                raise FHIRError("auth", f"{self.cfg.name}: {exc}") from exc
            try:
                async with self._sem:
                    resp = await self._client.get(url, params=params, headers=headers)
            except httpx.TimeoutException:
                last = "timed out"
                log.warning("%s %s: timeout (attempt %d/%d)", self.cfg.name, label, attempt, self.max_attempts)
                await asyncio.sleep(min(2 ** attempt, 8))
                continue
            except httpx.TransportError as exc:
                last = f"network error ({type(exc).__name__})"
                log.warning("%s %s: %s (attempt %d/%d)", self.cfg.name, label, last, attempt, self.max_attempts)
                await asyncio.sleep(min(2 ** attempt, 8))
                continue

            if resp.status_code == 200:
                try:
                    body = resp.json()
                except ValueError as exc:
                    raise FHIRError("invalid_response", f"{self.cfg.name}: non-JSON response for {label}") from exc
                if not isinstance(body, dict):
                    raise FHIRError("invalid_response", f"{self.cfg.name}: unexpected response shape for {label}")
                return body
            if resp.status_code == 401 and self.auth.requires_token and not retried_auth:
                retried_auth = True  # token expired/revoked upstream: refresh once
                self.auth.invalidate()
                continue
            if resp.status_code in RETRYABLE and attempt < self.max_attempts:
                ra = resp.headers.get("Retry-After", "")
                delay = float(ra) if ra.isdigit() else min(2 ** attempt, 8)
                log.warning("%s %s: HTTP %d, retry in %.0fs", self.cfg.name, label, resp.status_code, delay)
                await asyncio.sleep(min(delay, 30))
                continue
            raise self._http_error(resp.status_code, label)
        raise FHIRError("timeout" if last == "timed out" else "upstream",
                        f"{self.cfg.name}: {label} failed after {self.max_attempts} attempts ({last})")

    def _http_error(self, status: int, label: str) -> FHIRError:
        kind = {401: "auth", 403: "forbidden", 404: "not_found", 429: "rate_limited"}.get(
            status, "upstream" if status >= 500 else "invalid_response")
        msg = {
            "auth": "authentication rejected by the EHR (check credentials, kid/JWKS, token URL)",
            "forbidden": "the EHR denied access (check approved scopes and tenant allow-list)",
            "not_found": "resource not found",
            "rate_limited": "rate limited by the EHR",
            "upstream": f"EHR returned HTTP {status}",
            "invalid_response": f"EHR rejected the request (HTTP {status})",
        }[kind]
        log.error("%s %s: HTTP %d (%s)", self.cfg.name, label, status, kind)
        return FHIRError(kind, f"{self.cfg.name}: {label}: {msg}", status)

    async def search(self, resource_type: str, params: dict[str, Any]) -> SearchResult:
        """Follow `next` links up to max_pages; only entries of resource_type are kept."""
        result = SearchResult()
        url: str | None = f"{self.base_url}/{resource_type}"
        next_params: dict | None = params
        for _ in range(self.max_pages):
            bundle = await self._get(url, next_params, f"search {resource_type}")
            for entry in bundle.get("entry") or []:
                res = entry.get("resource") if isinstance(entry, dict) else None
                if isinstance(res, dict) and res.get("resourceType") == resource_type:
                    result.resources.append(res)
            url, next_params = None, None
            for link in bundle.get("link") or []:
                if isinstance(link, dict) and link.get("relation") == "next" and link.get("url"):
                    url = link["url"]
            if not url:
                return result
        result.truncated = True
        return result

    async def read(self, resource_type: str, resource_id: str) -> dict | None:
        """Read one resource; None when the EHR says 404."""
        try:
            return await self._get(f"{self.base_url}/{resource_type}/{resource_id}", None, f"read {resource_type}")
        except FHIRError as exc:
            if exc.kind == "not_found":
                return None
            raise

    async def test_auth(self) -> tuple[bool, str]:
        """Acquire a token only (no data). Never returns the token itself."""
        if not self.auth.requires_token:
            return True, "no token required (auth_method=none)"
        try:
            async with self._token_lock:
                ok = bool(await self.auth.token(self._client))
            return ok, "token acquired" if ok else "no token returned"
        except AuthError as exc:
            return False, str(exc)
