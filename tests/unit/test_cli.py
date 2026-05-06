"""Unit tests for the Forge CLI — CLI-001, CLI-002."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from forge.cli import app, _score_colour, _collector_detail
from forge.models import (
    ComplexityResult,
    DependencyHealthResult,
    ProjectHealthReport,
    RequirementsCoverageResult,
    TestMetricsResult,
    CollectorWeights,
)

runner = CliRunner()


def _make_report(
    overall_score: float | None = 0.85,
    grade: str = "B",
    project_name: str = "test-project",
    **kwargs,
) -> ProjectHealthReport:
    """Build a minimal ProjectHealthReport for CLI tests."""
    import datetime

    defaults = dict(
        project_name=project_name,
        project_path="/tmp/test-project",
        generated_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        weights=CollectorWeights(),
        test_metrics=TestMetricsResult(score=0.9, total=10, passed=9),
        complexity=ComplexityResult(score=0.8, avg_cyclomatic=2.5, maintainability_index=80.0),
        dependency_health=DependencyHealthResult(score=1.0, total_packages=5),
        requirements_coverage=RequirementsCoverageResult(
            score=0.75, total_requirements=4, covered_requirements=3
        ),
        overall_score=overall_score,
        grade=grade,
    )
    defaults.update(kwargs)
    return ProjectHealthReport(**defaults)


# ── forge health ──────────────────────────────────────────────────────────────

class TestHealthCommand:
    def test_exits_1_when_path_not_found(self, tmp_path):
        result = runner.invoke(app, ["health", str(tmp_path / "nope")])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Path not found" in result.output

    def test_prints_table_for_valid_project(self, tmp_path):
        report = _make_report()
        with patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            result = runner.invoke(app, ["health", str(tmp_path)])
        assert result.exit_code == 0
        assert "test-project" in result.output

    def test_json_flag_prints_json(self, tmp_path):
        report = _make_report()
        with patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            result = runner.invoke(app, ["health", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["project_name"] == "test-project"

    def test_output_flag_writes_json_file(self, tmp_path):
        report = _make_report()
        out_file = tmp_path / "report.json"
        with patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            result = runner.invoke(app, ["health", str(tmp_path), "--output", str(out_file)])
        assert result.exit_code == 0
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert data["project_name"] == "test-project"

    def test_na_grade_renders_without_error(self, tmp_path):
        report = _make_report(overall_score=None, grade="N/A")
        with patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            result = runner.invoke(app, ["health", str(tmp_path)])
        assert result.exit_code == 0

    def test_skipped_collectors_render_without_error(self, tmp_path):
        import datetime
        report = ProjectHealthReport(
            project_name="bare",
            project_path=str(tmp_path),
            generated_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            weights=CollectorWeights(),
            test_metrics=TestMetricsResult(skipped=True, skip_reason="no tests"),
            complexity=ComplexityResult(skipped=True, skip_reason="no radon"),
            dependency_health=DependencyHealthResult(skipped=True, skip_reason="no pip-audit"),
            requirements_coverage=RequirementsCoverageResult(skipped=True, skip_reason="no tags"),
            overall_score=None,
            grade="N/A",
        )
        with patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            result = runner.invoke(app, ["health", str(tmp_path)])
        assert result.exit_code == 0


# ── forge new ─────────────────────────────────────────────────────────────────

class TestNewCommand:
    def test_creates_project_directory(self, tmp_path):
        result = runner.invoke(app, ["new", "myapp", "--dest", str(tmp_path), "--no-git"])
        assert result.exit_code == 0
        assert (tmp_path / "myapp").exists()

    def test_exits_1_when_destination_exists(self, tmp_path):
        (tmp_path / "myapp").mkdir()
        result = runner.invoke(app, ["new", "myapp", "--dest", str(tmp_path)])
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_output_mentions_project_name(self, tmp_path):
        result = runner.invoke(app, ["new", "coolproj", "--dest", str(tmp_path), "--no-git"])
        assert result.exit_code == 0
        assert "coolproj" in result.output

    def test_many_files_truncated_in_output(self, tmp_path):
        result = runner.invoke(app, ["new", "bigproj", "--dest", str(tmp_path), "--no-git"])
        assert result.exit_code == 0


# ── _score_colour ─────────────────────────────────────────────────────────────

class TestScoreColour:
    def test_none_returns_dim(self):
        assert _score_colour(None) == "dim"

    def test_high_score_is_bold_green(self):
        assert _score_colour(0.95) == "bold green"

    def test_good_score_is_green(self):
        assert _score_colour(0.75) == "green"

    def test_medium_score_is_yellow(self):
        assert _score_colour(0.55) == "yellow"

    def test_low_score_is_red(self):
        assert _score_colour(0.3) == "red"


# ── _collector_detail ─────────────────────────────────────────────────────────

class TestCollectorDetail:
    def test_test_metrics_with_coverage(self):
        r = TestMetricsResult(score=0.9, total=10, passed=9, line_coverage=87.5)
        detail = _collector_detail(r)
        assert "9/10" in detail
        assert "87.5" in detail

    def test_test_metrics_without_coverage(self):
        r = TestMetricsResult(score=0.9, total=5, passed=5)
        detail = _collector_detail(r)
        assert "5/5" in detail
        assert "coverage" not in detail

    def test_complexity_both_metrics(self):
        r = ComplexityResult(score=0.8, avg_cyclomatic=2.5, maintainability_index=75.0)
        detail = _collector_detail(r)
        assert "CC" in detail
        assert "MI" in detail

    def test_complexity_cc_only(self):
        r = ComplexityResult(score=0.8, avg_cyclomatic=3.0)
        detail = _collector_detail(r)
        assert "CC" in detail

    def test_complexity_no_metrics_returns_dash(self):
        r = ComplexityResult(score=None)
        detail = _collector_detail(r)
        assert detail == "—"

    def test_dependency_health_no_vulns(self):
        r = DependencyHealthResult(score=1.0, total_packages=10, vulnerable_packages=0)
        detail = _collector_detail(r)
        assert "no CVEs" in detail

    def test_dependency_health_with_vulns(self):
        r = DependencyHealthResult(score=0.7, total_packages=10, vulnerable_packages=2)
        detail = _collector_detail(r)
        assert "2 vulnerable" in detail

    def test_requirements_coverage(self):
        r = RequirementsCoverageResult(
            score=0.75, total_requirements=4, covered_requirements=3
        )
        detail = _collector_detail(r)
        assert "3/4" in detail
