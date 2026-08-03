from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from drift.drift_monitor import run_drift_check
from drift.run_monthly_drift_reports import analyze_months, run_pipeline
from drift.simulate_production_traffic import (
    SimulationConfig,
    load_traffic_profile,
    simulate_monthly_windows,
)

EVALUATION_PATH = Path("evaluation/full_evaluation_results.csv")


def test_simulation_is_reproducible_from_evaluation_evidence() -> None:
    config = SimulationConfig(rows=80, seed=254)

    first_reference, first_months = simulate_monthly_windows(EVALUATION_PATH, config)
    second_reference, second_months = simulate_monthly_windows(EVALUATION_PATH, config)

    pd.testing.assert_frame_equal(first_reference, second_reference)
    for month in first_months:
        pd.testing.assert_frame_equal(first_months[month], second_months[month])


def test_month_one_is_nominal_and_month_two_starts_operational_drift() -> None:
    reference, months = simulate_monthly_windows()

    trend, reports = analyze_months(reference, months)

    assert reports["Month 1"].drifted_columns == ()
    assert reports["Month 1"].needs_action is False
    assert reports["Month 2"].drifted_columns == ("latency_ms", "total_tokens")
    first = trend[trend["first_detected"]]
    assert set(first[first["month"] == "Month 2"]["column"]) == {
        "latency_ms",
        "total_tokens",
    }


def test_month_three_adds_harmful_quality_drift() -> None:
    reference, months = simulate_monthly_windows()

    _, reports = analyze_months(reference, months)
    month_three = reports["Month 3"]

    assert {"rouge_l", "overall", "grounding_compliance"}.issubset(
        month_three.drifted_columns
    )
    assert month_three.needs_action is True


def test_monitor_rejects_invalid_threshold_missing_and_small_samples() -> None:
    frame = pd.DataFrame({"rouge_l": [0.8] * 20})

    with pytest.raises(ValueError, match="threshold"):
        run_drift_check(frame, frame, columns=("rouge_l",), threshold=1.2)
    with pytest.raises(ValueError, match="Missing"):
        run_drift_check(frame, frame, columns=("latency_ms",))
    with pytest.raises(ValueError, match="at least 20"):
        run_drift_check(frame.iloc[:10], frame.iloc[:10], columns=("rouge_l",))


def test_profile_rejects_incomplete_evaluation_artifact(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.csv"
    pd.DataFrame({"status": ["success"] * 10}).to_csv(path, index=False)

    with pytest.raises(ValueError, match="missing columns"):
        load_traffic_profile(path)


def test_pipeline_writes_three_reports_trend_and_first_alert(tmp_path: Path) -> None:
    artifacts = run_pipeline(
        EVALUATION_PATH,
        tmp_path,
        SimulationConfig(rows=80, seed=20260729),
    )

    html_paths = artifacts["html_paths"]
    assert len(html_paths) == 3
    assert all(path.exists() and path.stat().st_size > 0 for path in html_paths)
    trend = pd.read_csv(artifacts["trend_path"])
    alerts = [
        json.loads(line)
        for line in artifacts["alert_path"].read_text(encoding="utf-8").splitlines()
    ]
    assert len(trend) == 15
    assert alerts[0]["month"] == "Month 2"
    assert alerts[0]["column"] == "latency_ms"
    assert all("question" not in alert and "hypothesis" not in alert for alert in alerts)
