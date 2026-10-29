"""FastAPI application: routes, startup validation, request logging.

  GET  /api/health                 liveness (public, no upstream calls)
  GET  /api/config                 providers, AI provider, limits, config problems
  GET  /api/auth/test/{source}     acquire a token only (no patient data)
  GET  /auth/login|callback|logout Microsoft Entra sign-in (security.py)
  GET  /api/search                 search configured EHRs, rank, group candidates
  POST /api/records                clinical data for selected records (no AI)
  POST /api/summary                records + AI summary (confirmation required for >1 record)
Static frontend served from /.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import ai
from .aggregate import RecordsError, fetch_records
from .config import Settings, load_settings
from .logging_config import get_logger, setup_logging
from .matching import cluster_across_sources, score_against_query
from .models import RecordsRequest, SearchResponse, SummaryRequest, SummaryResponse
from .providers import EHRProvider, build_providers
from .security import require_user
from .security import router as auth_router

log = get_logger("app")
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def configure(app: FastAPI, settings: Settings, providers: dict[str, EHRProvider] | None = None,
              summarizer: ai.Summarizer | None = None) -> None:
    """Attach runtime state. Tests call this with fakes; `lifespan` calls it from config."""
    app.state.settings = settings
    app.state.problems = settings.problems()
    app.state.providers = providers if providers is not None else build_providers(settings)
    if summarizer is None:
        try:
            summarizer = ai.build_summarizer(settings.ai)
        except ai.AIConfigError as exc:
            app.state.problems["ai"] = [str(exc)]
    app.state.summarizer = summarizer
    if settings.production and app.state.problems:
        raise RuntimeError(f"invalid configuration: {app.state.problems}")
    for area, probs in app.state.problems.items():
        log.warning("configuration problem (%s): %s", area, "; ".join(probs))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    lc = settings.logging
    setup_logging(lc.level, lc.dir, lc.file, lc.max_bytes, lc.backup_count, lc.to_console)
    if not hasattr(app.state, "settings"):
        configure(app, settings)
    log.info("started env=%s providers=%s ai=%s", settings.env, list(app.state.providers),
             getattr(app.state.summarizer, "name", None))
    yield
    for p in app.state.providers.values():
        await p.aclose()


app = FastAPI(title="FHIR EHR Bridge", version="2.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)
api = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log method, path (never the query string), status and duration."""
    rid = uuid.uuid4().hex[:8]
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("[%s] %s %s -> unhandled error", rid, request.method, request.url.path)
        raise
    log.info("[%s] %s %s -> %d (%.0fms)", rid, request.method, request.url.path,
             response.status_code, (time.perf_counter() - start) * 1000)
    response.headers["X-Request-ID"] = rid
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
async def health(request: Request) -> dict:
    st = request.app.state
    return {"status": "degraded" if st.problems else "ok", "sso": st.settings.sso.enabled}


@api.get("/config")
async def config(request: Request) -> dict:
    st = request.app.state
    s: Settings = st.settings
    providers = {}
    for ehr in s.ehrs:
        state = "disabled" if not ehr.enabled else ("ready" if ehr.name in st.providers else "not_configured")
        providers[ehr.name] = {"label": ehr.label, "state": state, "problems": st.problems.get(ehr.name, [])}
    summ = st.summarizer
    return {
        "env": s.env,
        "user": getattr(request.state, "user", {}).get("name"),
        "providers": providers,
        "ai": {"provider": s.ai.provider, "name": getattr(summ, "name", None),
               "data_destination": getattr(summ, "data_destination", None),
               "problems": st.problems.get("ai", [])},
        "max_results": s.max_results,
        "max_selections": s.max_selections,
        "problems": st.problems.get("app", []),
    }


@api.get("/auth/test/{source}")
async def auth_test(source: str, request: Request) -> dict:
    providers = request.app.state.providers
    if source not in providers:
        raise HTTPException(404, f"source '{source}' is not configured")
    ok, detail = await providers[source].test_auth()
    return {"source": source, "ok": ok, "detail": detail}


