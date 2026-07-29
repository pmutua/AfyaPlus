"""Clinical-gate-first cost comparison and structural savings analysis."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

from cost.pricing import (
    EXCHANGE_RATE,
    EXCHANGE_RATE_DATE,
    EXCHANGE_RATE_SOURCE,
    MODEL_PRICING,
    PRICING_VERIFIED_ON,
    usd_to_kes,
)
from cost.projection import DAILY_FEATURE_VOLUME, DAYS, _ledger_averages
from cost.tracker import InferenceCost

QUALITY_GATES_PATH = Path("evaluation/quality_gate_log.csv")
PERCENT_QUANTUM = Decimal("0.01")


def load_gate_status(path: Path = QUALITY_GATES_PATH) -> dict[str, tuple[bool, str]]:
    """Return all-gates status and failed gate names for every measured model."""

    frame = pd.read_csv(path)
    required = {"model", "gate", "passed"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Quality-gate artifact is missing columns: {sorted(missing)}")
    statuses: dict[str, tuple[bool, str]] = {}
    for model, rows in frame.groupby("model", sort=True):
        passed = rows["passed"].astype(str).str.lower().eq("true")
        failed = ",".join(rows.loc[~passed, "gate"].astype(str))
        statuses[str(model)] = (bool(passed.all()), failed or "none")
    return statuses


def _model_costs(records: list[InferenceCost]) -> dict[str, Decimal]:
    grouped: dict[str, list[Decimal]] = {}
    for record in records:
        grouped.setdefault(record.model, []).append(Decimal(record.total_cost_usd))
    return {
        model: sum(costs, Decimal("0")) / Decimal(len(costs))
        for model, costs in grouped.items()
    }


def build_cost_comparison(
    records: list[InferenceCost],
    gate_status: dict[str, tuple[bool, str]],
) -> pd.DataFrame:
    """Compare measured request costs without relaxing clinical gates."""

    costs = _model_costs(records)
    rows = []
    for model in sorted(costs):
        eligible, failed = gate_status.get(model, (False, "missing_quality_evidence"))
        pricing = MODEL_PRICING[model]
        rows.append(
            {
                "model": model,
                "input_usd_per_million": str(pricing.input_usd),
                "cached_input_usd_per_million": str(pricing.cached_input_usd),
                "output_usd_per_million": str(pricing.output_usd),
                "average_cost_per_request_usd": f"{costs[model]:.8f}",
                "average_cost_per_request_kes": (
                    f"{usd_to_kes(costs[model]):.4f}"
                ),
                "all_quality_gates_passed": eligible,
                "failed_gates": failed,
                "pricing_verified_on": PRICING_VERIFIED_ON,
                "pricing_source": pricing.source_url,
                "usd_to_kes": str(EXCHANGE_RATE),
                "exchange_rate_date": EXCHANGE_RATE_DATE,
                "exchange_rate_source": EXCHANGE_RATE_SOURCE,
            }
        )
    return pd.DataFrame(rows)


def select_cheapest_eligible(
    comparison: pd.DataFrame,
) -> str | None:
    """Return the cheapest eligible measured model, or a safe no-result."""

    eligible = comparison[comparison["all_quality_gates_passed"].astype(bool)].copy()
    if eligible.empty:
        return None
    eligible["_cost"] = eligible["average_cost_per_request_usd"].map(Decimal)
    return str(eligible.sort_values(["_cost", "model"]).iloc[0]["model"])


def _scenario_cost(records: list[InferenceCost], model: str) -> Decimal:
    averages = _ledger_averages(records)
    cost = Decimal("0")
    for feature, daily_volume in DAILY_FEATURE_VOLUME.items():
        cost += averages[(model, feature)]["cost_usd"] * daily_volume * DAYS
    return cost.quantize(Decimal("0.00000001"), ROUND_HALF_UP)


def _savings(baseline: Decimal, proposed: Decimal) -> tuple[Decimal, Decimal]:
    saved = baseline - proposed
    percentage = (saved / baseline * Decimal("100")).quantize(
        PERCENT_QUANTUM,
        ROUND_HALF_UP,
    )
    return saved, percentage


def build_savings_analysis(
    records: list[InferenceCost],
    projection: pd.DataFrame,
    comparison: pd.DataFrame,
) -> pd.DataFrame:
    """Recommend structural savings only when all clinical gates pass."""

    baseline = Decimal(
        str(projection.loc[projection["scope"] == "overall", "projected_cost_usd"].iloc[0])
    )
    selected = select_cheapest_eligible(comparison)
    if selected is None:
        return _no_eligible_row(baseline)
    proposed = _scenario_cost(records, selected)
    saved, percentage = _savings(baseline, proposed)
    rows = [
        _routing_row(baseline, proposed, saved, percentage, selected),
        _cache_row(baseline),
    ]
    return pd.DataFrame(rows)


def _routing_row(
    baseline: Decimal,
    proposed: Decimal,
    saved: Decimal,
    percentage: Decimal,
    model: str,
) -> dict[str, object]:
    return {
        "strategy": "quality_gated_model_routing",
        "status": "RECOMMENDED",
        "selected_model": model,
        "quality_preserved": True,
        "baseline_30d_usd": f"{baseline:.8f}",
        "proposed_30d_usd": f"{proposed:.8f}",
        "savings_usd": f"{saved:.8f}",
        "savings_percent": str(percentage),
        "reason": "Cheapest model that passes every SPEC-7.1 clinical gate.",
    }


def _cache_row(baseline: Decimal) -> dict[str, object]:
    return {
        "strategy": "prompt_caching",
        "status": "NOT_APPLICABLE",
        "selected_model": "none",
        "quality_preserved": True,
        "baseline_30d_usd": f"{baseline:.8f}",
        "proposed_30d_usd": f"{baseline:.8f}",
        "savings_usd": "0.00000000",
        "savings_percent": "0.00",
        "reason": (
            "Provider cache usage was not reported and measured prompts are below "
            "the 1,024-token caching threshold."
        ),
    }


def _no_eligible_row(baseline: Decimal) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "strategy": "quality_gated_model_routing",
                "status": "NO_ELIGIBLE_MODEL",
                "selected_model": "none",
                "quality_preserved": True,
                "baseline_30d_usd": f"{baseline:.8f}",
                "proposed_30d_usd": f"{baseline:.8f}",
                "savings_usd": "0.00000000",
                "savings_percent": "0.00",
                "reason": "No measured model passes every required clinical gate.",
            }
        ]
    )
