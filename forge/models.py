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


class StaticAnalysisResult(CollectorResult):
    """REQ-011 — ruff/flake8 static analysis results."""

    collector: str = "static_analysis"
    total_errors: int = 0
    total_lines: int = 0
    error_density: float | None = None  # errors per 1000 lines


class TypeCoverageResult(CollectorResult):
    """REQ-012 — mypy type checking results."""

    collector: str = "type_coverage"
    total_errors: int = 0
    files_checked: int = 0


class DeadCodeResult(CollectorResult):
    """REQ-013 — vulture dead code detection results."""

    collector: str = "dead_code"
    unused_items: int = 0
    total_lines: int = 0
    unused_density: float | None = None  # unused items per 1000 lines


class MutationTestingResult(CollectorResult):
    """REQ-014 — mutmut mutation testing results (opt-in, REQ-015)."""

    collector: str = "mutation_testing"
    total_mutants: int = 0
    killed_mutants: int = 0
    mutation_score: float | None = None  # killed / total


# ── Weights & config ──────────────────────────────────────────────────────────


class CollectorWeights(BaseModel):
    """REQ-006 — configurable weights for the overall health score.

    Weights must sum to 1.0. Existing forge.toml files using the old
    4-collector layout (test_metrics + complexity + dependency_health +
    requirements_coverage = 1.0) must be updated to include the new
    collectors or set the new ones explicitly to 0.0.
    """

    test_metrics: float = Field(0.30, ge=0.0, le=1.0)
    complexity: float = Field(0.15, ge=0.0, le=1.0)
    dependency_health: float = Field(0.20, ge=0.0, le=1.0)
    requirements_coverage: float = Field(0.10, ge=0.0, le=1.0)
    static_analysis: float = Field(0.10, ge=0.0, le=1.0)
    type_coverage: float = Field(0.10, ge=0.0, le=1.0)
    dead_code: float = Field(0.05, ge=0.0, le=1.0)
    mutation_testing: float = Field(0.00, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "CollectorWeights":
        total = sum(getattr(self, f) for f in CollectorWeights.model_fields)
        if not (0.99 <= total <= 1.01):
            raise ValueError(
                f"Weights must sum to 1.0, got {total:.3f}. "
                "If you have an existing forge.toml with only the original 4 collectors, "
                "add the new collector weights (static_analysis, type_coverage, dead_code, "
                "mutation_testing) so all 8 sum to 1.0."
            )
        return self


# ── Top-level report ──────────────────────────────────────────────────────────

_COLLECTOR_FIELDS = (
    "test_metrics",
    "complexity",
    "dependency_health",
    "requirements_coverage",
    "static_analysis",
    "type_coverage",
    "dead_code",
    "mutation_testing",
)


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
    static_analysis: StaticAnalysisResult = Field(
        default_factory=lambda: StaticAnalysisResult(skipped=True, skip_reason="Not run")
    )
    type_coverage: TypeCoverageResult = Field(
        default_factory=lambda: TypeCoverageResult(skipped=True, skip_reason="Not run")
    )
    dead_code: DeadCodeResult = Field(
        default_factory=lambda: DeadCodeResult(skipped=True, skip_reason="Not run")
    )
    mutation_testing: MutationTestingResult = Field(
        default_factory=lambda: MutationTestingResult(
            skipped=True,
            skip_reason="Disabled by default; set [collectors.mutation_testing] enabled = true in forge.toml",
        )
    )

    @computed_field  # type: ignore[misc]
    @property
    def overall_score(self) -> float | None:
        """Weighted average of available collector scores (REQ-006, REQ-010)."""
        weighted_sum = 0.0
        total_weight = 0.0
        for key in _COLLECTOR_FIELDS:
            result = getattr(self, key)
            if result.score is not None:
                w = getattr(self.weights, key)
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
