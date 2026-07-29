"""Create a deterministic, identifier-minimized inference cost ledger."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

from cost.pricing import (
    EXCHANGE_RATE,
    EXCHANGE_RATE_DATE,
    PRICING_VERIFIED_ON,
    calculate_breakdown,
    usd_to_kes,
)

EVALUATION_PATH = Path("evaluation/full_evaluation_results.csv")
REQUIRED_COLUMNS = frozenset(
    {
        "question_id",
        "feature",
        "model",
        "status",
        "prompt_tokens",
        "completion_tokens",
    }
)


@dataclass(frozen=True)
class InferenceCost:
    """PII-free cost evidence for one successful evaluation request."""

    event_id: str
    model: str
    feature: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    cache_status: str
    input_cost_usd: str
    cached_input_cost_usd: str
    output_cost_usd: str
    total_cost_usd: str
    total_cost_kes: str
    pricing_verified_on: str
    exchange_rate_date: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _money(value: Decimal) -> str:
    return f"{value:.8f}"


def build_cost_record(row: pd.Series) -> InferenceCost:
    """Convert one sanitized SPEC-7.1 result into cost evidence."""

    input_tokens = int(row["prompt_tokens"])
    output_tokens = int(row["completion_tokens"])
    model = str(row["model"])
    breakdown = calculate_breakdown(model, input_tokens, output_tokens)
    event_id = f"evaluation:{row['question_id']}:{model.rsplit('/', 1)[-1]}"
    return InferenceCost(
        event_id=event_id,
        model=model,
        feature=str(row["feature"]),
        input_tokens=input_tokens,
        cached_input_tokens=0,
        output_tokens=output_tokens,
        cache_status="not_reported",
        input_cost_usd=_money(breakdown.input_cost_usd),
        cached_input_cost_usd=_money(breakdown.cached_input_cost_usd),
        output_cost_usd=_money(breakdown.output_cost_usd),
        total_cost_usd=_money(breakdown.total_cost_usd),
        total_cost_kes=f"{usd_to_kes(breakdown.total_cost_usd):.4f}",
        pricing_verified_on=PRICING_VERIFIED_ON,
        exchange_rate_date=EXCHANGE_RATE_DATE,
    )


def load_evaluation_records(path: Path = EVALUATION_PATH) -> list[InferenceCost]:
    """Load successful rows only and reject incomplete cost evidence."""

    frame = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Evaluation artifact is missing columns: {sorted(missing)}")
    successful = frame[frame["status"] == "success"].copy()
    if successful.empty:
        raise ValueError("Evaluation artifact has no successful requests.")
    ordered = successful.sort_values(["question_id", "model"])
    return [build_cost_record(row) for _, row in ordered.iterrows()]


def write_cost_ledger(records: list[InferenceCost], path: Path) -> Path:
    """Overwrite the generated ledger deterministically."""

    if not records:
        raise ValueError("At least one cost record is required.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), sort_keys=True) + "\n")
    return path
