"""Explicit allowlist of evidence files the dashboard will serve raw.

Deliberately not a generic file browser: `DASHBOARD_ARTIFACT_ROOT` in
production is the whole app container (`/app`), including source code and
`requirements.txt`. Only the exact relative paths below are ever servable,
regardless of what else exists on disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ALLOWED_ARTIFACTS: tuple[str, ...] = (
    "evaluation/full_evaluation_results.csv",
    "evaluation/llm_judge_matrix.csv",
    "evaluation/model_comparison_summary.csv",
    "evaluation/quality_gate_log.csv",
    "drift/drift_trend_table.csv",
    "drift/drift_alert_log.jsonl",
    "drift/drift_month_1.html",
    "drift/drift_month_2.html",
    "drift/drift_month_3.html",
    "cost/cost_projection_30d.csv",
    "cost/cost_per_request_comparison.csv",
    "cost/structural_savings_analysis.csv",
    "executive_summary.md",
    "executive_summary.pdf",
)

_MEDIA_TYPES = {
    ".csv": "text/csv",
    ".html": "text/html",
    ".jsonl": "application/x-ndjson",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
}


class ArtifactNotAvailableError(RuntimeError):
    """Raised when a requested artifact is not allowlisted or not present."""


@dataclass(frozen=True)
class ArtifactEntry:
    relative_path: str
    size_bytes: int
    media_type: str


def list_available_artifacts(root: Path) -> tuple[ArtifactEntry, ...]:
    """Return only the allowlisted artifacts that actually exist on disk."""

    entries = []
    for relative in ALLOWED_ARTIFACTS:
        path = root / relative
        if path.is_file():
            entries.append(
                ArtifactEntry(
                    relative_path=relative,
                    size_bytes=path.stat().st_size,
                    media_type=_MEDIA_TYPES[path.suffix],
                )
            )
    return tuple(entries)


def resolve_artifact_path(root: Path, relative_path: str) -> Path:
    """Return the real file path for an allowlisted, existing artifact.

    Raises `ArtifactNotAvailableError` for anything not on the allowlist,
    missing on disk, or that would resolve outside `root` - the allowlist
    check happens on the exact requested string first, so path-traversal
    sequences never reach the filesystem resolution step at all.
    """

    if relative_path not in ALLOWED_ARTIFACTS:
        raise ArtifactNotAvailableError(f"Not an evidence artifact: {relative_path}")
    resolved_root = root.resolve()
    candidate = (root / relative_path).resolve()
    if resolved_root not in candidate.parents:
        raise ArtifactNotAvailableError(f"Not an evidence artifact: {relative_path}")
    if not candidate.is_file():
        raise ArtifactNotAvailableError(f"Artifact not generated yet: {relative_path}")
    return candidate
