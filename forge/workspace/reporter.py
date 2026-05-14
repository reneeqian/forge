"""WorkspaceReporter — Rich terminal and markdown output for workspace status. REQ-018"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from forge.models import RepoStatus, WorkspaceStatusReport

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


_SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def _branch_col(repo: RepoStatus) -> str:
    name = repo.local_branch or _DASH
    parts = []
    if repo.branch_count is not None:
        parts.append(f"{repo.branch_count} br")
    if repo.stale_branches:
        parts.append(f"{len(repo.stale_branches)} stale")
    n_sync = len(repo.branches_behind) + len(repo.branches_diverged)
    if n_sync:
        parts.append(f"{n_sync} behind")
    return f"{name} ({', '.join(parts)})" if parts else name


def _yn(value: bool) -> str:
    return _CHECK if value else _CROSS


def _wf(present: bool, applicable: bool) -> str:
    if not applicable:
        return _NA
    return _CHECK if present else _CROSS


def _ci_colour(passed: int | None, total: int | None) -> str:
    if passed is None or total is None or total == 0:
        return "dim"
    if passed == total:
        return "green"
    if passed == 0:
        return "red"
    return "yellow"


def _ci_text(passed: int | None, total: int | None) -> str:
    if passed is None or total is None:
        return _DASH
    return f"{passed}/{total}"


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
        lines += self._md_project_details()

        return "\n".join(lines)

    def print_terminal(self, console: Console | None = None) -> None:
        con = console or Console()
        r = self._report
        con.print(f"\n[bold]Workspace Status Report[/bold]  ({r.generated_at.strftime('%Y-%m-%d %H:%M UTC')})\n")
        self._rich_overview_table(con)
        self._rich_settings_table(con)
        self._rich_ci_table(con)
        self._rich_health_table(con)
        self._rich_project_details(con)

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
        lines.append("| Repo | Type | Visibility | Local Branch | CI | PR | Description |")
        lines.append("|---|---|---|---|:---:|:---:|---|")
        for repo in self._report.repos:
            branch = _branch_col(repo)
            desc = repo.description or _DASH
            ci = _ci_text(repo.branch_ci_passed, repo.branch_ci_total)
            pr = f"[#{repo.open_pr_number}]({repo.open_pr_url})" if repo.open_pr_number else _DASH
            lines.append(
                f"| `{repo.name}` | {repo.repo_type} | {repo.visibility} "
                f"| {branch} | {ci} | {pr} | {desc} |"
            )
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

    def _build_project_issues(
        self, repo: RepoStatus
    ) -> list[tuple[str, str, str | None]]:
        issues: list[tuple[str, str, str | None]] = []

        if repo.collection_error:
            issues.append(("CRITICAL", f"collection error: {repo.collection_error}", None))

        if repo.last_ci_conclusion == "failure":
            issues.append(("CRITICAL", "CI: last forge-health run failed", repo.last_ci_run_url))

        for b in repo.branches_diverged:
            issues.append(("CRITICAL", f"Diverged branch: {b}", None))

        for b in repo.stale_branches:
            issues.append(("WARNING", f"Stale branch: {b} (merged — safe to delete)", None))

        low_collectors = [
            (label, v)
            for key, label in _COLLECTOR_LABELS
            if (v := repo.forge_health_collectors.get(key)) is not None and v < 0.70
        ]
        for label, v in sorted(low_collectors, key=lambda x: x[1]):
            issues.append(("WARNING", f"{label}: {v:.0%}", None))

        for msg in repo.issues:
            issues.append(("INFO", msg, None))

        for b in repo.branches_behind:
            issues.append(("INFO", f"Branch behind remote: {b}", None))

        return sorted(issues, key=lambda x: _SEVERITY_ORDER.get(x[0], 99))

    def _md_project_details(self) -> list[str]:
        lines = ["## Project Details", ""]
        any_issues = False
        for repo in self._report.repos:
            issues = self._build_project_issues(repo)
            if not issues:
                continue
            any_issues = True
            grade = repo.forge_health_grade or _DASH
            score_str = f"{repo.forge_health_score:.0%}" if repo.forge_health_score is not None else _DASH
            lines.append(f"### `{repo.name}`  ·  Grade {grade}  ·  {score_str}")
            lines.append("")
            for sev, msg, url in issues:
                display = f"[{msg}]({url})" if url else msg
                lines.append(f"- **{sev}**: {display}")
            lines.append("")
        if not any_issues:
            lines.append("All repos are healthy — no issues detected.")
            lines.append("")
        lines.append(
            "*Note: stale branch detection uses `git branch --merged`"
            " — squash-merged branches may not appear.*"
        )
        return lines

    # ── rich terminal sections ────────────────────────────────────────────────

    def _rich_overview_table(self, con: Console) -> None:
        t = Table(title="Repository Overview", show_lines=False)
        for col in ("Repo", "Type", "Visibility", "Branch", "CI", "PR", "Description"):
            t.add_column(col)
        t.columns[4].justify = "center"
        t.columns[5].justify = "center"
        for repo in self._report.repos:
            ci_txt = _ci_text(repo.branch_ci_passed, repo.branch_ci_total)
            ci_col = _ci_colour(repo.branch_ci_passed, repo.branch_ci_total)
            pr_txt = f"#{repo.open_pr_number}" if repo.open_pr_number else _DASH
            t.add_row(
                repo.name,
                repo.repo_type,
                repo.visibility,
                _branch_col(repo),
                f"[{ci_col}]{ci_txt}[/{ci_col}]",
                pr_txt,
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

    def _rich_project_details(self, con: Console) -> None:
        _SEV_STYLE: dict[str, str] = {"CRITICAL": "bold red", "WARNING": "yellow", "INFO": "dim"}
        any_issues = False
        for repo in self._report.repos:
            issues = self._build_project_issues(repo)
            if not issues:
                continue
            any_issues = True
            grade = repo.forge_health_grade or _DASH
            gc = _grade_colour(repo.forge_health_grade)
            score_str = (
                f"{repo.forge_health_score:.0%}" if repo.forge_health_score is not None else _DASH
            )
            con.print(f"\n[bold]{repo.name}[/bold]  [{gc}]{grade}[/{gc}]  {score_str}")
            for sev, msg, _url in issues:
                style = _SEV_STYLE.get(sev, "")
                con.print(f"  [{style}]{sev:8}[/{style}]  {msg}")
        if not any_issues:
            con.print("\n[green]All repos are healthy — no issues detected.[/green]")
        con.print(
            "\n[dim]Note: stale detection uses git branch --merged;"
            " squash-merged branches may not appear.[/dim]"
        )
