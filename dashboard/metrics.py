"""Dedicated Prometheus registry for executive dashboard evidence."""

from __future__ import annotations

from dataclasses import dataclass

from prometheus_client import CollectorRegistry, Gauge

from dashboard.data_sources import DashboardData
from dashboard.health import HealthEvidence


@dataclass(frozen=True)
class DashboardMetrics:
    """Prometheus gauges owned only by this dashboard process."""

    registry: CollectorRegistry
    upstream_health: Gauge
    quality_score: Gauge
    quality_gate: Gauge
    drift_detected: Gauge
    drift_action_required: Gauge
    projected_cost_usd: Gauge
    budget_utilization: Gauge
    monthly_budget_utilization: Gauge


def _gauge(
    registry: CollectorRegistry,
    name: str,
    description: str,
    labels: tuple[str, ...] = (),
) -> Gauge:
    return Gauge(name, description, list(labels), registry=registry)


def create_metrics() -> DashboardMetrics:
    """Create an isolated registry so tests and workers do not collide."""

    registry = CollectorRegistry()
    return DashboardMetrics(
        registry=registry,
        upstream_health=_gauge(
            registry, "afyaplus_upstream_health", "AfyaPlus health contract."
        ),
        quality_score=_gauge(
            registry, "afyaplus_feature_quality_score", "Measured quality.",
            ("model", "feature", "metric"),
        ),
        quality_gate=_gauge(
            registry, "afyaplus_model_quality_gate_pass", "Clinical gate.", ("model",)
        ),
        drift_detected=_gauge(
            registry, "afyaplus_drift_detected", "Latest drift.",
            ("column", "signal_type"),
        ),
        drift_action_required=_gauge(
            registry, "afyaplus_drift_action_required", "Quality drift action.",
            ("column",),
        ),
        projected_cost_usd=_gauge(
            registry, "afyaplus_projected_30d_cost_usd", "Projected 30-day USD."
        ),
        budget_utilization=_gauge(
            registry, "afyaplus_budget_utilization_ratio", "Daily budget utilization."
        ),
        monthly_budget_utilization=_gauge(
            registry, "afyaplus_monthly_budget_utilization_ratio",
            "Monthly budget utilization.",
        ),
    )


def publish_artifacts(metrics: DashboardMetrics, data: DashboardData) -> None:
    """Populate gauges from validated generated evidence."""

    for row in data.quality_rows:
        labels = {"model": str(row["model"]), "feature": str(row["feature"])}
        for name in ("success_rate", "rouge_l", "overall", "grounding_rate"):
            metrics.quality_score.labels(metric=name, **labels).set(float(row[name]))
        metrics.quality_gate.labels(model=str(row["model"])).set(
            int(bool(row["eligible"]))
        )
    for row in data.drift_rows:
        metrics.drift_detected.labels(
            column=str(row["column"]),
            signal_type=str(row["signal_type"]),
        ).set(int(bool(row["drift_detected"])))
        metrics.drift_action_required.labels(column=str(row["column"])).set(
            int(bool(row["requires_action"]))
        )
    metrics.projected_cost_usd.set(data.budget.projected_cost_usd)
    metrics.budget_utilization.set(data.budget.utilization)
    metrics.monthly_budget_utilization.set(data.budget.monthly_utilization)


def publish_health(
    metrics: DashboardMetrics,
    health: HealthEvidence,
) -> None:
    """Update upstream health without exposing endpoint details as labels."""

    metrics.upstream_health.set(1 if health.status == "HEALTHY" else 0)
