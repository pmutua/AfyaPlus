"""Generate SPEC-7.2 trend, alert, and Evidently HTML evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from drift.drift_monitor import MONITORED_COLUMNS, DriftReport, run_drift_check
from drift.simulate_production_traffic import (
    EVALUATION_RESULTS_PATH,
    SimulationConfig,
    simulate_monthly_windows,
)

if TYPE_CHECKING:
    from evidently import Dataset

OUTPUT_DIR = Path("drift")


def analyze_months(
    reference: pd.DataFrame,
    months: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, DriftReport]]:
    """Return long-form trend evidence using one fixed reference."""

    rows: list[dict[str, object]] = []
    reports: dict[str, DriftReport] = {}
    seen_drift: set[str] = set()
    for month_index, (month, current) in enumerate(months.items(), start=1):
        report = run_drift_check(reference, current)
        reports[month] = report
        for result in report.column_results:
            first_detected = result.drift_detected and result.column not in seen_drift
            rows.append(
                {
                    "month": month,
                    "month_index": month_index,
                    **result.to_dict(),
                    "first_detected": first_detected,
                }
            )
            if result.drift_detected:
                seen_drift.add(result.column)
    return pd.DataFrame(rows), reports


def write_alert_log(trend: pd.DataFrame, path: Path) -> Path:
    """Write one deterministic JSON line per drifted month/column."""

    path.parent.mkdir(parents=True, exist_ok=True)
    alerts = trend[trend["drift_detected"]].to_dict("records")
    with path.open("w", encoding="utf-8") as handle:
        for alert in alerts:
            handle.write(json.dumps(alert, ensure_ascii=False) + "\n")
    return path


def _evidently_dataset(frame: pd.DataFrame) -> Dataset:
    from evidently import DataDefinition, Dataset

    definition = DataDefinition(numerical_columns=list(MONITORED_COLUMNS))
    return Dataset.from_pandas(
        frame[list(MONITORED_COLUMNS)],
        data_definition=definition,
    )


def save_evidently_reports(
    reference: pd.DataFrame,
    months: dict[str, pd.DataFrame],
    output_dir: Path,
) -> tuple[Path, ...]:
    """Save one Evidently 0.7 K-S snapshot for each month."""

    from evidently import Report
    from evidently.presets import DataDriftPreset

    output_dir.mkdir(parents=True, exist_ok=True)
    reference_dataset = _evidently_dataset(reference)
    paths: list[Path] = []
    for index, current in enumerate(months.values(), start=1):
        report = Report(
            [DataDriftPreset(columns=list(MONITORED_COLUMNS), num_method="ks")]
        )
        snapshot = report.run(_evidently_dataset(current), reference_dataset)
        path = output_dir / f"drift_month_{index}.html"
        snapshot.save_html(str(path))
        paths.append(path)
    return tuple(paths)


def run_pipeline(
    evaluation_path: Path = EVALUATION_RESULTS_PATH,
    output_dir: Path = OUTPUT_DIR,
    config: SimulationConfig | None = None,
) -> dict[str, object]:
    """Generate all required SPEC-7.2 artifacts."""

    reference, months = simulate_monthly_windows(evaluation_path, config)
    trend, reports = analyze_months(reference, months)
    output_dir.mkdir(parents=True, exist_ok=True)
    trend_path = output_dir / "drift_trend_table.csv"
    trend.to_csv(trend_path, index=False)
    alert_path = write_alert_log(trend, output_dir / "drift_alert_log.jsonl")
    html_paths = save_evidently_reports(reference, months, output_dir)
    return {
        "trend_path": trend_path,
        "alert_path": alert_path,
        "html_paths": html_paths,
        "reports": reports,
    }


def main() -> None:
    """Run the deterministic monthly drift pipeline."""

    artifacts = run_pipeline()
    print(f"trend: {artifacts['trend_path']}")
    print(f"alerts: {artifacts['alert_path']}")
    for path in artifacts["html_paths"]:
        print(f"report: {path}")


if __name__ == "__main__":
    main()
