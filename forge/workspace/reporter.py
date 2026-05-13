"""WorkspaceReporter — Rich terminal and markdown output for workspace status. REQ-018"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from forge.models import WorkspaceStatusReport

_CHECK = "✅"
_CROSS = "❌"
_NA = "N/A"
_DASH = "—"

# Workflows shown in the CI inventory table
_CODE_WORKFLOWS = ["forge-health.yml", "auto-merge.yml", "codeql.yml", "dependency-review.yml", "pip-audit.yml"]
_DOC_WORKFLOWS = ["forge-health.yml", "auto-merge.yml"]

_COLLECTOR_LABELS = [
    ("test_metrics",          "Tests"),
    ("complexity",            "Complex."),
    ("dependency_health",     "Dep Health"),
    ("requirements_coverage", "Req Cov"),
    ("static_analysis",       "Static"),
    ("type_coverage",         "Type"),
    ("dead_code",             "Dead Code"),
    ("mutation_testing",      "Mutation"),
]


def _yn(value: bool) -> str:
    return _CHECK if value else _CROSS


def _wf(present: bool, applicable: bool) -> str:
    if not applicable:
        return _NA
    return _CHECK if present else _CROSS


def _score_colour(score: float | None) -> str:
    if score is None:
        return "dim"
    if score >= 0.9:
        return "bold green"
    if score >= 0.7:
        return "green"
    if score >= 0.5:
        return "yellow"
    return "red"


def _grade_colour(grade: str | None) -> str:
    return {
        "A": "bold green", "B": "green", "C": "yellow",
        "D": "red", "F": "bold red",
    }.get(grade or "", "dim")


class WorkspaceReporter:
    def __init__(self, report: WorkspaceStatusReport) -> None:
        self._report = report

    # ── public ────────────────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        r = self._report
        lines: list[str] = []

        lines.append("# Workspace Status Report")
        lines.append(f"*Generated {r.generated_at.strftime('%Y-%m-%d %H:%M UTC')}*")
        lines.append("")
        lines.append("---")
        lines.append("")

        lines += self._md_overview_table()
        lines.append("")
        lines += self._md_settings_table()
        lines.append("")
        lines += self._md_ci_table()
        lines.append("")
        lines += self._md_health_table()
        lines.append("")
        lines += self._md_cleanup_section()

        return "\n".join(lines)

    def print_terminal(self, console: Console | None = None) -> None:
        con = console or Console()
        r = self._report
        con.print(f"\n[bold]Workspace Status Report[/bold]  ({r.generated_at.strftime('%Y-%m-%d %H:%M UTC')})\n")
        self._rich_overview_table(con)
        self._rich_settings_table(con)
        self._rich_ci_table(con)
        self._rich_health_table(con)
        self._rich_cleanup_section(con)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _active_collectors(self) -> list[tuple[str, str]]:
        """Return collector (key, label) pairs, omitting Mutation if no repo has data."""
        return [
            (key, label)
            for key, label in _COLLECTOR_LABELS
            if key != "mutation_testing" or any(
                repo.forge_health_collectors.get(key) is not None
                for repo in self._report.repos
            )
        ]

    # ── markdown sections ─────────────────────────────────────────────────────

    def _md_overview_table(self) -> list[str]:
        lines = ["## Repository Overview", ""]
        lines.append("| Repo | Type | Visibility | Local Branch | Description |")
        lines.append("|---|---|---|---|---|")
        for repo in self._report.repos:
            branch = repo.local_branch or _DASH
            desc = repo.description or _DASH
            lines.append(f"| `{repo.name}` | {repo.repo_type} | {repo.visibility} | {branch} | {desc} |")
        return lines

    def _md_settings_table(self) -> list[str]:
        lines = ["## Repo-Level Settings", ""]
        lines.append("| Repo | Auto-merge | Delete on merge | Rebase | CODEOWNERS | Dependabot |")
        lines.append("|---|:---:|:---:|:---:|:---:|:---:|")
        for repo in self._report.repos:
            lines.append(
                f"| `{repo.name}` "
                f"| {_yn(repo.auto_merge)} "
                f"| {_yn(repo.delete_on_merge)} "
                f"| {_yn(repo.rebase_allowed)} "
                f"| {_yn(repo.has_codeowners)} "
                f"| {_yn(repo.has_dependabot)} |"
            )
        return lines

    def _md_ci_table(self) -> list[str]:
        lines = ["## CI/CD Workflows", ""]
        headers = ["Repo", "forge-health", "auto-merge", "codeql", "dependency-review", "pip-audit"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|---" + "|:---:" * (len(headers) - 1) + "|")
        for repo in self._report.repos:
            is_code = repo.repo_type == "code"
            wfs = set(repo.workflows)
            row = [
                f"`{repo.name}`",
                _wf("forge-health.yml" in wfs, True),
                _wf("auto-merge.yml" in wfs, True),
                _wf("codeql.yml" in wfs, is_code),
                _wf("dependency-review.yml" in wfs, is_code),
                _wf("pip-audit.yml" in wfs, is_code),
            ]
            lines.append("| " + " | ".join(row) + " |")
        return lines

    def _md_health_table(self) -> list[str]:
        active = self._active_collectors()
        lines = ["## Health Details", ""]
        headers = ["Repo", "Grade", "Score"] + [label for _, label in active] + ["Last CI"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|---" + "|:---:" * (len(headers) - 1) + "|")
        for repo in self._report.repos:
            grade = repo.forge_health_grade or _DASH
            score = repo.forge_health_score
            score_str = f"{score:.0%}" if score is not None else _DASH
            collector_cells = []
            for key, _ in active:
                cv = repo.forge_health_collectors.get(key)
                collector_cells.append(f"{cv:.0%}" if cv is not None else _DASH)
            ci = repo.last_ci_conclusion or _DASH
            row = [f"`{repo.name}`", grade, score_str] + collector_cells + [ci]
            lines.append("| " + " | ".join(row) + " |")
        return lines

    def _md_cleanup_section(self) -> list[str]:
        lines = ["## Recommended Cleanup", ""]
        repos_with_issues = [r for r in self._report.repos if r.issues or r.collection_error]

        if not repos_with_issues:
            lines.append("No issues detected.")
            return lines

        n = 1
        lines.append("| # | Repo | Issue |")
        lines.append("|---|---|---|")
        for repo in repos_with_issues:
            if repo.collection_error:
                lines.append(f"| {n} | `{repo.name}` | collection error: {repo.collection_error} |")
                n += 1
            for issue in repo.issues:
                lines.append(f"| {n} | `{repo.name}` | {issue} |")
                n += 1
        return lines

    # ── rich terminal sections ────────────────────────────────────────────────

    def _rich_overview_table(self, con: Console) -> None:
        t = Table(title="Repository Overview", show_lines=False)
        for col in ("Repo", "Type", "Visibility", "Branch", "Description"):
            t.add_column(col)
        for repo in self._report.repos:
            t.add_row(
                repo.name,
                repo.repo_type,
                repo.visibility,
                repo.local_branch or _DASH,
                repo.description or _DASH,
            )
        con.print(t)

    def _rich_settings_table(self, con: Console) -> None:
        t = Table(title="Repo-Level Settings", show_lines=False)
        for col in ("Repo", "Auto-merge", "Del-on-merge", "Rebase", "CODEOWNERS", "Dependabot"):
            t.add_column(col, justify="center")
        t.columns[0].justify = "left"
        for repo in self._report.repos:
            t.add_row(
                repo.name,
                _yn(repo.auto_merge),
                _yn(repo.delete_on_merge),
                _yn(repo.rebase_allowed),
                _yn(repo.has_codeowners),
                _yn(repo.has_dependabot),
            )
        con.print(t)

    def _rich_ci_table(self, con: Console) -> None:
        t = Table(title="CI/CD Workflows", show_lines=False)
        t.add_column("Repo")
        for wf in ("forge-health", "auto-merge", "codeql", "dep-review", "pip-audit"):
            t.add_column(wf, justify="center")
        for repo in self._report.repos:
            is_code = repo.repo_type == "code"
            wfs = set(repo.workflows)
            t.add_row(
                repo.name,
                _wf("forge-health.yml" in wfs, True),
                _wf("auto-merge.yml" in wfs, True),
                _wf("codeql.yml" in wfs, is_code),
                _wf("dependency-review.yml" in wfs, is_code),
                _wf("pip-audit.yml" in wfs, is_code),
            )
        con.print(t)

    def _rich_health_table(self, con: Console) -> None:
        active = self._active_collectors()
        t = Table(title="Health Details", show_lines=False)
        t.add_column("Repo")
        t.add_column("Grade", justify="center")
        t.add_column("Score", justify="right")
        for _, label in active:
            t.add_column(label, justify="right")
        t.add_column("Last CI", justify="center")
        for repo in self._report.repos:
            grade = repo.forge_health_grade or _DASH
            gc = _grade_colour(repo.forge_health_grade)
            score = repo.forge_health_score
            score_str = f"{score:.0%}" if score is not None else _DASH
            sc = _score_colour(score)
            collector_cells = []
            for key, _ in active:
                cv = repo.forge_health_collectors.get(key)
                cv_str = f"{cv:.0%}" if cv is not None else _DASH
                cc = _score_colour(cv)
                collector_cells.append(f"[{cc}]{cv_str}[/{cc}]")
            ci = repo.last_ci_conclusion or _DASH
            t.add_row(
                repo.name,
                f"[{gc}]{grade}[/{gc}]",
                f"[{sc}]{score_str}[/{sc}]",
                *collector_cells,
                ci,
            )
        con.print(t)

    def _rich_cleanup_section(self, con: Console) -> None:
        repos_with_issues = [r for r in self._report.repos if r.issues or r.collection_error]
        if not repos_with_issues:
            con.print("\n[green]No issues detected.[/green]")
            return

        t = Table(title="Recommended Cleanup", show_lines=True)
        t.add_column("#", justify="right")
        t.add_column("Repo")
        t.add_column("Issue")
        n = 1
        for repo in repos_with_issues:
            if repo.collection_error:
                t.add_row(str(n), repo.name, f"collection error: {repo.collection_error}")
                n += 1
            for issue in repo.issues:
                t.add_row(str(n), repo.name, issue)
                n += 1
        con.print(t)
