"""Fail-fast configuration for the standalone executive dashboard."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

DEFAULT_HEALTH_URL = (
    "https://afyaplus-rag-agent-production.up.railway.app/health"
)


class DashboardConfigurationError(RuntimeError):
    """Raised when dashboard startup configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class DashboardSettings:
    """Validated dashboard runtime settings."""

    access_token: str
    artifact_root: Path
    health_url: str
    health_timeout_seconds: float


def _required_token(values: Mapping[str, str]) -> str:
    token = values.get("DASHBOARD_ACCESS_TOKEN", "")
    if len(token) < 16:
        raise DashboardConfigurationError(
            "DASHBOARD_ACCESS_TOKEN must contain at least 16 characters."
        )
    return token


def _health_url(values: Mapping[str, str]) -> str:
    url = values.get("AFYAPLUS_HEALTH_URL", DEFAULT_HEALTH_URL)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DashboardConfigurationError(
            "AFYAPLUS_HEALTH_URL must be an absolute http(s) URL."
        )
    return url


def _timeout(values: Mapping[str, str]) -> float:
    try:
        timeout = float(values.get("DASHBOARD_HEALTH_TIMEOUT_SECONDS", "3"))
    except ValueError as exc:
        raise DashboardConfigurationError(
            "DASHBOARD_HEALTH_TIMEOUT_SECONDS must be numeric."
        ) from exc
    if timeout <= 0:
        raise DashboardConfigurationError(
            "DASHBOARD_HEALTH_TIMEOUT_SECONDS must be positive."
        )
    return timeout


def load_settings(
    environ: Mapping[str, str] | None = None,
) -> DashboardSettings:
    """Resolve settings and fail before serving on invalid configuration."""

    if environ is None:
        load_dotenv()
        values: Mapping[str, str] = os.environ
    else:
        values = environ
    artifact_root = Path(values.get("DASHBOARD_ARTIFACT_ROOT", ".")).resolve()
    if not artifact_root.is_dir():
        raise DashboardConfigurationError(
            f"DASHBOARD_ARTIFACT_ROOT does not exist: {artifact_root}"
        )
    return DashboardSettings(
        access_token=_required_token(values),
        artifact_root=artifact_root,
        health_url=_health_url(values),
        health_timeout_seconds=_timeout(values),
    )
