"""Integration tests for Aggregator — SYS-001, COL-005, SYS-002."""

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.aggregator import Aggregator
from forge.models import ProjectHealthReport


class TestAggregator:
    def test_returns_project_health_report(self, tmp_project: Path):
        agg = Aggregator()
        with (
            patch.object(agg._test_metrics, "collect") as tm,
            patch.object(agg._complexity, "collect") as cx,
            patch.object(agg._dependency, "collect") as dep,
            patch.object(agg._requirements, "collect") as req,
        ):
            from forge.models import (
                ComplexityResult,
                DependencyHealthResult,
                RequirementsCoverageResult,
                TestMetricsResult,
            )
            tm.return_value = TestMetricsResult(score=0.9)
            cx.return_value = ComplexityResult(score=0.8)
            dep.return_value = DependencyHealthResult(score=1.0)
            req.return_value = RequirementsCoverageResult(score=0.5)

            report = agg.run(tmp_project)

        assert isinstance(report, ProjectHealthReport)
        assert report.overall_score is not None
        assert report.project_name != ""

    def test_uses_forge_toml_name(self, project_with_forge_toml: Path):
        agg = Aggregator()
        with (
            patch.object(agg._test_metrics, "collect") as tm,
            patch.object(agg._complexity, "collect") as cx,
            patch.object(agg._dependency, "collect") as dep,
            patch.object(agg._requirements, "collect") as req,
        ):
            from forge.models import (
                ComplexityResult,
                DependencyHealthResult,
                RequirementsCoverageResult,
                TestMetricsResult,
            )
            tm.return_value = TestMetricsResult(score=0.9)
            cx.return_value = ComplexityResult(score=0.8)
            dep.return_value = DependencyHealthResult(score=1.0)
            req.return_value = RequirementsCoverageResult(score=0.5)

            report = agg.run(project_with_forge_toml)

        assert report.project_name == "custom-name"

    def test_graceful_with_all_skipped_collectors(self, empty_project: Path):
        """SYS-002: if every collector skips, overall_score is None — no crash."""
        agg = Aggregator()
        report = agg.run(empty_project)
        assert isinstance(report, ProjectHealthReport)
        assert report.overall_score is None
        assert report.grade == "N/A"
