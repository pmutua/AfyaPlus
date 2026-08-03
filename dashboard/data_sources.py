"""Validated loaders for SPEC-7.1 through SPEC-7.3 evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


class DashboardDataError(RuntimeError):
    """Raised when required dashboard evidence is missing or malformed."""


@dataclass(frozen=True)
class BudgetEvidence:
    projected_requests: int
    projected_cost_usd: float
    projected_cost_kes: float
    daily_budget_usd: float
    utilization: float
    status: str
    monthly_budget_usd: float
    monthly_utilization: float
    monthly_status: str
    exchange_rate: float
    exchange_rate_date: str


@dataclass(frozen=True)
class DashboardData:
    quality_rows: tuple[dict[str, object], ...]
    drift_rows: tuple[dict[str, object], ...]
    budget: BudgetEvidence


def _read_csv(path: Path, required: set[str]) -> pd.DataFrame:
    if not path.is_file():
        raise DashboardDataError(f"Required artifact is missing: {path}")
    try:
        frame = pd.read_csv(path)
    except (OSError, pd.errors.ParserError) as exc:
        raise DashboardDataError(f"Could not read artifact: {path}") from exc
    missing = required - set(frame.columns)
    if missing:
        raise DashboardDataError(
            f"{path.name} is missing columns: {sorted(missing)}"
        )
    if frame.empty:
        raise DashboardDataError(f"Required artifact is empty: {path}")
    return frame


def _boolean(series: pd.Series, name: str) -> pd.Series:
    normalized = series.astype(str).str.strip().str.lower()
    invalid = ~normalized.isin({"true", "false"})
    if invalid.any():
        raise DashboardDataError(f"{name} contains invalid boolean values.")
    return normalized.eq("true")


def _numeric(frame: pd.DataFrame, columns: tuple[str, ...], name: str) -> None:
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[list(columns)].isna().any().any():
        raise DashboardDataError(f"{name} contains invalid numeric values.")


def _gate_status(root: Path) -> dict[str, bool]:
    path = root / "evaluation" / "model_comparison_summary.csv"
    frame = _read_csv(path, {"model", "all_gates_passed"})
    frame["all_gates_passed"] = _boolean(
        frame["all_gates_passed"],
        "all_gates_passed",
    )
    return dict(zip(frame["model"].astype(str), frame["all_gates_passed"]))


def load_quality_rows(root: Path) -> tuple[dict[str, object], ...]:
    """Aggregate sanitized model-feature quality evidence."""

    required = {
        "model", "feature", "status", "rouge_l", "overall",
        "grounding_compliance_pass",
    }
    path = root / "evaluation" / "full_evaluation_results.csv"
    frame = _read_csv(path, required)
    _numeric(frame, ("rouge_l", "overall"), path.name)
    frame["grounding_compliance_pass"] = _boolean(
        frame["grounding_compliance_pass"],
        "grounding_compliance_pass",
    )
    gates = _gate_status(root)
    rows = [
        _quality_row(str(model), str(feature), group, gates)
        for (model, feature), group in frame.groupby(["model", "feature"], sort=True)
    ]
    return tuple(rows)


def _quality_row(
    model: str,
    feature: str,
    group: pd.DataFrame,
    gates: dict[str, bool],
) -> dict[str, object]:
    successful = group[group["status"] == "success"]
    if successful.empty:
        raise DashboardDataError(f"No successful evidence for {model}/{feature}.")
    return {
        "model": model,
        "feature": feature,
        "success_rate": len(successful) / len(group),
        "rouge_l": float(successful["rouge_l"].mean()),
        "overall": float(successful["overall"].mean()),
        "grounding_rate": float(
            successful["grounding_compliance_pass"].mean()
        ),
        "eligible": gates.get(model, False),
    }


def load_drift_rows(root: Path) -> tuple[dict[str, object], ...]:
    """Load the latest complete monthly drift vector."""

    required = {
        "month", "month_index", "column", "current_mean", "mean_change",
        "drift_detected", "signal_type", "requires_action",
    }
    path = root / "drift" / "drift_trend_table.csv"
    frame = _read_csv(path, required)
    _numeric(frame, ("month_index", "current_mean", "mean_change"), path.name)
    for column in ("drift_detected", "requires_action"):
        frame[column] = _boolean(frame[column], column)
    latest = frame[frame["month_index"] == frame["month_index"].max()]
    return tuple(
        {
            "month": str(row["month"]),
            "column": str(row["column"]),
            "current_mean": float(row["current_mean"]),
            "mean_change": float(row["mean_change"]),
            "drift_detected": bool(row["drift_detected"]),
            "signal_type": str(row["signal_type"]),
            "requires_action": bool(row["requires_action"]),
        }
        for _, row in latest.iterrows()
    )


def load_budget(root: Path) -> BudgetEvidence:
    """Load and validate the reconciled overall cost projection."""

    required = {
        "scope", "projected_requests", "projected_cost_usd",
        "projected_cost_kes", "daily_budget_usd", "budget_utilization",
        "budget_status", "monthly_budget_usd", "monthly_budget_utilization",
        "monthly_budget_status", "usd_to_kes", "exchange_rate_date",
    }
    path = root / "cost" / "cost_projection_30d.csv"
    frame = _read_csv(path, required)
    overall = frame[frame["scope"] == "overall"].copy()
    if len(overall) != 1:
        raise DashboardDataError("Cost projection needs exactly one overall row.")
    numeric = (
        "projected_requests", "projected_cost_usd", "projected_cost_kes",
        "daily_budget_usd", "budget_utilization", "monthly_budget_usd",
        "monthly_budget_utilization", "usd_to_kes",
    )
    _numeric(overall, numeric, path.name)
    row = overall.iloc[0]
    return BudgetEvidence(
        projected_requests=int(row["projected_requests"]),
        projected_cost_usd=float(row["projected_cost_usd"]),
        projected_cost_kes=float(row["projected_cost_kes"]),
        daily_budget_usd=float(row["daily_budget_usd"]),
        utilization=float(row["budget_utilization"]),
        status=str(row["budget_status"]),
        monthly_budget_usd=float(row["monthly_budget_usd"]),
        monthly_utilization=float(row["monthly_budget_utilization"]),
        monthly_status=str(row["monthly_budget_status"]),
        exchange_rate=float(row["usd_to_kes"]),
        exchange_rate_date=str(row["exchange_rate_date"]),
    )


def load_dashboard_data(root: Path) -> DashboardData:
    """Load every mandatory dashboard section from generated artifacts."""

    return DashboardData(
        quality_rows=load_quality_rows(root),
        drift_rows=load_drift_rows(root),
        budget=load_budget(root),
    )
