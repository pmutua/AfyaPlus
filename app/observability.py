"""Privacy-safe Prometheus instrumentation for the AfyaPlus API."""

from __future__ import annotations

import time
from dataclasses import dataclass

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import RequestResponseEndpoint


@dataclass(frozen=True)
class ApiMetrics:
    """Bounded-cardinality API metrics with no user-controlled labels."""

    registry: CollectorRegistry
    requests: Counter
    duration: Histogram
    in_progress: Gauge


def create_api_metrics() -> ApiMetrics:
    """Create an isolated registry for one single-worker API process."""

    registry = CollectorRegistry()
    labels = ("method", "route", "status_class")
    return ApiMetrics(
        registry=registry,
        requests=Counter(
            "afyaplus_api_http_requests",
            "Completed AfyaPlus API requests.",
            labels,
            registry=registry,
        ),
        duration=Histogram(
            "afyaplus_api_http_request_duration_seconds",
            "AfyaPlus API request duration in seconds.",
            ("method", "route"),
            registry=registry,
        ),
        in_progress=Gauge(
            "afyaplus_api_http_requests_in_progress",
            "AfyaPlus API requests currently in progress.",
            ("method", "route"),
            registry=registry,
        ),
    )


def route_label(path: str) -> str:
    """Map paths to a fixed allowlist so labels cannot contain PII."""

    if path in {"/chat", "/health", "/metrics"}:
        return path
    if path == "/ui" or path.startswith("/ui/"):
        return "/ui"
    if path in {"/docs", "/openapi.json", "/redoc"}:
        return "/docs"
    return "other"


def _status_class(status_code: int) -> str:
    return f"{status_code // 100}xx" if 100 <= status_code < 600 else "other"


def _record(
    metrics: ApiMetrics,
    method: str,
    route: str,
    status_code: int,
    started_at: float,
) -> None:
    metrics.requests.labels(method, route, _status_class(status_code)).inc()
    metrics.duration.labels(method, route).observe(time.perf_counter() - started_at)


def install_api_observability(
    application: FastAPI,
    metrics: ApiMetrics | None = None,
) -> ApiMetrics:
    """Expose `/metrics` and observe API traffic without request content."""

    resolved = metrics or create_api_metrics()

    @application.middleware("http")
    async def observe(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        route = route_label(request.url.path)
        if route == "/metrics":
            return await call_next(request)
        method = request.method
        started_at = time.perf_counter()
        resolved.in_progress.labels(method, route).inc()
        try:
            response = await call_next(request)
        except Exception:
            _record(resolved, method, route, 500, started_at)
            raise
        finally:
            resolved.in_progress.labels(method, route).dec()
        _record(resolved, method, route, response.status_code, started_at)
        return response

    @application.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(
            generate_latest(resolved.registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    return resolved
