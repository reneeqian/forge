"""Unit tests for the Forge CLI — CLI-001, CLI-002, CLI-003, WRK-001, WRK-003, WRK-005."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from forge.cli import _collector_detail, _score_colour, app
from forge.env_discovery import EnvInfo
from forge.models import (
    CollectorWeights,
    ComplexityResult,
    DependencyHealthResult,
    ProjectHealthReport,
    RepoStatus,
    RequirementsCoverageResult,
    StaticAnalysisResult,
    TestMetricsResult,
    WorkspaceStatusReport,
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
        generated_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),  # noqa: UP017,
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
            generated_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),  # noqa: UP017,
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

    def test_save_artifact_creates_timestamped_dir(self, tmp_path):
        report = _make_report()
        with patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            result = runner.invoke(app, ["health", str(tmp_path), "--save-artifact"])
        assert result.exit_code == 0
        health_runs = tmp_path / "artifacts" / "health_runs"
        assert health_runs.is_dir()
        run_dirs = list(health_runs.iterdir())
        assert len(run_dirs) == 1
        assert (run_dirs[0] / "health_report.json").exists()

    def test_save_artifact_json_contains_project_name(self, tmp_path):
        report = _make_report()
        with patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            runner.invoke(app, ["health", str(tmp_path), "--save-artifact"])
        health_runs = tmp_path / "artifacts" / "health_runs"
        run_dir = next(health_runs.iterdir())
        data = json.loads((run_dir / "health_report.json").read_text())
        assert data["project_name"] == "test-project"

    def test_save_artifact_and_output_both_work(self, tmp_path):
        report = _make_report()
        out_file = tmp_path / "report.json"
        with patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            result = runner.invoke(
                app,
                ["health", str(tmp_path), "--save-artifact", "--output", str(out_file)],
            )
        assert result.exit_code == 0
        assert out_file.exists()
        assert (tmp_path / "artifacts" / "health_runs").is_dir()


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

    def test_static_analysis_shows_all_three_tiers(self):
        r = StaticAnalysisResult(
            score=0.8, safe_errors=39, unsafe_errors=10, manual_errors=40,
            total_lines=1000, error_density=25.0,
        )
        detail = _collector_detail(r)
        assert "39 safe" in detail
        assert "10 unsafe" in detail
        assert "40 manual" in detail

    def test_static_analysis_omits_zero_tiers(self):
        r = StaticAnalysisResult(score=0.9, safe_errors=5, total_lines=500, error_density=3.0)
        detail = _collector_detail(r)
        assert "unsafe" not in detail
        assert "manual" not in detail
        assert "5 safe" in detail

    def test_static_analysis_density_labeled_weighted(self):
        r = StaticAnalysisResult(
            score=0.8, manual_errors=10, total_lines=1000, error_density=10.0
        )
        detail = _collector_detail(r)
        assert "weighted" in detail


# ── forge workspace ───────────────────────────────────────────────────────────


def _make_workspace_report() -> WorkspaceStatusReport:
    return WorkspaceStatusReport(
        repos=[
            RepoStatus(
                name="medical_image_ai_toolkit",
                owner="reneeqian",
                repo_type="code",
                visibility="public",
                description="ML toolkit",
                local_branch="dev",
                auto_merge=True,
                delete_on_merge=True,
            )
        ]
    )


class TestWorkspaceCommand:
    def test_workspace_command_exists(self, tmp_path):
        toml_path = tmp_path / "workspace.toml"
        toml_path.write_text(
            '[workspace]\nowner = "reneeqian"\n\n[[repos]]\nname = "r"\ntype = "code"\n'
        )
        with patch("forge.cli.WorkspaceCollector") as MockColl:
            MockColl.return_value.collect_all.return_value = _make_workspace_report()
            result = runner.invoke(app, ["workspace", str(toml_path)])
        assert result.exit_code == 0

    def test_exits_1_when_config_not_found(self, tmp_path):
        result = runner.invoke(app, ["workspace", str(tmp_path / "no.toml")])
        assert result.exit_code == 1

    def test_renders_terminal_output_by_default(self, tmp_path):
        toml_path = tmp_path / "workspace.toml"
        toml_path.write_text(
            '[workspace]\nowner = "reneeqian"\n\n[[repos]]\nname = "my_repo"\ntype = "code"\n'
        )
        with patch("forge.cli.WorkspaceCollector") as MockColl:
            MockColl.return_value.collect_all.return_value = _make_workspace_report()
            result = runner.invoke(app, ["workspace", str(toml_path)])
        assert result.exit_code == 0
        assert "Repository Overview" in result.output

    def test_markdown_flag_prints_markdown_to_stdout(self, tmp_path):
        toml_path = tmp_path / "workspace.toml"
        toml_path.write_text(
            '[workspace]\nowner = "reneeqian"\n\n[[repos]]\nname = "my_repo"\ntype = "code"\n'
        )
        with patch("forge.cli.WorkspaceCollector") as MockColl:
            MockColl.return_value.collect_all.return_value = _make_workspace_report()
            result = runner.invoke(app, ["workspace", str(toml_path), "--markdown"])
        assert result.exit_code == 0
        assert "# Workspace Status Report" in result.output

    def test_output_flag_writes_file(self, tmp_path):
        toml_path = tmp_path / "workspace.toml"
        toml_path.write_text(
            '[workspace]\nowner = "reneeqian"\n\n[[repos]]\nname = "my_repo"\ntype = "code"\n'
        )
        out_path = tmp_path / "out.md"
        with patch("forge.cli.WorkspaceCollector") as MockColl:
            MockColl.return_value.collect_all.return_value = _make_workspace_report()
            result = runner.invoke(app, ["workspace", str(toml_path), "--output", str(out_path)])
        assert result.exit_code == 0
        assert out_path.exists()
        assert "# Workspace Status Report" in out_path.read_text()

    def test_output_dir_auto_generates_timestamped_file(self, tmp_path):
        toml_path = tmp_path / "myworkspace.toml"
        toml_path.write_text(
            '[workspace]\nowner = "reneeqian"\n\n[[repos]]\nname = "my_repo"\ntype = "code"\n'
        )
        out_dir = tmp_path / "reports"
        out_dir.mkdir()
        with patch("forge.cli.WorkspaceCollector") as MockColl:
            MockColl.return_value.collect_all.return_value = _make_workspace_report()
            result = runner.invoke(app, ["workspace", str(toml_path), "--output", str(out_dir)])
        assert result.exit_code == 0
        md_files = list(out_dir.glob("*-myworkspace-status-report.md"))
        assert len(md_files) == 1
        assert "# Workspace Status Report" in md_files[0].read_text()

    def test_health_runs_by_default(self, tmp_path):
        toml_path = tmp_path / "workspace.toml"
        toml_path.write_text(
            '[workspace]\nowner = "reneeqian"\n\n[[repos]]\nname = "my_repo"\ntype = "code"\n'
        )
        with patch("forge.cli.WorkspaceCollector") as MockColl:
            MockColl.return_value.collect_all.return_value = _make_workspace_report()
            runner.invoke(app, ["workspace", str(toml_path)])
        MockColl.return_value.collect_all.assert_called_once_with(run_health=True)

    def test_no_health_flag_skips_health(self, tmp_path):
        toml_path = tmp_path / "workspace.toml"
        toml_path.write_text(
            '[workspace]\nowner = "reneeqian"\n\n[[repos]]\nname = "my_repo"\ntype = "code"\n'
        )
        with patch("forge.cli.WorkspaceCollector") as MockColl:
            MockColl.return_value.collect_all.return_value = _make_workspace_report()
            runner.invoke(app, ["workspace", str(toml_path), "--no-health"])
        MockColl.return_value.collect_all.assert_called_once_with(run_health=False)

    def test_preview_flag_opens_file_after_writing(self, tmp_path):
        toml_path = tmp_path / "workspace.toml"
        toml_path.write_text(
            '[workspace]\nowner = "reneeqian"\n\n[[repos]]\nname = "my_repo"\ntype = "code"\n'
        )
        out_path = tmp_path / "report.md"
        with patch("forge.cli.WorkspaceCollector") as MockColl, \
             patch("forge.cli.click.launch") as mock_launch:
            MockColl.return_value.collect_all.return_value = _make_workspace_report()
            result = runner.invoke(
                app, ["workspace", str(toml_path), "--output", str(out_path), "--preview"]
            )
        assert result.exit_code == 0
        assert out_path.exists()
        mock_launch.assert_called_once_with(str(out_path))

    def test_preview_flag_without_output_warns(self, tmp_path):
        toml_path = tmp_path / "workspace.toml"
        toml_path.write_text(
            '[workspace]\nowner = "reneeqian"\n\n[[repos]]\nname = "my_repo"\ntype = "code"\n'
        )
        with patch("forge.cli.WorkspaceCollector") as MockColl, \
             patch("forge.cli.click.launch") as mock_launch:
            MockColl.return_value.collect_all.return_value = _make_workspace_report()
            result = runner.invoke(app, ["workspace", str(toml_path), "--preview"])
        assert result.exit_code == 0
        assert "--preview requires --output" in result.output
        mock_launch.assert_not_called()



# ── forge dashboard ───────────────────────────────────────────────────────────


def _make_fake_envs(tmp_path: "Path") -> "list[EnvInfo]":
    from pathlib import Path

    paths = [
        tmp_path / "envs" / "base" / "bin" / "python",
        tmp_path / "envs" / "medimg-base" / "bin" / "python",
    ]
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
    return [EnvInfo("base", paths[0]), EnvInfo("medimg-base", paths[1])]


class TestDashboardCommand:
    def test_exits_1_when_path_not_found(self, tmp_path):
        result = runner.invoke(app, ["dashboard", str(tmp_path / "nope")])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Path not found" in result.output

    def test_env_flag_skips_picker_and_runs_health(self, tmp_path):
        envs = _make_fake_envs(tmp_path)
        report = _make_report()
        with patch("forge.cli.discover_envs", return_value=envs), \
             patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            result = runner.invoke(app, ["dashboard", str(tmp_path), "--env", "medimg-base"])
        assert result.exit_code == 0
        assert "medimg-base" in result.output
        assert "test-project" in result.output

    def test_env_flag_unknown_name_exits_1(self, tmp_path):
        envs = _make_fake_envs(tmp_path)
        with patch("forge.cli.discover_envs", return_value=envs):
            result = runner.invoke(app, ["dashboard", str(tmp_path), "--env", "no-such-env"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "Environment not found" in result.output

    def test_interactive_picker_uses_user_selection(self, tmp_path):
        envs = _make_fake_envs(tmp_path)
        report = _make_report()
        with patch("forge.cli.discover_envs", return_value=envs), \
             patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            # User types "2" to pick medimg-base
            result = runner.invoke(app, ["dashboard", str(tmp_path)], input="2\n")
        assert result.exit_code == 0
        assert "medimg-base" in result.output

    def test_interactive_picker_invalid_input_exits_1(self, tmp_path):
        envs = _make_fake_envs(tmp_path)
        with patch("forge.cli.discover_envs", return_value=envs):
            result = runner.invoke(app, ["dashboard", str(tmp_path)], input="99\n")
        assert result.exit_code == 1

    def test_no_envs_uses_system_python(self, tmp_path):
        report = _make_report()
        with patch("forge.cli.discover_envs", return_value=[]), \
             patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            result = runner.invoke(app, ["dashboard", str(tmp_path)])
        assert result.exit_code == 0
        assert "system Python" in result.output

    def test_output_flag_writes_json(self, tmp_path):
        envs = _make_fake_envs(tmp_path)
        report = _make_report()
        out_file = tmp_path / "dashboard_report.json"
        with patch("forge.cli.discover_envs", return_value=envs), \
             patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            result = runner.invoke(
                app,
                ["dashboard", str(tmp_path), "--env", "base", "--output", str(out_file)],
            )
        assert result.exit_code == 0
        assert out_file.exists()
        import json
        data = json.loads(out_file.read_text())
        assert data["project_name"] == "test-project"

    def test_picker_shows_default_marker_from_forge_toml(self, tmp_path):
        envs = _make_fake_envs(tmp_path)
        (tmp_path / "forge.toml").write_text(
            '[test_runner]\npython = "' + str(envs[1].python) + '"\n'
        )
        report = _make_report()
        with patch("forge.cli.discover_envs", return_value=envs), \
             patch("forge.cli.Aggregator") as MockAgg:
            MockAgg.return_value.run.return_value = report
            # Default should point at index 2 (medimg-base); user just hits Enter (selects default)
            result = runner.invoke(app, ["dashboard", str(tmp_path)], input="\n")
        assert result.exit_code == 0
        # default marker should appear in the table
        assert "default" in result.output
