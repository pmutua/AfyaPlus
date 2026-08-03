"""Create deterministic AfyaPlus traffic windows from SPEC-7.1 evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

EVALUATION_RESULTS_PATH = Path("evaluation/full_evaluation_results.csv")
REQUIRED_COLUMNS = frozenset(
    {
        "channel",
        "feature",
        "status",
        "rouge_l",
        "overall",
        "latency_ms",
        "prompt_tokens",
        "completion_tokens",
        "grounding_compliance_pass",
    }
)


@dataclass(frozen=True)
class SimulationConfig:
    """Reproducible monthly-traffic settings."""

    rows: int = 240
    seed: int = 20260729


@dataclass(frozen=True)
class TrafficProfile:
    """Sanitized distribution parameters derived from evaluation evidence."""

    means: dict[str, float]
    standard_deviations: dict[str, float]
    channels: tuple[str, ...]
    features: tuple[str, ...]
    grounding_rate: float


def _require_columns(frame: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"Evaluation results are missing columns: {sorted(missing)}")


def _numeric_metric(
    frame: pd.DataFrame,
    column: str,
    minimum_deviation: float,
) -> tuple[float, float]:
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if len(values) < 10:
        raise ValueError(f"{column!r} needs at least 10 successful observations.")
    return float(values.mean()), max(float(values.std(ddof=1)), minimum_deviation)


def load_traffic_profile(path: Path = EVALUATION_RESULTS_PATH) -> TrafficProfile:
    """Load only sanitized aggregate inputs from the SPEC-7.1 artifact."""

    frame = pd.read_csv(path)
    _require_columns(frame)
    successful = frame[frame["status"] == "success"].copy()
    if len(successful) < 10:
        raise ValueError("Evaluation results need at least 10 successful rows.")
    successful["total_tokens"] = (
        pd.to_numeric(successful["prompt_tokens"])
        + pd.to_numeric(successful["completion_tokens"])
    )
    metrics = {
        "rouge_l": _numeric_metric(successful, "rouge_l", 0.03),
        "overall": _numeric_metric(successful, "overall", 0.25),
        "latency_ms": _numeric_metric(successful, "latency_ms", 100.0),
        "total_tokens": _numeric_metric(successful, "total_tokens", 20.0),
    }
    return TrafficProfile(
        means={name: values[0] for name, values in metrics.items()},
        standard_deviations={name: values[1] for name, values in metrics.items()},
        channels=tuple(sorted(successful["channel"].astype(str).unique())),
        features=tuple(sorted(successful["feature"].astype(str).unique())),
        grounding_rate=float(successful["grounding_compliance_pass"].astype(bool).mean()),
    )


def _normal(
    rng: np.random.Generator,
    mean: float,
    deviation: float,
    rows: int,
    lower: float,
    upper: float | None = None,
) -> np.ndarray:
    values = rng.normal(mean, deviation, rows)
    return np.clip(values, lower, upper) if upper is not None else np.maximum(values, lower)


def _window(
    profile: TrafficProfile,
    rng: np.random.Generator,
    config: SimulationConfig,
    month: int,
) -> pd.DataFrame:
    quality_shift = 0.0 if month < 3 else -0.12
    judge_shift = 0.0 if month < 3 else -0.8
    latency_scale = (1.0, 1.0, 1.35, 1.45)[month]
    token_scale = (1.0, 1.0, 1.25, 1.35)[month]
    grounding_rate = profile.grounding_rate if month < 3 else 0.75
    rows = config.rows
    metrics = _window_metrics(
        profile,
        rng,
        rows,
        quality_shift,
        judge_shift,
        latency_scale,
        token_scale,
    )
    return pd.DataFrame(
        {
            "channel": rng.choice(profile.channels, rows),
            "feature": rng.choice(profile.features, rows),
            **metrics,
            "grounding_compliance": rng.binomial(1, grounding_rate, rows),
        }
    )


def _window_metrics(
    profile: TrafficProfile,
    rng: np.random.Generator,
    rows: int,
    quality_shift: float,
    judge_shift: float,
    latency_scale: float,
    token_scale: float,
) -> dict[str, np.ndarray]:
    return {
        "rouge_l": _normal(
            rng, profile.means["rouge_l"] + quality_shift,
            profile.standard_deviations["rouge_l"], rows, 0, 1,
        ).round(4),
        "overall": _normal(
            rng, profile.means["overall"] + judge_shift,
            profile.standard_deviations["overall"], rows, 1, 5,
        ).round(2),
        "latency_ms": _normal(
            rng, profile.means["latency_ms"] * latency_scale,
            profile.standard_deviations["latency_ms"], rows, 1,
        ).round(2),
        "total_tokens": _normal(
            rng, profile.means["total_tokens"] * token_scale,
            profile.standard_deviations["total_tokens"], rows, 1,
        ).round(),
    }


def simulate_monthly_windows(
    evaluation_path: Path = EVALUATION_RESULTS_PATH,
    config: SimulationConfig | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Return one fixed reference and three deterministic monthly windows."""

    resolved = config or SimulationConfig()
    if resolved.rows < 20:
        raise ValueError("Simulation requires at least 20 rows per window.")
    profile = load_traffic_profile(evaluation_path)
    rng = np.random.default_rng(resolved.seed)
    reference = _window(profile, rng, resolved, month=0)
    months = {
        f"Month {month}": _window(profile, rng, resolved, month)
        for month in range(1, 4)
    }
    return reference, months
