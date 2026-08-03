from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from cost.optimizer import (
    build_cost_comparison,
    build_savings_analysis,
    load_gate_status,
    select_cheapest_eligible,
)
from cost.pricing import calculate_breakdown, usd_to_kes
from cost.projection import build_projection, budget_status
from cost.run_cost_analysis import run_pipeline
from cost.tracker import (
    EVALUATION_PATH,
    load_evaluation_records,
    write_cost_ledger,
)

GATES_PATH = Path("evaluation/quality_gate_log.csv")


def test_exact_cost_arithmetic_tracks_cached_input_separately() -> None:
    result = calculate_breakdown(
        "openai/gpt-4o-mini",
        input_tokens=1_000_000,
        cached_input_tokens=500_000,
        output_tokens=1_000_000,
    )

    assert result.input_cost_usd == Decimal("0.075")
    assert result.cached_input_cost_usd == Decimal("0.0375")
    assert result.output_cost_usd == Decimal("0.60")
    assert result.total_cost_usd == Decimal("0.71250000")
    assert usd_to_kes(result.total_cost_usd) == Decimal("92.2688")


def test_pricing_and_budget_validation_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        calculate_breakdown("openai/gpt-4o-mini", 5, 1, 6)
    with pytest.raises(ValueError, match="no verified pricing"):
        calculate_breakdown("unknown", 1, 1)
    with pytest.raises(ValueError, match="cap"):
        budget_status(Decimal("1"), Decimal("0"))


def test_ledger_is_deterministic_minimized_and_tracks_missing_cache(
    tmp_path: Path,
) -> None:
    records = load_evaluation_records(EVALUATION_PATH)
    first = write_cost_ledger(records, tmp_path / "first.jsonl")
    second = write_cost_ledger(records, tmp_path / "second.jsonl")
    payloads = [json.loads(line) for line in first.read_text().splitlines()]

    assert first.read_bytes() == second.read_bytes()
    assert len(payloads) == 30
    assert all(item["cached_input_tokens"] == 0 for item in payloads)
    assert all(item["cache_status"] == "not_reported" for item in payloads)
    assert all("hypothesis" not in item and "reasoning" not in item for item in payloads)


def test_projection_has_exact_75_25_mix_and_reconciles() -> None:
    projection = build_projection(load_evaluation_records(EVALUATION_PATH))
    details = projection[projection["scope"] == "model_feature"]
    total = projection[projection["scope"] == "overall"].iloc[0]
    by_model = details.groupby("model")["projected_requests"].sum()

    assert int(total["projected_requests"]) == 9_000
    assert int(by_model["openai/gpt-4o-mini"]) == 6_750
    assert int(by_model["openai/gpt-4o"]) == 2_250
    for column in (
        "projected_input_tokens",
        "projected_cached_input_tokens",
        "projected_output_tokens",
        "projected_cost_usd",
    ):
        assert sum(Decimal(value) for value in details[column]) == Decimal(total[column])
    assert total["budget_status"] == "WARNING"
    assert Decimal(total["monthly_budget_usd"]) == Decimal("3.60")
    assert total["monthly_budget_status"] in {"OK", "WARNING", "CRITICAL"}
    assert Decimal(total["monthly_budget_utilization"]) == (
        Decimal(total["projected_cost_usd"]) / Decimal("3.60")
    ).quantize(Decimal("0.0001"))


def test_optimizer_uses_quality_gates_and_handles_no_eligible_model() -> None:
    records = load_evaluation_records(EVALUATION_PATH)
    comparison = build_cost_comparison(records, load_gate_status(GATES_PATH))
    projection = build_projection(records)

    assert select_cheapest_eligible(comparison) == "openai/gpt-4o-mini"
    assert comparison.set_index("model").loc[
        "openai/gpt-4o", "failed_gates"
    ] == "grounding_compliance_rate"
    assert {
        "pricing_source",
        "exchange_rate_source",
        "exchange_rate_document",
    }.issubset(comparison.columns)
    comparison["all_quality_gates_passed"] = False
    savings = build_savings_analysis(records, projection, comparison)
    assert savings.iloc[0]["status"] == "NO_ELIGIBLE_MODEL"
    assert Decimal(savings.iloc[0]["savings_usd"]) == 0


def test_pipeline_writes_reconciled_quality_safe_outputs(tmp_path: Path) -> None:
    artifacts = run_pipeline(EVALUATION_PATH, GATES_PATH, tmp_path)

    assert set(artifacts) == {"ledger", "projection", "comparison", "savings"}
    assert all(path.exists() and path.stat().st_size > 0 for path in artifacts.values())
    savings = pd.read_csv(artifacts["savings"])
    recommended = savings[savings["status"] == "RECOMMENDED"].iloc[0]
    assert recommended["selected_model"] == "openai/gpt-4o-mini"
    assert bool(recommended["quality_preserved"]) is True
    assert float(recommended["savings_usd"]) > 0
