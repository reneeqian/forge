"""Unit tests for WorkspaceReporter — REQ-018."""


from rich.console import Console

from forge.models import RepoStatus, WorkspaceStatusReport
from forge.workspace.reporter import WorkspaceReporter

# ── helpers ────────────────────────────────────────────────────────────────────


def _code_repo(
    name: str = "my_repo",
    auto_merge: bool = True,
    workflows: list[str] | None = None,
    grade: str | None = "A",
    issues: list[str] | None = None,
    forge_health_collectors: dict | None = None,
) -> RepoStatus:
    return RepoStatus(
        name=name,
        owner="reneeqian",
        repo_type="code",
        visibility="public",
        description="A test repo",
        local_branch="dev",
        auto_merge=auto_merge,
        delete_on_merge=True,
        has_codeowners=True,
        workflows=workflows if workflows is not None else ["forge-health.yml", "auto-merge.yml"],
        forge_health_grade=grade,
        forge_health_score=0.90 if grade == "A" else None,
        forge_health_collectors=forge_health_collectors or {},
        issues=issues or [],
    )


def _docs_repo(
    name: str = "SaMD-DHF-Templates",
    workflows: list[str] | None = None,
    issues: list[str] | None = None,
) -> RepoStatus:
    return RepoStatus(
        name=name,
        owner="reneeqian",
        repo_type="docs",
        visibility="public",
        description="A docs repo",
        local_branch="dev",
        auto_merge=True,
        delete_on_merge=True,
        has_codeowners=True,
        workflows=workflows if workflows is not None else ["forge-health.yml", "auto-merge.yml"],
        forge_health_grade=None,
        issues=issues or [],
    )


def _report(*repos: RepoStatus) -> WorkspaceStatusReport:
    return WorkspaceStatusReport(repos=list(repos))


# ── Markdown output tests ──────────────────────────────────────────────────────


class TestWorkspaceReporterMarkdown:
    def test_markdown_contains_all_repo_names(self):
        report = _report(_code_repo("repo_a"), _code_repo("repo_b"))
        md = WorkspaceReporter(report).to_markdown()
        assert "repo_a" in md
        assert "repo_b" in md

    def test_markdown_overview_table_has_header_row(self):
        report = _report(_code_repo())
        md = WorkspaceReporter(report).to_markdown()
        assert "Repo" in md
        assert "Visibility" in md

    def test_markdown_shows_checkmark_for_auto_merge_on(self):
        report = _report(_code_repo(auto_merge=True))
        md = WorkspaceReporter(report).to_markdown()
        assert "✅" in md

    def test_markdown_shows_warning_for_auto_merge_off(self):
        report = _report(_code_repo(auto_merge=False))
        md = WorkspaceReporter(report).to_markdown()
        assert "❌" in md

    def test_markdown_shows_checkmark_for_workflow_present(self):
        report = _report(_code_repo(workflows=["forge-health.yml"]))
        md = WorkspaceReporter(report).to_markdown()
        assert "✅" in md

    def test_markdown_shows_cross_for_missing_workflow(self):
        report = _report(_code_repo(workflows=[]))
        md = WorkspaceReporter(report).to_markdown()
        assert "❌" in md

    def test_markdown_shows_na_for_docs_repo_code_workflow(self):
        report = _report(_docs_repo())
        md = WorkspaceReporter(report).to_markdown()
        assert "n/a" in md.lower() or "N/A" in md

    def test_markdown_shows_grade_for_code_repo(self):
        report = _report(_code_repo(grade="B"))
        md = WorkspaceReporter(report).to_markdown()
        assert "B" in md

    def test_markdown_shows_none_or_dash_for_docs_repo_health(self):
        report = _report(_docs_repo())
        md = WorkspaceReporter(report).to_markdown()
        # docs repos have no health grade — should show — or n/a, not a letter grade
        assert "—" in md or "n/a" in md.lower() or "N/A" in md

    def test_markdown_cleanup_section_with_issues(self):
        repo = _code_repo(issues=["auto-merge is disabled", "CODEOWNERS file missing"])
        report = _report(repo)
        md = WorkspaceReporter(report).to_markdown()
        assert "auto-merge" in md
        assert "CODEOWNERS" in md

    def test_markdown_cleanup_empty_when_no_issues(self):
        report = _report(_code_repo(issues=[]))
        md = WorkspaceReporter(report).to_markdown()
        # Should contain a section indicating no issues, or just omit the cleanup table
        assert "my_repo" in md

    def test_empty_workspace_renders_without_error(self):
        report = WorkspaceStatusReport()
        md = WorkspaceReporter(report).to_markdown()
        assert isinstance(md, str)

    def test_markdown_has_generated_at_timestamp(self):
        report = _report(_code_repo())
        md = WorkspaceReporter(report).to_markdown()
        assert str(report.generated_at.year) in md

    def test_markdown_ci_workflow_section_present(self):
        report = _report(_code_repo())
        md = WorkspaceReporter(report).to_markdown()
        assert "forge-health" in md.lower() or "workflow" in md.lower() or "CI" in md

    def test_markdown_settings_section_present(self):
        report = _report(_code_repo())
        md = WorkspaceReporter(report).to_markdown()
        # Should have a repo-level settings section with auto-merge column
        assert "Auto" in md or "auto" in md