@api.get("/search", response_model=SearchResponse)
async def search(
    request: Request,
    given: str | None = Query(None, min_length=1, max_length=100),
    family: str | None = Query(None, min_length=1, max_length=100),
    birth_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    gender: str | None = Query(None, pattern="^(male|female|other|unknown)$"),
    sources: str | None = Query(None, description="comma list, e.g. cerner,athena"),
    max_results: int | None = Query(None, ge=1, le=100),
) -> SearchResponse:
    st = request.app.state
    if not (given or family or birth_date):
        raise HTTPException(400, "Provide at least one of: given, family, birth_date")
    wanted = [s.strip() for s in sources.split(",") if s.strip()] if sources else list(st.providers)
    unknown = [s for s in wanted if s not in st.providers]
    if unknown or not wanted:
        raise HTTPException(400, f"source(s) not configured: {', '.join(unknown) or '(none requested)'}")
    limit = max_results or st.settings.max_results
    errors: list[str] = []
    truncated: list[str] = []

    async def run(src: str):
        try:
            cards, cut = await st.providers[src].search_patients(
                given=given, family=family, birth_date=birth_date, gender=gender, max_results=limit)
        except Exception as exc:  # noqa: BLE001 - one EHR failing must not hide the other
            log.warning("search %s failed: %s", src, exc)
            errors.append(str(exc) if hasattr(exc, "kind") else f"{src}: unexpected error ({type(exc).__name__})")
            return []
        if cut:
            truncated.append(src)
        return cards

    results = [c for cards in await asyncio.gather(*(run(s) for s in wanted)) for c in cards]
    for card in results:
        card.match_score = score_against_query(card, given=given, family=family, birth_date=birth_date, gender=gender)
    results.sort(key=lambda c: c.match_score, reverse=True)
    return SearchResponse(
        query={"given": given, "family": family, "birth_date": birth_date, "gender": gender, "sources": wanted},
        results=results, clusters=cluster_across_sources(results), errors=errors, truncated=truncated,
    )


def _check_selections(request: Request, req: RecordsRequest) -> None:
    limit = request.app.state.settings.max_selections
    if len(req.selections) > limit:
        raise HTTPException(400, f"at most {limit} records can be selected")
    if len({(s.source, s.patient_id) for s in req.selections}) != len(req.selections):
        raise HTTPException(400, "duplicate selection")


@api.post("/records")
async def records(req: RecordsRequest, request: Request) -> dict:
    _check_selections(request, req)
    try:
        data = await fetch_records(request.app.state.providers, req.selections)
    except RecordsError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return {"records": [d.model_dump() for d in data]}


@api.post("/summary", response_model=SummaryResponse)
async def summary(req: SummaryRequest, request: Request) -> SummaryResponse:
    st = request.app.state
    _check_selections(request, req)
    if len(req.selections) > 1 and not req.confirmed_same_person:
        raise HTTPException(400, "Combining records requires confirmed_same_person=true after review")
    if st.summarizer is None:
        raise HTTPException(503, "AI provider is not configured: " + "; ".join(st.problems.get("ai", [])))
    try:
        per_source = await fetch_records(st.providers, req.selections)
    except RecordsError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    try:
        narrative, omitted = await ai.summarize(st.summarizer, per_source, st.settings.ai.max_input_chars)
    except ai.AIError as exc:
        log.warning("summary failed with %s: %s", st.summarizer.name, exc)
        raise HTTPException(502, f"Summary failed ({st.summarizer.name}): {exc}") from exc
    return SummaryResponse(
        sources=[s.patient.source for s in per_source], per_source=per_source, narrative=narrative,
        provider=st.summarizer.name, data_destination=st.summarizer.data_destination,
        omitted=omitted, disclaimer=ai.DISCLAIMER,
    )


app.include_router(api)
app.include_router(auth_router)

if FRONTEND_DIR.exists():
    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
