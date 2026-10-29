"""Sign-in with Microsoft Entra ID (Azure AD), OpenID Connect authorization-code flow.

  GET /auth/login     -> redirect to Entra
  GET /auth/callback  -> verify the id_token, set the session cookie, redirect to /
  GET /auth/logout    -> clear the cookie, sign out of Entra

Who may sign in is decided in Entra (assign users/groups to the enterprise app);
the app has no roles. When SSO is not configured in development the API is open;
production refuses to start without it (see Settings.problems).
Authors: Claude and Karthi.
"""
from __future__ import annotations

import secrets
import time
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .config import SSOConfig

router = APIRouter(prefix="/auth", include_in_schema=False)
SESSION_COOKIE = "fhir_bridge_session"
STATE_COOKIE = "fhir_bridge_state"
ENTRA = "https://login.microsoftonline.com/{tenant}"


def require_user(request: Request) -> None:
    cfg: SSOConfig = request.app.state.settings.sso
    if not cfg.enabled:
        return  # development without SSO; production never starts in this state
    try:
        request.state.user = jwt.decode(request.cookies.get(SESSION_COOKIE, ""), cfg.session_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "sign in required") from None


def session_cookie(cfg: SSOConfig, claims: dict) -> str:
    """Signed, expiring session value from verified id_token claims (no PHI, no tokens)."""
    return jwt.encode({"sub": claims["sub"], "name": claims.get("name", ""), "upn": claims.get("preferred_username", ""),
                       "exp": int(time.time()) + cfg.session_hours * 3600}, cfg.session_secret, algorithm="HS256")


@lru_cache(maxsize=4)
def _jwks(tenant: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(ENTRA.format(tenant=tenant) + "/discovery/v2.0/keys")


def _id_token_claims(cfg: SSOConfig, code: str) -> dict:
    """Exchange the code and verify the id_token against the tenant's published keys."""
    r = httpx.post(ENTRA.format(tenant=cfg.tenant_id) + "/oauth2/v2.0/token", timeout=15, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": cfg.redirect_uri,
        "client_id": cfg.client_id, "client_secret": cfg.client_secret, "scope": "openid profile email"})
    if r.status_code != 200:
        err = r.json().get("error", "") if r.headers.get("content-type", "").startswith("application/json") else ""
        raise HTTPException(502, f"sign-in failed: token endpoint returned HTTP {r.status_code} {err}".rstrip())
    token = r.json().get("id_token", "")
    try:
        key = _jwks(cfg.tenant_id).get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["RS256"], audience=cfg.client_id,
                          issuer=ENTRA.format(tenant=cfg.tenant_id) + "/v2.0")
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"sign-in failed: id_token rejected ({type(exc).__name__})") from None


def _cfg(request: Request) -> SSOConfig:
    cfg: SSOConfig = request.app.state.settings.sso
    if not cfg.enabled:
        raise HTTPException(404, "SSO is not configured")
    return cfg


@router.get("/login")
def login(request: Request) -> RedirectResponse:
    cfg = _cfg(request)
    state = secrets.token_urlsafe(24)
    url = ENTRA.format(tenant=cfg.tenant_id) + "/oauth2/v2.0/authorize?" + urlencode({
        "client_id": cfg.client_id, "response_type": "code", "redirect_uri": cfg.redirect_uri,
        "response_mode": "query", "scope": "openid profile email", "state": state})
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", secure=cfg.secure)
    return resp


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = "") -> RedirectResponse:
    cfg = _cfg(request)
    if error:
        raise HTTPException(400, f"sign-in refused by Entra: {error} {error_description[:200]}")
    if not code or not state or not secrets.compare_digest(state, request.cookies.get(STATE_COOKIE, "")):
        raise HTTPException(400, "sign-in failed: state mismatch (start again at /auth/login)")
    claims = _id_token_claims(cfg, code)
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(STATE_COOKIE)
    resp.set_cookie(SESSION_COOKIE, session_cookie(cfg, claims), max_age=cfg.session_hours * 3600,
                    httponly=True, samesite="lax", secure=cfg.secure)
    return resp


@router.get("/logout")
def logout(request: Request) -> RedirectResponse:
    cfg = _cfg(request)
    resp = RedirectResponse(ENTRA.format(tenant=cfg.tenant_id) + "/oauth2/v2.0/logout?"
                            + urlencode({"post_logout_redirect_uri": cfg.base_url}), status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
