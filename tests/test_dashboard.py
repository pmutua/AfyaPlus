from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from dashboard.config import (
    DashboardConfigurationError,
    DashboardSettings,
    load_settings,
)
from dashboard.data_sources import DashboardDataError, load_dashboard_data
from dashboard.health import HealthEvidence, probe_health
from dashboard.main import create_app

ROOT = Path(__file__).parents[1]
TOKEN = "dashboard-test-token-254"


def _settings(root: Path = ROOT) -> DashboardSettings:
    return DashboardSettings(
        access_token=TOKEN,
        artifact_root=root,
        health_url="https://afyaplus.example/health",
        health_timeout_seconds=0.2,
    )


def _healthy(_url: str, _timeout: float) -> HealthEvidence:
    return HealthEvidence("HEALTHY", "https://afyaplus.example/health", "Ready")


def _unknown(_url: str, _timeout: float) -> HealthEvidence:
    return HealthEvidence("UNKNOWN", "https://afyaplus.example/health", "Unavailable")


def test_loaders_build_all_sections_from_real_generated_artifacts() -> None:
    data = load_dashboard_data(ROOT)

    assert len(data.quality_rows) == 6
    assert len(data.drift_rows) == 5
    assert data.budget.projected_requests == 9_000
    assert data.budget.status == "WARNING"


def test_loader_rejects_incomplete_quality_artifact(tmp_path: Path) -> None:
    evaluation = tmp_path / "evaluation"
    evaluation.mkdir()
    pd.DataFrame({"model": ["openai/gpt-4o-mini"]}).to_csv(
        evaluation / "full_evaluation_results.csv",
        index=False,
    )

    with pytest.raises(DashboardDataError, match="missing columns"):
        load_dashboard_data(tmp_path)


def test_settings_fail_fast_without_a_strong_access_token() -> None:
    with pytest.raises(DashboardConfigurationError, match="at least 16"):
        load_settings({"DASHBOARD_ARTIFACT_ROOT": str(ROOT)})


def test_dashboard_rejects_missing_and_wrong_tokens() -> None:
    client = TestClient(create_app(_settings(), _healthy))

    assert client.get("/").status_code == 401
    assert client.get("/", headers={"X-Dashboard-Token": "wrong"}).status_code == 401


def test_dashboard_renders_all_sections_with_correct_token() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    response = client.get("/", headers={"X-Dashboard-Token": TOKEN})

    assert response.status_code == 200
    for section in (
        "System Health",
        "Feature Quality Matrix",
        "Drift Vector Status",
        "Budget Capital Utilisation",
    ):
        assert section in response.text
    assert "HEALTHY" in response.text
    assert "openai/gpt-4o-mini" in response.text


def test_failed_health_probe_degrades_to_unknown() -> None:
    client = TestClient(create_app(_settings(), _unknown))
    response = client.get("/", params={"access_token": TOKEN})

    assert response.status_code == 200
    assert "UNKNOWN" in response.text
    assert probe_health("http://127.0.0.1:1/health", 0.1).status == "UNKNOWN"


def test_metrics_are_public_and_use_dedicated_dashboard_names() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "afyaplus_feature_quality_score" in response.text
    assert "afyaplus_drift_detected" in response.text
    assert "afyaplus_budget_utilization_ratio" in response.text


def test_compose_contains_api_dashboard_prometheus_and_grafana() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "dashboard" / "Dockerfile").read_text(encoding="utf-8")

    assert all(
        f"  {service}:" in compose
        for service in ("api", "dashboard", "prometheus", "grafana")
    )
    assert "dockerfile: app/Dockerfile" in compose
    assert "MODEL_PROVIDER: ollama_cloud" in compose
    assert "OLLAMA_CLOUD_API_KEY: ${OLLAMA_CLOUD_API_KEY:?" in compose
    assert "QDRANT_API_KEY: ${QDRANT_API_KEY:?" in compose
    assert "env_file:" not in compose
    assert "host.docker.internal" not in compose
    assert "AFYAPLUS_HEALTH_URL: http://api:8000/health" in compose
    assert "grafana/grafana:13.1.0" in compose
    assert "GRAFANA_ADMIN_PASSWORD:?" in compose
    assert "--workers\", \"1" in dockerfile


def test_grafana_provisions_prometheus_and_executive_panels() -> None:
    grafana = ROOT / "dashboard" / "grafana"
    datasource = (
        grafana / "provisioning" / "datasources" / "prometheus.yml"
    ).read_text(encoding="utf-8")
    provider = (
        grafana / "provisioning" / "dashboards" / "dashboards.yml"
    ).read_text(encoding="utf-8")
    dashboard = json.loads(
        (grafana / "dashboards" / "afyaplus-observability.json").read_text(
            encoding="utf-8"
        )
    )

    assert "uid: afyaplus-prometheus" in datasource
    assert "url: http://prometheus:9090" in datasource
    assert "path: /var/lib/grafana/dashboards" in provider
    assert dashboard["uid"] == "afyaplus-executive"
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert {
        "System Health",
        "Feature Quality Matrix",
        "Drift Vector Status",
        "Budget Capital Utilisation",
    }.issubset(titles)
    expressions = {
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    }
    assert "afyaplus_upstream_health" in expressions
    assert "afyaplus_budget_utilization_ratio" in expressions
    assert any("afyaplus_api_http_requests_total" in item for item in expressions)
    assert any(
        "afyaplus_api_http_request_duration_seconds_bucket" in item
        for item in expressions
    )
