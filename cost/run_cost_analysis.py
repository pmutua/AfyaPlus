"""Generate all required SPEC-7.3 cost and efficiency artifacts."""

from __future__ import annotations

from pathlib import Path

from cost.optimizer import (
    QUALITY_GATES_PATH,
    build_cost_comparison,
    build_savings_analysis,
    load_gate_status,
)
from cost.projection import build_projection
from cost.tracker import (
    EVALUATION_PATH,
    load_evaluation_records,
    write_cost_ledger,
)

OUTPUT_DIR = Path("cost")


def run_pipeline(
    evaluation_path: Path = EVALUATION_PATH,
    gates_path: Path = QUALITY_GATES_PATH,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Path]:
    """Write the deterministic ledger, projection, comparison, and savings CSV."""

    records = load_evaluation_records(evaluation_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = write_cost_ledger(records, output_dir / "inference_costs.jsonl")
    projection = build_projection(records)
    projection_path = output_dir / "cost_projection_30d.csv"
    projection.to_csv(projection_path, index=False)
    comparison = build_cost_comparison(records, load_gate_status(gates_path))
    comparison_path = output_dir / "cost_per_request_comparison.csv"
    comparison.to_csv(comparison_path, index=False)
    savings = build_savings_analysis(records, projection, comparison)
    savings_path = output_dir / "structural_savings_analysis.csv"
    savings.to_csv(savings_path, index=False)
    return {
        "ledger": ledger_path,
        "projection": projection_path,
        "comparison": comparison_path,
        "savings": savings_path,
    }


def main() -> None:
    """Run the SPEC-7.3 analysis from the repository root."""

    for name, path in run_pipeline().items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
