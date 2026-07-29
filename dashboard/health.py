"""Failure-tolerant probe for the real AfyaPlus health endpoint."""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class HealthEvidence:
    """Sanitized upstream liveness evidence."""

    status: str
    endpoint: str
    detail: str


def probe_health(url: str, timeout_seconds: float) -> HealthEvidence:
    """Return HEALTHY only for the real expected contract; otherwise UNKNOWN."""

    try:
        response = httpx.get(url, timeout=timeout_seconds)
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return HealthEvidence("UNKNOWN", url, "Health probe unavailable")
    if response.status_code == 200 and payload == {"status": "ok"}:
        return HealthEvidence("HEALTHY", url, "AfyaPlus API responded")
    return HealthEvidence("UNKNOWN", url, "Unexpected health response")
