"""Tests for Railway deployment and CI configuration."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
PRODUCTION_VARIABLES = {
    "MODEL_PROVIDER",
    "OLLAMA_CLOUD_BASE_URL",
    "OLLAMA_CLOUD_MODEL",
    "OLLAMA_CLOUD_API_KEY",
    "CLOUD_TIMEOUT_SECONDS",
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "QDRANT_COLLECTION_NAME",
    "QDRANT_EMBEDDING_MODEL",
    "QDRANT_EMBEDDING_DIMENSIONS",
    "QDRANT_TIMEOUT_SECONDS",
    "AGENT_HISTORY_TOKEN_BUDGET",
    "RATE_LIMIT_ENABLED",
    "RATE_LIMIT_REQUESTS_PER_MINUTE",
    "RATE_LIMIT_REQUESTS_PER_DAY",
    "RATE_LIMIT_TRUST_RAILWAY_PROXY",
    "CHAINLIT_COT_MODE",
}


def _production_template() -> dict[str, str]:
    lines = (ROOT / "railway.env.example").read_text(encoding="utf-8").splitlines()
    entries = (line.split("=", 1) for line in lines if line and not line.startswith("#"))
    return dict(entries)


def test_railway_runs_single_worker_on_injected_port() -> None:
    config = json.loads((ROOT / "app" / "railway.json").read_text(encoding="utf-8"))
    command = config["deploy"]["startCommand"]

    assert config["build"]["builder"] == "RAILPACK"
    assert "app.main:app" in command
    assert "--host 0.0.0.0" in command
    assert "--port $PORT" in command
    assert "--workers 1" in command


def test_railway_gates_activation_on_health_endpoint() -> None:
    config = json.loads((ROOT / "app" / "railway.json").read_text(encoding="utf-8"))
    deployment = config["deploy"]

    assert deployment["healthcheckPath"] == "/health"
    assert deployment["healthcheckTimeout"] == 300
    assert deployment["restartPolicyType"] == "ON_FAILURE"


def test_runtime_and_ci_use_python_312() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"
    assert 'python-version: "3.12"' in workflow
    assert "python -m pip check" in workflow
    assert "python -m pytest -q" in workflow
    assert "python -m compileall -q" in workflow
    assert "git diff --check" in workflow


def test_production_template_has_only_required_cloud_variables() -> None:
    variables = _production_template()

    assert set(variables) == PRODUCTION_VARIABLES
    assert variables["MODEL_PROVIDER"] == "ollama_cloud"
    assert variables["RATE_LIMIT_TRUST_RAILWAY_PROXY"] == "true"
    assert variables["CHAINLIT_COT_MODE"] == "hidden"
    assert "OLLAMA_LOCAL" not in "\n".join(variables)
    assert variables["OLLAMA_CLOUD_API_KEY"].startswith("<")
    assert variables["QDRANT_API_KEY"].startswith("<")
    assert not any(value.startswith("eyJ") for value in variables.values())
