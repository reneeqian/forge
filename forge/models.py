"""Core data models for Forge project health reports.

All collector results and the top-level ProjectHealthReport are defined here.
Using Pydantic v2 for validation and clean JSON serialisation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, computed_field, model_validator


# ── Per-collector result models ───────────────────────────────────────────────


class CollectorResult(BaseModel):
    """Base result returned by every collector.

    score is None when the collector could not run (REQ-010).
    """

    collector: str
    score: float | None = Field(None, ge=0.0, le=1.0)
    skipped: bool = False
    skip_reason: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class TestMetricsResult(CollectorResult):
    """REQ-002 — pytest + coverage results."""

    collector: str = "test_metrics"
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped_tests: int = 0
    pass_rate: float | None = None
    line_coverage: float | None = None  # 0–100


class ComplexityResult(CollectorResult):
    """REQ-003 — radon complexity results."""

    collector: str = "complexity"
    avg_cyclomatic: float | None = None
    maintainability_index: float | None = None  # 0–100


class DependencyHealthResult(CollectorResult):
    """REQ-004 — pip-audit vulnerability results."""

    collector: str = "dependency_health"
    total_packages: int = 0
    vulnerable_packages: int = 0
    vulnerabilities: list[dict[str, Any]] = Field(default_factory=list)


class RequirementsCoverageResult(CollectorResult):
    """REQ-005 — requirement tag traceability results."""

    collector: str = "requirements_coverage"
    total_requirements: int = 0
    covered_requirements: int = 0
    uncovered: list[str] = Field(default_factory=list)


# ── Weights & config ──────────────────────────────────────────────────────────


class CollectorWeights(BaseModel):
    """REQ-006 — configurable weights for the overall health score."""

    test_metrics: float = Field(0.35, ge=0.0, le=1.0)
    complexity: float = Field(0.25, ge=0.0, le=1.0)
    dependency_health: float = Field(0.25, ge=0.0, le=1.0)
    requirements_coverage: float = Field(0.15, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "CollectorWeights":
        total = (
            self.test_metrics
            + self.complexity
            + self.dependency_health
            + self.requirements_coverage
        )
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"Weights must sum to 1.0, got {total:.3f}")
        return self


# ── Top-level report ──────────────────────────────────────────────────────────

_COLLECTOR_WEIGHT_MAP = {
    "test_metrics": "test_metrics",
    "complexity": "complexity",
    "dependency_health": "dependency_health",
    "requirements_coverage": "requirements_coverage",
}


class ProjectHealthReport(BaseModel):
    """REQ-001 — full health report for a single project."""

    project_name: str
    project_path: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    weights: CollectorWeights = Field(default_factory=CollectorWeights)

    test_metrics: TestMetricsResult = Field(
        default_factory=lambda: TestMetricsResult(skipped=True, skip_reason="Not run")
    )
    complexity: ComplexityResult = Field(
        default_factory=lambda: ComplexityResult(skipped=True, skip_reason="Not run")
    )
    dependency_health: DependencyHealthResult = Field(
        default_factory=lambda: DependencyHealthResult(skipped=True, skip_reason="Not run")
    )
    requirements_coverage: RequirementsCoverageResult = Field(
        default_factory=lambda: RequirementsCoverageResult(skipped=True, skip_reason="Not run")
    )

    @computed_field  # type: ignore[misc]
    @property
    def overall_score(self) -> float | None:
        """Weighted average of available collector scores (REQ-006, REQ-010)."""
        results = {
            "test_metrics": self.test_metrics,
            "complexity": self.complexity,
            "dependency_health": self.dependency_health,
            "requirements_coverage": self.requirements_coverage,
        }
        weight_values = {
            "test_metrics": self.weights.test_metrics,
            "complexity": self.weights.complexity,
            "dependency_health": self.weights.dependency_health,
            "requirements_coverage": self.weights.requirements_coverage,
        }

        weighted_sum = 0.0
        total_weight = 0.0
        for key, result in results.items():
            if result.score is not None:
                w = weight_values[key]
                weighted_sum += result.score * w
                total_weight += w

        if total_weight == 0:
            return None
        return round(weighted_sum / total_weight, 4)

    @computed_field  # type: ignore[misc]
    @property
    def grade(self) -> str:
        """Letter grade derived from overall_score."""
        s = self.overall_score
        if s is None:
            return "N/A"
        if s >= 0.90:
            return "A"
        if s >= 0.80:
            return "B"
        if s >= 0.70:
            return "C"
        if s >= 0.60:
            return "D"
        return "F"
