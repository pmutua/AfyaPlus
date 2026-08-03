from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from dashboard.artifacts import (
    ArtifactNotAvailableError,
    list_available_artifacts,
    resolve_artifact_path,
)
from dashboard.config import (
    DashboardConfigurationError,
    DashboardSettings,
    load_settings,
)
from dashboard.data_sources import DashboardDataError, load_dashboard_data
from dashboard.health import HealthEvidence, parse_exception_count, probe_health
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
    assert response.text.count("<progress") == 2
    assert "Daily cap" in response.text
    assert "Monthly cap" in response.text


def test_failed_health_probe_degrades_to_unknown() -> None:
    client = TestClient(create_app(_settings(), _unknown))
    response = client.get("/", params={"access_token": TOKEN})

    assert response.status_code == 200
    assert "UNKNOWN" in response.text
    result = probe_health("http://127.0.0.1:1/health", 0.1)
    assert result.status == "UNKNOWN"
    assert result.exception_count is None


def test_parse_exception_count_sums_only_4xx_and_5xx() -> None:
    metrics_text = (
        "# TYPE afyaplus_api_http_requests_total counter\n"
        'afyaplus_api_http_requests_total{method="GET",route="/health",'
        'status_class="2xx"} 5.0\n'
        'afyaplus_api_http_requests_total{method="POST",route="/chat",'
        'status_class="4xx"} 2.0\n'
        'afyaplus_api_http_requests_total{method="POST",route="/chat",'
        'status_class="5xx"} 1.0\n'
    )

    assert parse_exception_count(metrics_text) == 3


def test_parse_exception_count_is_zero_with_no_failures() -> None:
    metrics_text = (
        "# TYPE afyaplus_api_http_requests_total counter\n"
        'afyaplus_api_http_requests_total{method="GET",route="/health",'
        'status_class="2xx"} 5.0\n'
    )

    assert parse_exception_count(metrics_text) == 0


def test_dashboard_shows_exception_count_from_health_evidence() -> None:
    def _healthy_with_exceptions(_url: str, _timeout: float) -> HealthEvidence:
        return HealthEvidence(
            "HEALTHY", "https://afyaplus.example/health", "Ready", 3
        )

    client = TestClient(create_app(_settings(), _healthy_with_exceptions))
    response = client.get("/", headers={"X-Dashboard-Token": TOKEN})

    assert response.status_code == 200
    assert "4xx/5xx exceptions" in response.text
    assert "failures observed" in response.text


def test_query_param_auth_bootstraps_an_httponly_session_cookie() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    response = client.get("/", params={"access_token": TOKEN})

    set_cookie = response.headers.get("set-cookie", "")
    assert "dashboard_token=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()


def test_session_cookie_alone_authenticates_without_token_in_url() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    client.get("/", params={"access_token": TOKEN})  # bootstraps the cookie

    response = client.get("/artifacts")  # no header, no query param this time

    assert response.status_code == 200


def test_header_auth_does_not_leak_token_into_a_cookie() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    response = client.get("/", headers={"X-Dashboard-Token": TOKEN})

    assert "set-cookie" not in response.headers


def test_authenticated_responses_never_leak_a_referer() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    response = client.get("/", headers={"X-Dashboard-Token": TOKEN})

    assert response.headers["referrer-policy"] == "no-referrer"


def test_html_artifacts_are_sandboxed_against_same_origin_script_access() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    response = client.get(
        "/artifacts/drift/drift_month_1.html",
        headers={"X-Dashboard-Token": TOKEN},
    )

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == "sandbox allow-scripts"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_non_html_artifacts_get_nosniff_but_no_sandbox_csp() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    response = client.get(
        "/artifacts/cost/cost_projection_30d.csv",
        headers={"X-Dashboard-Token": TOKEN},
    )

    assert response.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in response.headers


def test_evidence_links_never_carry_the_token_in_the_url() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    response = client.get("/artifacts", params={"access_token": TOKEN})

    assert f"access_token={TOKEN}" not in response.text
    assert 'href="/artifacts/cost/cost_projection_30d.csv"' in response.text


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


def test_list_available_artifacts_finds_only_real_allowlisted_files() -> None:
    entries = list_available_artifacts(ROOT)

    paths = {entry.relative_path for entry in entries}
    assert "evaluation/model_comparison_summary.csv" in paths
    assert "drift/drift_month_1.html" in paths
    assert "executive_summary.pdf" in paths
    assert all(entry.size_bytes > 0 for entry in entries)


def test_resolve_artifact_path_rejects_non_allowlisted_files(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("not evidence", encoding="utf-8")

    with pytest.raises(ArtifactNotAvailableError, match="Not an evidence artifact"):
        resolve_artifact_path(tmp_path, "requirements.txt")


def test_resolve_artifact_path_rejects_path_traversal(tmp_path: Path) -> None:
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("do not serve", encoding="utf-8")

    with pytest.raises(ArtifactNotAvailableError, match="Not an evidence artifact"):
        resolve_artifact_path(tmp_path, "../secret.txt")


def test_resolve_artifact_path_rejects_allowlisted_but_missing_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(ArtifactNotAvailableError, match="not generated yet"):
        resolve_artifact_path(tmp_path, "evaluation/model_comparison_summary.csv")


def test_resolve_artifact_path_returns_real_path_for_valid_request() -> None:
    resolved = resolve_artifact_path(ROOT, "cost/cost_projection_30d.csv")

    assert resolved == (ROOT / "cost" / "cost_projection_30d.csv").resolve()


def test_artifacts_index_requires_auth() -> None:
    client = TestClient(create_app(_settings(), _healthy))

    assert client.get("/artifacts").status_code == 401


def test_artifacts_index_lists_real_files_with_correct_token() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    response = client.get("/artifacts", headers={"X-Dashboard-Token": TOKEN})

    assert response.status_code == 200
    assert "evaluation/model_comparison_summary.csv" in response.text
    assert "executive_summary.pdf" in response.text


def test_artifact_file_requires_auth() -> None:
    client = TestClient(create_app(_settings(), _healthy))

    response = client.get("/artifacts/cost/cost_projection_30d.csv")

    assert response.status_code == 401


def test_artifact_file_serves_allowlisted_content_with_correct_token() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    response = client.get(
        "/artifacts/cost/cost_projection_30d.csv",
        headers={"X-Dashboard-Token": TOKEN},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "projected_cost_usd" in response.text


def test_artifact_file_rejects_non_allowlisted_path_even_with_valid_token() -> None:
    client = TestClient(create_app(_settings(), _healthy))
    response = client.get(
        "/artifacts/dashboard/config.py",
        headers={"X-Dashboard-Token": TOKEN},
    )

    assert response.status_code == 404


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
