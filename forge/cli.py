"""Forge CLI — CLI-001, CLI-002.

Entry point: `forge`
Commands:
  forge health <path>   — run all collectors and print a report
  forge new <name>      — scaffold a new project
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from forge.aggregator import Aggregator
from forge.models import CollectorResult, ProjectHealthReport
from forge.scaffolder.engine import ScaffoldConfig, ScaffoldEngine
from forge.scaffolder.github_setup import GitHubConfig

app = typer.Typer(
    name="forge",
    help="Personal project automation toolkit.",
    add_completion=False,
    pretty_exceptions_show_locals=False,
)
console = Console()


# ── forge health ─────────────────────────────────────────────────────────────


@app.command()
def health(
    path: Path = typer.Argument(
        default=Path("."),
        help="Path to the project to analyse. Defaults to current directory.",
        show_default=True,
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Write full JSON report to this file path.",
    ),
    json_stdout: bool = typer.Option(
        False,
        "--json",
        help="Print raw JSON to stdout instead of the formatted table.",
    ),
    python: Optional[str] = typer.Option(
        None,
        "--python", "-P",
        help="Python interpreter to use for running tests (e.g. path to a conda env's python).",
    ),
) -> None:
    """Run a full health check on a project. CLI-001"""
    path = path.resolve()

    if not path.exists():
        console.print(f"[red]✗[/red] Path not found: {path}")
        raise typer.Exit(1)

    with console.status(f"[bold cyan]Analysing {path.name}…[/bold cyan]"):
        aggregator = Aggregator()
        report = aggregator.run(path, python_executable=python or "")

    if json_stdout:
        print(report.model_dump_json(indent=2))
        return

    _print_report(report)

    if output:
        output.write_text(report.model_dump_json(indent=2))
        console.print(f"\n[dim]Report written to {output}[/dim]")


# ── forge new ────────────────────────────────────────────────────────────────


@app.command()
def new(
    name: str = typer.Argument(..., help="Project name (will become the directory name)."),
    destination: Path = typer.Option(
        Path("."),
        "--dest", "-d",
        help="Parent directory where the project folder will be created.",
    ),
    python_version: str = typer.Option("3.11", "--python", "-p", help="Python version."),
    license_type: str = typer.Option("MIT", "--license", "-l", help="License type."),
    author: str = typer.Option("", "--author", "-a", help="Author name."),
    no_git: bool = typer.Option(False, "--no-git", help="Skip git init."),
    github: bool = typer.Option(False, "--github", "-g", help="Create GitHub repo with branch policy (requires gh CLI)."),
    private: bool = typer.Option(False, "--private", help="Make the GitHub repo private."),
    description: str = typer.Option("", "--description", help="GitHub repo description."),
) -> None:
    """Scaffold a new project with standard structure. CLI-002"""
    dest = destination.resolve() / name

    if dest.exists():
        console.print(f"[red]✗[/red] Directory already exists: {dest}")
        raise typer.Exit(1)

    config = ScaffoldConfig(
        project_name=name,
        destination=dest,
        python_version=python_version,
        license_type=license_type,
        author=author,
        git_init=not no_git,
        github=GitHubConfig(create_repo=True, private=private, description=description) if github else None,
    )

    with console.status(f"[bold cyan]Creating {name}…[/bold cyan]"):
        engine = ScaffoldEngine()
        result = engine.create(config)

    console.print(f"\n[bold green]✓[/bold green] Project created at [cyan]{dest}[/cyan]\n")

    if result.github is not None:
        if result.github.ok:
            console.print(f"[bold green]✓[/bold green] GitHub repo ready: [cyan]{result.github.repo_url}[/cyan]")
            console.print("  [dim]main[/dim] — PR required (ruleset active)")
            console.print("  [dim]dev[/dim]  — direct pushes allowed\n")
        else:
            for err in result.github.errors:
                console.print(f"[yellow]⚠[/yellow]  GitHub setup: {err}")

    tree_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    tree_table.add_column(style="dim")
    for f in result.created_files[:20]:
        tree_table.add_row(str(f.relative_to(dest)))
    if len(result.created_files) > 20:
        tree_table.add_row(f"… and {len(result.created_files) - 20} more files")

    console.print(Panel(tree_table, title=f"[bold]{name}/[/bold]", border_style="cyan"))

    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  cd {dest}")
    console.print("  conda env create -f environment.yaml")
    console.print(f"  conda activate {name}")
    console.print("  pip install -e '.[dev]'")
    console.print("  forge health .\n")


# ── report rendering ──────────────────────────────────────────────────────────


def _print_report(report: ProjectHealthReport) -> None:
    """Render a ProjectHealthReport to the terminal using Rich."""
    grade_colour = {
        "A": "bold green", "B": "green", "C": "yellow",
        "D": "red", "F": "bold red", "N/A": "dim",
    }.get(report.grade, "white")

    score_str = (
        f"{report.overall_score:.1%}" if report.overall_score is not None else "N/A"
    )

    console.print()
    console.print(
        Panel(
            f"[bold]{report.project_name}[/bold]  "
            f"[{grade_colour}]{report.grade}  {score_str}[/{grade_colour}]\n"
            f"[dim]{report.project_path}[/dim]",
            title="[bold cyan]forge health[/bold cyan]",
            border_style="cyan",
        )
    )

    table = Table(box=box.SIMPLE_HEAD, show_header=True, padding=(0, 2))
    table.add_column("Collector", style="bold")
    table.add_column("Score", justify="right")
    table.add_column("Details")
    table.add_column("Status", justify="center")

    collectors: list[tuple[str, CollectorResult]] = [
        ("Test Metrics", report.test_metrics),
        ("Complexity", report.complexity),
        ("Dep. Health", report.dependency_health),
        ("Req. Coverage", report.requirements_coverage),
        ("Static Analysis", report.static_analysis),
        ("Type Coverage", report.type_coverage),
        ("Dead Code", report.dead_code),
        ("Mutation Testing", report.mutation_testing),
    ]

    for label, result in collectors:
        if result.skipped:
            table.add_row(label, "[dim]—[/dim]", f"[dim]{result.skip_reason}[/dim]", "⏭")
            continue

        score_val = result.score
        score_display = f"{score_val:.1%}" if score_val is not None else "—"
        score_colour = _score_colour(score_val)

        detail = _collector_detail(result)
        status = "✓" if score_val is not None and score_val >= 0.7 else "✗"
        status_colour = "green" if status == "✓" else "red"

        table.add_row(
            label,
            f"[{score_colour}]{score_display}[/{score_colour}]",
            detail,
            f"[{status_colour}]{status}[/{status_colour}]",
        )

    console.print(table)
    console.print(f"[dim]Generated {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}[/dim]\n")


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


def _collector_detail(result: CollectorResult) -> str:
    """One-line human summary for each collector type."""
    from forge.models import (
        ComplexityResult,
        DeadCodeResult,
        DependencyHealthResult,
        MutationTestingResult,
        RequirementsCoverageResult,
        StaticAnalysisResult,
        TestMetricsResult,
        TypeCoverageResult,
    )

    if isinstance(result, TestMetricsResult):
        if result.details.get("coverage_only"):
            cov = f"{result.line_coverage:.1f}%" if result.line_coverage is not None else "N/A"
            return f"coverage {cov} (coverage-only mode)"
        cov = f", coverage {result.line_coverage:.1f}%" if result.line_coverage is not None else ""
        return f"{result.passed}/{result.total} tests passed{cov}"

    if isinstance(result, ComplexityResult):
        parts = []
        if result.avg_cyclomatic is not None:
            parts.append(f"cyclomatic CC: {result.avg_cyclomatic:.1f}")
        if result.maintainability_index is not None:
            parts.append(f"MI: {result.maintainability_index:.1f}")
        return ", ".join(parts) or "—"

    if isinstance(result, DependencyHealthResult):
        if result.vulnerable_packages == 0:
            return f"{result.total_packages} packages, no CVEs"
        return f"{result.vulnerable_packages} vulnerable / {result.total_packages} packages"

    if isinstance(result, RequirementsCoverageResult):
        return (
            f"{result.covered_requirements}/{result.total_requirements} requirements covered"
        )

    if isinstance(result, StaticAnalysisResult):
        if result.error_density is not None:
            return f"{result.total_errors} errors, {result.error_density:.1f}/1k lines"
        return f"{result.total_errors} errors"

    if isinstance(result, TypeCoverageResult):
        detail = f"{result.total_errors} mypy errors"
        if result.files_checked:
            detail += f" ({result.files_checked} files)"
        return detail

    if isinstance(result, DeadCodeResult):
        if result.unused_density is not None:
            return f"{result.unused_items} unused items, {result.unused_density:.1f}/1k lines"
        return f"{result.unused_items} unused items"

    if isinstance(result, MutationTestingResult):
        if result.total_mutants == 0:
            return "no mutants generated"
        pct = (result.killed_mutants / result.total_mutants) * 100
        return (
            f"{result.killed_mutants}/{result.total_mutants} mutants killed ({pct:.0f}%)"
        )

    return str(result.details) if result.details else "—"


if __name__ == "__main__":
    app()
