"""Validated K-S drift decisions for sanitized AfyaPlus metrics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

import pandas as pd
from scipy.stats import ks_2samp

MONITORED_COLUMNS = (
    "rouge_l",
    "overall",
    "latency_ms",
    "total_tokens",
    "grounding_compliance",
)
QUALITY_COLUMNS = frozenset({"rouge_l", "overall", "grounding_compliance"})
MINIMUM_SAMPLES = 20


@dataclass(frozen=True)
class ColumnDrift:
    """Machine-readable evidence for one monitored column."""

    column: str
    statistic: float
    p_value: float
    reference_mean: float
    current_mean: float
    mean_change: float
    drift_detected: bool
    signal_type: str
    requires_action: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DriftReport:
    """One window's deterministic drift decision."""

    threshold: float
    column_results: tuple[ColumnDrift, ...]

    @property
    def drifted_columns(self) -> tuple[str, ...]:
        return tuple(item.column for item in self.column_results if item.drift_detected)

    @property
    def needs_action(self) -> bool:
        return any(item.requires_action for item in self.column_results)


def _numeric_values(frame: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if len(values) < MINIMUM_SAMPLES:
        raise ValueError(
            f"{column!r} requires at least {MINIMUM_SAMPLES} numeric observations."
        )
    return values


def _column_result(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    column: str,
    threshold: float,
    quality_columns: frozenset[str],
) -> ColumnDrift:
    reference_values = _numeric_values(reference, column)
    current_values = _numeric_values(current, column)
    statistic, p_value = ks_2samp(reference_values, current_values, method="asymp")
    reference_mean = float(reference_values.mean())
    current_mean = float(current_values.mean())
    drifted = bool(p_value < threshold)
    is_quality = column in quality_columns
    return ColumnDrift(
        column=column,
        statistic=round(float(statistic), 6),
        p_value=round(float(p_value), 10),
        reference_mean=round(reference_mean, 6),
        current_mean=round(current_mean, 6),
        mean_change=round(current_mean - reference_mean, 6),
        drift_detected=drifted,
        signal_type="quality" if is_quality else "operational",
        requires_action=drifted and is_quality and current_mean < reference_mean,
    )


def run_drift_check(
    reference: pd.DataFrame,
    current: pd.DataFrame,
    columns: Iterable[str] = MONITORED_COLUMNS,
    quality_columns: frozenset[str] = QUALITY_COLUMNS,
    threshold: float = 0.05,
) -> DriftReport:
    """Compare required columns and distinguish harmful quality decline."""

    if not 0 < threshold < 1:
        raise ValueError("threshold must be between 0 and 1.")
    requested = tuple(columns)
    missing = [
        column
        for column in requested
        if column not in reference.columns or column not in current.columns
    ]
    if missing:
        raise ValueError(f"Missing monitored columns: {missing}")
    results = tuple(
        _column_result(reference, current, column, threshold, quality_columns)
        for column in requested
    )
    return DriftReport(threshold=threshold, column_results=results)