# ── Terminal rendering smoke test ─────────────────────────────────────────────


    def test_markdown_health_table_shows_collector_columns(self):
        report = _report(_code_repo())
        md = WorkspaceReporter(report).to_markdown()
        assert "Tests" in md
        assert "Static" in md
        assert "Req Cov" in md

    def test_markdown_health_table_shows_collector_scores(self):
        collectors = {"test_metrics": 0.90, "static_analysis": 0.75}
        report = _report(_code_repo(forge_health_collectors=collectors))
        md = WorkspaceReporter(report).to_markdown()
        assert "90%" in md
        assert "75%" in md

    def test_markdown_health_table_shows_dash_for_missing_collector(self):
        report = _report(_code_repo(forge_health_collectors={}))
        md = WorkspaceReporter(report).to_markdown()
        assert "—" in md

    def test_markdown_health_table_omits_mutation_column_when_no_data(self):
        report = _report(_code_repo(forge_health_collectors={}))
        md = WorkspaceReporter(report).to_markdown()
        assert "Mutation" not in md

    def test_markdown_health_table_includes_mutation_column_when_data_present(self):
        collectors = {"mutation_testing": 0.80}
        report = _report(_code_repo(forge_health_collectors=collectors))
        md = WorkspaceReporter(report).to_markdown()
        assert "Mutation" in md

    def test_markdown_health_section_renamed_to_health_details(self):
        report = _report(_code_repo())
        md = WorkspaceReporter(report).to_markdown()
        assert "## Health Details" in md

    def test_markdown_health_table_shows_overall_score(self):
        report = _report(_code_repo(grade="A"))
        md = WorkspaceReporter(report).to_markdown()
        assert "Score" in md


class TestWorkspaceReporterTerminal:
    def test_print_terminal_does_not_raise(self):
        report = _report(_code_repo(), _docs_repo())
        reporter = WorkspaceReporter(report)
        console = Console(record=True)
        reporter.print_terminal(console=console)
        output = console.export_text()
        assert len(output) > 0

    def test_terminal_renders_with_collector_data(self):
        collectors = {
            "test_metrics": 0.95, "complexity": 0.80,
            "dependency_health": 1.0, "requirements_coverage": 0.70,
            "static_analysis": 0.90, "type_coverage": 0.85,
            "dead_code": 0.60,
        }
        report = _report(_code_repo(forge_health_collectors=collectors))
        reporter = WorkspaceReporter(report)
        console = Console(record=True)
        reporter.print_terminal(console=console)
        output = console.export_text()
        assert "Health Details" in output
        assert "95%" in output
