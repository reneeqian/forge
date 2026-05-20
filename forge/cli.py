"""Forge CLI — CLI-001, CLI-002, CLI-003, WRK-001, WRK-005.

Entry point: `forge`
Commands:
  forge health <path>         — run all collectors and print a report
  forge new <name>            — scaffold a new project
  forge workspace <toml>      — workspace-wide infrastructure status report
  forge dashboard [path]      — interactive env picker + health report
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click
import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from forge.aggregator import Aggregator
from forge.config import load_config
from forge.env_discovery import default_index, discover_envs, resolve_env
from forge.models import (
    CollectorResult,
    ComplexityResult,
    DeadCodeResult,
    DependencyHealthResult,
    MutationTestingResult,
    ProjectHealthReport,
    RequirementsCoverageResult,
    StaticAnalysisResult,
    TestMetricsResult,
    TypeCoverageResult,
)
from forge.scaffolder.engine import ScaffoldConfig, ScaffoldEngine
from forge.scaffolder.github_setup import GitHubConfig
from forge.workspace.collector import WorkspaceCollector
from forge.workspace.config import WorkspaceConfig
from forge.workspace.reporter import WorkspaceReporter


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
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Write full JSON report to this file path.",
    ),
    json_stdout: bool = typer.Option(
        False,
        "--json",
        help="Print raw JSON to stdout instead of the formatted table.",
    ),
    python: str | None = typer.Option(
        None,
        "--python", "-P",
        help="Python interpreter to use for running tests (e.g. path to a conda env's python).",
    ),
    save_artifact: bool = typer.Option(
        False,
        "--save-artifact",
        help="Save timestamped JSON report to <project>/artifacts/health_runs/<timestamp>/health_report.json.",
    ),
) -> None:
    """Run a full health check on a project. CLI-001, CLI-003"""
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

    if save_artifact:
        import datetime as _dt
        ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S_%f")  # noqa: UP017
        artifact_dir = path / "artifacts" / "health_runs" / ts
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_file = artifact_dir / "health_report.json"
        artifact_file.write_text(report.model_dump_json(indent=2))
        console.print(f"[dim]Artifact saved to {artifact_file}[/dim]")


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


def _fmt_test_metrics(r: TestMetricsResult) -> str:
    if r.details.get("coverage_only"):
        cov = f"{r.line_coverage:.1f}%" if r.line_coverage is not None else "N/A"
        return f"coverage {cov} (coverage-only mode)"
    cov = f", coverage {r.line_coverage:.1f}%" if r.line_coverage is not None else ""
    return f"{r.passed}/{r.total} tests passed{cov}"


def _fmt_complexity(r: ComplexityResult) -> str:
    parts = []
    if r.avg_cyclomatic is not None:
        parts.append(f"cyclomatic CC: {r.avg_cyclomatic:.1f}")
    if r.maintainability_index is not None:
        parts.append(f"MI: {r.maintainability_index:.1f}")
    return ", ".join(parts) or "—"


def _fmt_dependency_health(r: DependencyHealthResult) -> str:
    if r.vulnerable_packages == 0:
        return f"{r.total_packages} packages, no CVEs"
    return f"{r.vulnerable_packages} vulnerable / {r.total_packages} packages"


def _fmt_requirements_coverage(r: RequirementsCoverageResult) -> str:
    return f"{r.covered_requirements}/{r.total_requirements} requirements covered"


def _fmt_static_analysis(r: StaticAnalysisResult) -> str:
    parts = []
    if r.safe_errors:
        parts.append(f"{r.safe_errors} safe")
    if r.unsafe_errors:
        parts.append(f"{r.unsafe_errors} unsafe")
    if r.manual_errors:
        parts.append(f"{r.manual_errors} manual")
    breakdown = f" ({' · '.join(parts)})" if parts else ""
    if r.error_density is not None:
        return f"{r.total_errors} errors{breakdown}, {r.error_density:.1f}/1k lines (weighted)"
    return f"{r.total_errors} errors{breakdown}"


def _fmt_type_coverage(r: TypeCoverageResult) -> str:
    detail = f"{r.total_errors} mypy errors"
    if r.files_checked:
        detail += f" ({r.files_checked} files)"
    return detail


def _fmt_dead_code(r: DeadCodeResult) -> str:
    if r.unused_density is not None:
        return f"{r.unused_items} unused items, {r.unused_density:.1f}/1k lines"
    return f"{r.unused_items} unused items"


def _fmt_mutation_testing(r: MutationTestingResult) -> str:
    if r.total_mutants == 0:
        return "no mutants generated"
    pct = (r.killed_mutants / r.total_mutants) * 100
    return f"{r.killed_mutants}/{r.total_mutants} mutants killed ({pct:.0f}%)"


_DETAIL_FORMATTERS: dict[type, object] = {
    TestMetricsResult: _fmt_test_metrics,
    ComplexityResult: _fmt_complexity,
    DependencyHealthResult: _fmt_dependency_health,
    RequirementsCoverageResult: _fmt_requirements_coverage,
    StaticAnalysisResult: _fmt_static_analysis,
    TypeCoverageResult: _fmt_type_coverage,
    DeadCodeResult: _fmt_dead_code,
    MutationTestingResult: _fmt_mutation_testing,
}


def _collector_detail(result: CollectorResult) -> str:
    formatter = _DETAIL_FORMATTERS.get(type(result))
    if formatter is None:
        return str(result.details) if result.details else "—"
    return formatter(result)  # type: ignore[operator]


# ── forge workspace ───────────────────────────────────────────────────────────


def _auto_output_path(directory: Path, config_path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return directory / f"{ts}-{config_path.stem}-status-report.md"


@app.command()
def workspace(
    config: Path = typer.Argument(
        default=Path("workspace.toml"),
        help="Path to workspace.toml config file.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help=(
            "Write markdown report to FILE. "
            "Pass a directory (e.g. -o .) to auto-generate a timestamped filename inside it."
        ),
    ),
    markdown: bool = typer.Option(
        False,
        "--markdown",
        help="Print markdown to stdout instead of Rich terminal tables.",
    ),
    no_health: bool = typer.Option(
        False,
        "--no-health",
        help="Skip forge health collection (faster, omits grade column).",
    ),
    preview: bool = typer.Option(
        False,
        "--preview", "-p",
        help="Open the written report in the system default viewer after saving (requires -o).",
    ),
) -> None:
    """Generate a workspace-wide infrastructure status report. REQ-018"""
    try:
        cfg = WorkspaceConfig.load(config)
    except FileNotFoundError:
        console.print(f"[red]Config not found:[/red] {config}")
        raise typer.Exit(1) from None

    report = WorkspaceCollector(cfg).collect_all(run_health=not no_health)
    reporter = WorkspaceReporter(report)

    if output is not None:
        out_path = _auto_output_path(output, config) if output.is_dir() else output
        out_path.write_text(reporter.to_markdown())
        console.print(f"[green]Report written to[/green] {out_path}")
        if preview:
            click.launch(str(out_path))
        return

    if preview:
        console.print("[yellow]--preview requires --output (-o)[/yellow]")

    if markdown:
        typer.echo(reporter.to_markdown())
        return

    reporter.print_terminal(console=console)


# ── forge dashboard ───────────────────────────────────────────────────────────


@app.command()
def dashboard(
    path: Path = typer.Argument(
        default=Path("."),
        help="Path to the project to analyse. Defaults to current directory.",
        show_default=True,
    ),
    env: str | None = typer.Option(
        None,
        "--env", "-e",
        help="Environment name or python path to use directly (skips the picker).",
    ),
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Write full JSON report to this file path.",
    ),
) -> None:
    """Interactive env picker + health report. WRK-005"""
    from rich.prompt import Prompt
    from rich.rule import Rule

    path = path.resolve()
    if not path.exists():
        console.print(f"[red]✗[/red] Path not found: {path}")
        raise typer.Exit(1)

    cfg = load_config(path)
    envs = discover_envs(project_path=path)

    # ── resolve python executable ─────────────────────────────────────────────
    if env is not None:
        matched = resolve_env(env, envs)
        if matched is None:
            console.print(f"[red]✗[/red] Environment not found: {env!r}")
            raise typer.Exit(1)
        python_executable = str(matched.python)
        console.print(f"[dim]Environment:[/dim] {matched.name}  ({python_executable})\n")
    elif not envs:
        console.print("[yellow]No conda or .venv environments found — using system Python.[/yellow]\n")
        python_executable = ""
    else:
        # Interactive picker
        console.print(Rule("[bold cyan]forge dashboard[/bold cyan]"))
        console.print()

        t = Table(box=box.SIMPLE_HEAD, show_header=True, padding=(0, 2))
        t.add_column("#", justify="right", style="dim", no_wrap=True)
        t.add_column("Environment", style="bold")
        t.add_column("Python binary", style="dim")

        def_idx = default_index(envs, cfg.python_executable)
        for i, e in enumerate(envs):
            marker = " [green](default)[/green]" if i == def_idx else ""
            t.add_row(str(i + 1), f"{e.name}{marker}", str(e.python))

        console.print(t)

        raw = Prompt.ask(
            "Select environment",
            default=str(def_idx + 1),
            console=console,
        )
        try:
            idx = int(raw) - 1
            if idx < 0 or idx >= len(envs):
                raise ValueError
        except ValueError:
            console.print("[red]✗[/red] Invalid selection — enter a number from the list above.")
            raise typer.Exit(1)

        selected = envs[idx]
        python_executable = str(selected.python)
        console.print(f"\n[dim]Using:[/dim] [bold]{selected.name}[/bold]  ({python_executable})\n")

    # ── run health ────────────────────────────────────────────────────────────
    with console.status(f"[bold cyan]Analysing {path.name}…[/bold cyan]"):
        aggregator = Aggregator()
        report = aggregator.run(path, python_executable=python_executable)

    _print_report(report)

    if output:
        output.write_text(report.model_dump_json(indent=2))
        console.print(f"\n[dim]Report written to {output}[/dim]")


# ── forge gitsync ─────────────────────────────────────────────────────────────


@app.command()
def gitsync(
    target: Path = typer.Argument(
        default=Path("."),
        help="Repo path, or directory containing repos. Defaults to current directory.",
        show_default=True,
    ),
) -> None:
    """Fetch, pull, and prune stale branches across one or more repos. GIT-001, GIT-002, GIT-003, GIT-004"""
    from forge.git_sync import sync as run_sync

    target = target.resolve()
    if not target.exists():
        console.print(f"[red]✗[/red] Path not found: {target}")
        raise typer.Exit(1)

    with console.status("[bold cyan]Syncing repos…[/bold cyan]"):
        result = run_sync(target)

    if not result.repos:
        console.print("[yellow]No git repositories found.[/yellow]")
        raise typer.Exit(1)

    table = Table(box=box.SIMPLE_HEAD, show_header=True, padding=(0, 2))
    table.add_column("Repo", style="bold")
    table.add_column("Branch")
    table.add_column("Pulled", justify="center")
    table.add_column("Deleted")
    table.add_column("Skipped (unpushed)", style="yellow")
    table.add_column("Errors", style="red")

    for r in result.repos:
        skipped_text = ", ".join(
            f"{b} ({r.skip_reasons.get(b, 'unpushed')})" for b in r.skipped
        ) or "—"
        table.add_row(
            r.repo.name,
            r.landed_on or "—",
            "[green]✓[/green]" if r.pulled else "[red]✗[/red]",
            ", ".join(r.deleted) or "—",
            skipped_text,
            ", ".join(r.errors) or "—",
        )

    console.print()
    console.print(table)


if __name__ == "__main__":
    app()
