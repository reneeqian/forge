"""Unit tests for forge.models — REQ-001, REQ-006."""

import pytest
from pydantic import ValidationError

from forge.models import (
    CollectorWeights,
    ComplexityResult,
    DependencyHealthResult,
    ProjectHealthReport,
    RequirementsCoverageResult,
    TestMetricsResult,
)


# ── CollectorWeights ──────────────────────────────────────────────────────────

class TestCollectorWeights:
    def test_default_weights_sum_to_one(self):
        w = CollectorWeights()
        total = sum(getattr(w, f) for f in CollectorWeights.model_fields)
        assert abs(total - 1.0) < 0.001

    def test_custom_valid_weights(self):
        w = CollectorWeights(
            test_metrics=0.40,
            complexity=0.15,
            dependency_health=0.20,
            requirements_coverage=0.10,
            static_analysis=0.05,
            type_coverage=0.05,
            dead_code=0.05,
            mutation_testing=0.00,
        )
        assert w.test_metrics == 0.40

    def test_weights_not_summing_to_one_raises(self):
        with pytest.raises(ValidationError, match="Weights must sum to 1.0"):
            CollectorWeights(
                test_metrics=0.50,
                complexity=0.50,
                dependency_health=0.10,
                requirements_coverage=0.10,
            )

    def test_negative_weight_raises(self):
        with pytest.raises(ValidationError):
            CollectorWeights(test_metrics=-0.1, complexity=0.4, dependency_health=0.4, requirements_coverage=0.3)


# ── ProjectHealthReport ───────────────────────────────────────────────────────

class TestProjectHealthReport:
    def test_overall_score_all_skipped_returns_none(self):
        report = ProjectHealthReport(project_name="x", project_path="/x")
        assert report.overall_score is None

    def test_overall_score_single_collector(self):
        report = ProjectHealthReport(
            project_name="x",
            project_path="/x",
            test_metrics=TestMetricsResult(score=0.8),
        )
        # Only test_metrics contributes — score should equal its value
        assert report.overall_score == 0.8

    def test_overall_score_weighted_average(self):
        weights = CollectorWeights(
            test_metrics=0.5,
            complexity=0.5,
            dependency_health=0.0,
            requirements_coverage=0.0,
            static_analysis=0.0,
            type_coverage=0.0,
            dead_code=0.0,
            mutation_testing=0.0,
        )
        report = ProjectHealthReport(
            project_name="x",
            project_path="/x",
            weights=weights,
            test_metrics=TestMetricsResult(score=1.0),
            complexity=ComplexityResult(score=0.0),
        )
        assert report.overall_score == pytest.approx(0.5, abs=0.01)

    def test_grade_A_for_high_score(self):
        report = ProjectHealthReport(
            project_name="x",
            project_path="/x",
            test_metrics=TestMetricsResult(score=0.95),
        )
        assert report.grade == "A"

    def test_grade_F_for_low_score(self):
        report = ProjectHealthReport(
            project_name="x",
            project_path="/x",
            test_metrics=TestMetricsResult(score=0.1),
        )
        assert report.grade == "F"

    def test_grade_NA_when_no_score(self):
        report = ProjectHealthReport(project_name="x", project_path="/x")
        assert report.grade == "N/A"

    def test_serialises_to_json(self):
        report = ProjectHealthReport(
            project_name="proj",
            project_path="/proj",
            test_metrics=TestMetricsResult(score=0.9, total=10, passed=9),
        )
        data = report.model_dump()
        assert data["project_name"] == "proj"
        assert "overall_score" in data
        assert "grade" in data

    def test_skipped_collector_excluded_from_score(self):
        """REQ-010: skipped collectors should not drag down the overall score."""
        report = ProjectHealthReport(
            project_name="x",
            project_path="/x",
            test_metrics=TestMetricsResult(score=1.0),
            complexity=ComplexityResult(skipped=True, skip_reason="no radon"),
        )
        # Only test_metrics contributed — should not be penalised for missing complexity
        assert report.overall_score == 1.0


# ── Individual result models ──────────────────────────────────────────────────

class TestCollectorResultModels:
    def test_test_metrics_result_defaults(self):
        r = TestMetricsResult()
        assert r.collector == "test_metrics"
        assert r.score is None
        assert r.total == 0

    def test_complexity_result_defaults(self):
        r = ComplexityResult()
        assert r.collector == "complexity"

    def test_dependency_health_result_defaults(self):
        r = DependencyHealthResult()
        assert r.collector == "dependency_health"
        assert r.vulnerabilities == []

    def test_requirements_coverage_result_defaults(self):
        r = RequirementsCoverageResult()
        assert r.collector == "requirements_coverage"
        assert r.uncovered == []

    def test_score_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            TestMetricsResult(score=1.5)
