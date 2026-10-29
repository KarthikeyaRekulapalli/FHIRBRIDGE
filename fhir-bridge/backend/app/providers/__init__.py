"""Build the active EHR adapters from configuration.

An EHR is registered only when it is enabled *and* its configuration has no
problems. Nothing is registered by default and there is no mock fallback.
"""
from __future__ import annotations

from ..config import Settings
from ..fhir_client import FHIRClient
from ..logging_config import get_logger
from .base import EHRProvider
from .fhir_provider import PROVIDER_CLASSES

log = get_logger(__name__)


def build_providers(settings: Settings) -> dict[str, EHRProvider]:
    providers: dict[str, EHRProvider] = {}
    problems = settings.problems()
    for ehr in settings.ehrs:
        if not ehr.enabled:
            log.info("provider %s: disabled", ehr.name)
            continue
        if ehr.name in problems:
            log.warning("provider %s: not configured: %s", ehr.name, "; ".join(problems[ehr.name]))
            continue
        client = FHIRClient(ehr, timeout=settings.http_timeout, max_pages=settings.max_pages,
                            concurrency=settings.outbound_concurrency)
        providers[ehr.name] = PROVIDER_CLASSES[ehr.name](ehr, client)
        log.info("provider %s: registered (%s, auth=%s)", ehr.name, ehr.base_url, ehr.auth_method)
    return providers


__all__ = ["EHRProvider", "build_providers"]
