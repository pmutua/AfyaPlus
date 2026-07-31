"""Authenticated FastAPI executive observability dashboard."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from dashboard.artifacts import (
    ArtifactNotAvailableError,
    list_available_artifacts,
    resolve_artifact_path,
)
from dashboard.config import DashboardSettings, load_settings
from dashboard.data_sources import DashboardData, load_dashboard_data
from dashboard.health import HealthEvidence, probe_health
from dashboard.metrics import (
    DashboardMetrics,
    create_metrics,
    publish_artifacts,
    publish_health,
)

HealthProbe = Callable[[str, float], HealthEvidence]
TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _request_token(request: Request) -> str:
    header = request.headers.get("X-Dashboard-Token", "")
    return header or request.query_params.get("access_token", "")


def _authorized(request: Request, expected: str) -> bool:
    supplied = _request_token(request)
    return bool(supplied) and secrets.compare_digest(supplied, expected)


def _install_auth(application: FastAPI, access_token: str) -> None:
    @application.middleware("http")
    async def authenticate(request: Request, call_next: Callable) -> Response:
        if request.url.path == "/metrics":
            return await call_next(request)
        if not _authorized(request, access_token):
            return JSONResponse(
                {"detail": "Dashboard authentication required."},
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Dashboard-Token"},
            )
        return await call_next(request)


def _install_routes(
    application: FastAPI,
    settings: DashboardSettings,
    data: DashboardData,
    metrics: DashboardMetrics,
    health_probe: HealthProbe,
) -> None:
    @application.get("/", name="dashboard")
    def dashboard(request: Request) -> Response:
        health = health_probe(
            settings.health_url,
            settings.health_timeout_seconds,
        )
        publish_health(metrics, health)
        return TEMPLATES.TemplateResponse(
            request=request,
            name="index.html",
            context={"health": health, "data": data},
        )

    @application.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(
            generate_latest(metrics.registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    @application.get("/artifacts", name="artifacts")
    def artifacts_index(request: Request) -> Response:
        return TEMPLATES.TemplateResponse(
            request=request,
            name="artifacts.html",
            context={
                "artifacts": list_available_artifacts(settings.artifact_root),
                "token": request.query_params.get("access_token", ""),
            },
        )

    @application.get("/artifacts/{artifact_path:path}", name="artifact_file")
    def artifact_file(artifact_path: str) -> Response:
        try:
            resolved = resolve_artifact_path(settings.artifact_root, artifact_path)
        except ArtifactNotAvailableError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        entry = next(
            e
            for e in list_available_artifacts(settings.artifact_root)
            if e.relative_path == artifact_path
        )
        return FileResponse(resolved, media_type=entry.media_type)


def create_app(
    settings: DashboardSettings | None = None,
    health_probe: HealthProbe = probe_health,
) -> FastAPI:
    """Create a single-process dashboard from validated real evidence."""

    resolved = settings or load_settings()
    data = load_dashboard_data(resolved.artifact_root)
    metrics = create_metrics()
    publish_artifacts(metrics, data)
    application = FastAPI(
        title="AfyaPlus Executive Observability",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    _install_auth(application, resolved.access_token)
    _install_routes(application, resolved, data, metrics, health_probe)
    return application
