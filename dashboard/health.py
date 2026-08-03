"""Failure-tolerant probe for the real AfyaPlus health endpoint."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from prometheus_client.parser import text_string_to_metric_families

_EXCEPTION_STATUS_CLASSES = {"4xx", "5xx"}


@dataclass(frozen=True)
class HealthEvidence:
    """Sanitized upstream liveness evidence."""

    status: str
    endpoint: str
    detail: str
    exception_count: int | None = None


def parse_exception_count(metrics_text: str) -> int:
    """Sum bounded-label 4xx/5xx request counters from Prometheus text output.

    Counts requests, not distinct exception types - the upstream metric never
    carries exception class/message (see app/observability.py), only the
    already-sanitized status_class label.
    """

    total = 0.0
    for family in text_string_to_metric_families(metrics_text):
        for sample in family.samples:
            if (
                sample.name == "afyaplus_api_http_requests_total"
                and sample.labels.get("status_class") in _EXCEPTION_STATUS_CLASSES
            ):
                total += sample.value
    return int(total)


def _metrics_url(health_url: str) -> str:
    if health_url.endswith("/health"):
        return health_url[: -len("/health")] + "/metrics"
    return health_url


def _probe_exception_count(health_url: str, timeout_seconds: float) -> int | None:
    try:
        response = httpx.get(_metrics_url(health_url), timeout=timeout_seconds)
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    try:
        return parse_exception_count(response.text)
    except ValueError:
        return None


def probe_health(url: str, timeout_seconds: float) -> HealthEvidence:
    """Return HEALTHY only for the real expected contract; otherwise UNKNOWN.

    Exception counts are probed separately and best-effort - a failure there
    degrades to `None` (rendered as "n/a") without affecting the reported
    liveness status itself.
    """

    exception_count = _probe_exception_count(url, timeout_seconds)
    try:
        response = httpx.get(url, timeout=timeout_seconds)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return HealthEvidence(
            "UNKNOWN", url, "Health probe unavailable", exception_count
        )
    if response.status_code == 200 and payload == {"status": "ok"}:
        return HealthEvidence(
            "HEALTHY", url, "AfyaPlus API responded", exception_count
        )
    return HealthEvidence(
        "UNKNOWN", url, "Unexpected health response", exception_count
    )
