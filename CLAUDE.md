# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Environment setup
conda env create -f environment.yaml
conda activate forge
pip install -e ".[all]"

# Tests
pytest                          # all tests with coverage
pytest tests/unit/              # unit tests only
pytest tests/integration/       # integration tests only
pytest -k test_name             # single test by name
pytest -m unit                  # by marker

# Lint / format / type check
ruff check .
ruff format .
mypy forge/
```

Coverage threshold is 80%. Pre-commit hooks run ruff (lint + format) automatically on commit.

## CLI reference

```bash
# Health check
forge health <path>             # run all collectors, print report
forge health <path> --python /path/to/python   # override interpreter for running tests
forge health <path> --output report.json        # also write JSON
forge health <path> --json                      # raw JSON to stdout only

# Scaffold
forge new <name>                # scaffold with git init
forge new <name> --github       # also create GitHub repo + dev branch + main ruleset
forge new <name> --github --private             # make repo private
forge new <name> --github --description "..."   # set repo description
forge new <name> --no-git       # skip git init
forge new <name> --dest ~/Projects              # parent directory
```

## Architecture

Forge is a collector-aggregator CLI tool. The main data flow:

1. `forge health <path>` → CLI (`cli.py`) → `Aggregator.run()` → 4 collectors → `ProjectHealthReport`
2. `forge new <name>` → CLI → `ScaffoldEngine.create()` → writes project files from templates

**Collector pattern**: each collector in `forge/collectors/` has a `.collect(project_path: Path) -> CollectorResult` method. Collectors independently detect whether their required tool is available; if not, they return `skipped=True` with a reason. The aggregator re-normalizes weights across only the non-skipped collectors.

**Scoring**: each collector returns a `score` (0.0–1.0). `ProjectHealthReport.overall_score` is a weighted average; `grade` maps to A/B/C/D/F at thresholds 0.90/0.80/0.70/0.60.

Default weights: `test_metrics=0.30`, `complexity=0.15`, `dependency_health=0.20`, `requirements_coverage=0.10`, `static_analysis=0.10`, `type_coverage=0.10`, `dead_code=0.05`, `mutation_testing=0.00`. These are overridable via `forge.toml`. All 8 weights must sum to 1.0.

**Mutation testing** is disabled by default (very slow). Enable per-project: `[collectors.mutation_testing] enabled = true` in `forge.toml`.

**Coverage-only mode**: `Aggregator.run(project_path, skip_test_run=True)` skips pytest execution and reads an existing `coverage.xml` from the project. Use this when the caller already ran tests.

## Key modules

| Module | Role |
|---|---|
| `forge/cli.py` | Typer app; `health` and `new` commands; Rich rendering |
| `forge/aggregator.py` | Runs all collectors, assembles `ProjectHealthReport` |
| `forge/models.py` | Pydantic v2 models: `ProjectHealthReport`, `CollectorWeights`, 4 `CollectorResult` subclasses |
| `forge/config.py` | Loads `forge.toml` into `ForgeConfig`; provides defaults if file absent |
| `forge/collectors/test_metrics.py` | Runs pytest + coverage.py subprocess; auto-detects project Python; supports `run_tests=False` coverage-only mode |
| `forge/collectors/complexity.py` | Runs radon for **cyclomatic** complexity (CC) + maintainability index (MI) |
| `forge/collectors/dependency_health.py` | Runs pip-audit; skips if no `requirements.txt` or `pyproject.toml` found |
| `forge/collectors/requirements_coverage.py` | YAML mode (preferred) or regex fallback — see below |
| `forge/collectors/static_analysis.py` | Runs ruff (or flake8 fallback); error density score |
| `forge/collectors/type_coverage.py` | Runs mypy; count-based score (100+ errors → 0.0) |
| `forge/collectors/dead_code.py` | Runs vulture ≥80% confidence; density-based score |
| `forge/collectors/mutation_testing.py` | Runs mutmut; disabled by default (very slow) |
| `forge/scaffolder/engine.py` | Creates new project trees from templates using `$VAR` substitution |
| `forge/scaffolder/github_setup.py` | Creates GitHub repo, commits, pushes, creates `dev` branch, applies main branch ruleset via `gh` CLI |

## Non-obvious collector behaviour

**`RequirementsCoverageCollector`** operates in two modes selected automatically:
- **YAML mode** (preferred): if the target project has `docs/requirements.yaml` (or `requirements.yaml` at root), requirement IDs are read from `- id:` fields. Any prefix works (`DAT-001`, `SYS-002`, etc.). Coverage = IDs referenced in at least one test file ÷ total IDs.
- **Regex fallback**: if no YAML file exists, scans source files for tags matching `tag_pattern` (default `REQ-\d+`) and checks which appear in test files.

**`TestMetricsCollector`** auto-detects the Python interpreter for the target project in this order: project `.venv/bin/python` → conda env named in `environment.yaml`/`environment.yml` → `sys.executable`. Override with `--python` on the CLI or `[test_runner] python = "..."` in the target project's `forge.toml`.

## forge.toml (in the analyzed project, not forge itself)

```toml
[project]
name = "my-project"

[weights]
# All 8 weights must sum to 1.0
test_metrics        = 0.30
complexity          = 0.15
dependency_health   = 0.20
requirements_coverage = 0.10
static_analysis     = 0.10
type_coverage       = 0.10
dead_code           = 0.05
mutation_testing    = 0.00   # set to non-zero only if enabled below

[thresholds]
overall = 0.70
coverage = 0.80

[collectors.requirements]
tag_pattern = "REQ-\\d+"   # only used when no requirements.yaml found

[collectors.mutation_testing]
enabled = false   # set to true to run mutmut (very slow — 30+ min)

[test_runner]
python = "/path/to/env/bin/python"   # overrides auto-detection
```

## GitHub setup (`forge new --github`)

`GitHubSetup.run()` executes these steps in order, stopping on first error:
1. `_initial_local_commit` — `git add .` + `git commit` (must happen before remote creation)
2. `_create_repo` — `gh repo create <name> --source <abs_path>` (sets up `origin` remote)
3. `_push_to_remote` — `git push -u origin main`
4. `_create_dev_branch` — creates `dev` branch via GitHub API pointing at `main`'s SHA
5. `_apply_main_ruleset` — POSTs a ruleset to protect `main`: requires PR, forbids deletion and force-push
6. `_update_ci_workflow` — rewrites `.github/workflows/ci.yml` push trigger from `main` to `dev`

All subprocess calls go through `_run(cmd, stdin=None)` which returns stdout or `None` on failure. JSON API calls use `_run_json`. Requires `gh` CLI authenticated via `gh auth login`.

## Branch and PR policy

**main** — no direct pushes; all changes via pull request (enforced by GitHub ruleset).
**dev** — direct pushes allowed; preferred workflow is feature branch → PR → dev.

For changes to forge itself: create a feature branch from `dev`, open a PR targeting `dev`, then open a separate `dev → main` PR when ready to ship.

## Tests

- `tests/unit/` — pure unit tests using mocks, marked `@pytest.mark.unit`
- `tests/integration/` — filesystem + subprocess tests, marked `@pytest.mark.integration`
- `GitHubSetup` tests in `tests/unit/test_github_setup.py` mock all subprocess calls with `patch.object(GitHubSetup, "_run", ...)` — never make real network calls

## Requirements traceability

`docs/REQUIREMENTS.md` defines REQ-001 through REQ-010 for forge itself. Source files reference these with inline `REQ-NNN` tags. When adding new features, tag them if they correspond to a requirement.
