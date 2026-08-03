"""Reconciled 30-day AfyaPlus workload and budget projections."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

import pandas as pd

from cost.pricing import (
    EXCHANGE_RATE,
    EXCHANGE_RATE_DATE,
    EXCHANGE_RATE_DOCUMENT,
    EXCHANGE_RATE_PUBLISHED_ON,
    EXCHANGE_RATE_SOURCE,
    PRICING_VERIFIED_ON,
    usd_to_kes,
)
from cost.tracker import InferenceCost

DAYS = 30
DAILY_FEATURE_VOLUME = {
    "clinical_routing": 120,
    "insurance_verification": 100,
    "medication_safety": 80,
}
MODEL_SHARES = {
    "openai/gpt-4o-mini": Decimal("0.75"),
    "openai/gpt-4o": Decimal("0.25"),
}
DAILY_BUDGET_USD = Decimal("0.12")
MONTHLY_BUDGET_USD = DAILY_BUDGET_USD * DAYS
MONEY_QUANTUM = Decimal("0.00000001")


def budget_status(spend: Decimal, cap: Decimal) -> tuple[str, Decimal]:
    """Return an out-of-band alert status and utilization for any spend/cap pair.

    Used for both the daily and the independently-tracked monthly cap - the
    thresholds (80% WARNING, 95% CRITICAL) are the same in either case.
    """

    if spend < 0 or cap <= 0:
        raise ValueError("Spend must be non-negative and cap must be positive.")
    utilization = spend / cap
    if utilization >= Decimal("0.95"):
        return "CRITICAL", utilization
    if utilization >= Decimal("0.80"):
        return "WARNING", utilization
    return "OK", utilization


def _ledger_averages(
    records: list[InferenceCost],
) -> dict[tuple[str, str], dict[str, Decimal]]:
    grouped: dict[tuple[str, str], list[InferenceCost]] = defaultdict(list)
    for record in records:
        grouped[(record.model, record.feature)].append(record)
    averages: dict[tuple[str, str], dict[str, Decimal]] = {}
    for key, items in grouped.items():
        count = Decimal(len(items))
        averages[key] = {
            "input_tokens": sum(Decimal(item.input_tokens) for item in items) / count,
            "cached_tokens": sum(
                Decimal(item.cached_input_tokens) for item in items
            ) / count,
            "output_tokens": sum(Decimal(item.output_tokens) for item in items) / count,
            "cost_usd": sum(Decimal(item.total_cost_usd) for item in items) / count,
        }
    return averages


def _detail_row(
    model: str,
    feature: str,
    share: Decimal,
    daily_feature_requests: int,
    averages: dict[str, Decimal],
) -> dict[str, object]:
    daily_requests = int(Decimal(daily_feature_requests) * share)
    requests = daily_requests * DAYS
    projected_tokens = {
        name: str((averages[name] * requests).quantize(Decimal("1"), ROUND_HALF_UP))
        for name in ("input_tokens", "cached_tokens", "output_tokens")
    }
    cost = (averages["cost_usd"] * requests).quantize(
        MONEY_QUANTUM,
        ROUND_HALF_UP,
    )
    return {
        "scope": "model_feature",
        "model": model,
        "feature": feature,
        "model_mix_share": str(share),
        "daily_requests": daily_requests,
        "projected_requests": requests,
        "projected_input_tokens": projected_tokens["input_tokens"],
        "projected_cached_input_tokens": projected_tokens["cached_tokens"],
        "projected_output_tokens": projected_tokens["output_tokens"],
        "projected_cost_usd": f"{cost:.8f}",
        "projected_cost_kes": f"{usd_to_kes(cost, quantum=Decimal('0.01')):.2f}",
    }


def _total_row(details: list[dict[str, object]]) -> dict[str, object]:
    total_cost = sum(
        (Decimal(str(row["projected_cost_usd"])) for row in details),
        Decimal("0"),
    )
    daily_cost = total_cost / DAYS
    status, utilization = budget_status(daily_cost, DAILY_BUDGET_USD)
    monthly_status, monthly_utilization = budget_status(
        total_cost, MONTHLY_BUDGET_USD
    )
    return {
        "scope": "overall",
        "model": "75% gpt-4o-mini / 25% gpt-4o",
        "feature": "all",
        "model_mix_share": "1.00",
        "daily_requests": sum(int(row["daily_requests"]) for row in details),
        "projected_requests": sum(int(row["projected_requests"]) for row in details),
        "projected_input_tokens": str(
            sum(Decimal(str(row["projected_input_tokens"])) for row in details)
        ),
        "projected_cached_input_tokens": str(
            sum(Decimal(str(row["projected_cached_input_tokens"])) for row in details)
        ),
        "projected_output_tokens": str(
            sum(Decimal(str(row["projected_output_tokens"])) for row in details)
        ),
        "projected_cost_usd": f"{total_cost:.8f}",
        "projected_cost_kes": f"{usd_to_kes(total_cost, quantum=Decimal('0.01')):.2f}",
        "daily_budget_usd": str(DAILY_BUDGET_USD),
        "budget_utilization": f"{utilization:.4f}",
        "budget_status": status,
        "monthly_budget_usd": str(MONTHLY_BUDGET_USD),
        "monthly_budget_utilization": f"{monthly_utilization:.4f}",
        "monthly_budget_status": monthly_status,
    }


def build_projection(
    records: list[InferenceCost],
    model_shares: dict[str, Decimal] | None = None,
) -> pd.DataFrame:
    """Build detail rows and one exactly reconciled overall row."""

    if not records:
        raise ValueError("Projection requires cost records.")
    shares = model_shares or MODEL_SHARES
    if sum(shares.values(), Decimal("0")) != Decimal("1"):
        raise ValueError("Model shares must sum exactly to 1.")
    averages = _ledger_averages(records)
    details = [
        _detail_row(model, feature, share, volume, averages[(model, feature)])
        for feature, volume in DAILY_FEATURE_VOLUME.items()
        for model, share in shares.items()
    ]
    total = _total_row(details)
    frame = pd.DataFrame([*details, total])
    frame["pricing_verified_on"] = PRICING_VERIFIED_ON
    frame["usd_to_kes"] = str(EXCHANGE_RATE)
    frame["exchange_rate_date"] = EXCHANGE_RATE_DATE
    frame["exchange_rate_published_on"] = EXCHANGE_RATE_PUBLISHED_ON
    frame["exchange_rate_source"] = EXCHANGE_RATE_SOURCE
    frame["exchange_rate_document"] = EXCHANGE_RATE_DOCUMENT
    return frame
