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

Coverage threshold is 80%.

## Architecture

Forge is a collector-aggregator CLI tool. The main data flow:

1. `forge health <path>` → CLI (`cli.py`) → `Aggregator.run()` → 4 collectors → `ProjectHealthReport`
2. `forge new <name>` → CLI → `ScaffoldEngine.create()` → writes project files from templates

**Collector pattern**: each collector in `forge/collectors/` has a `.collect(project_path: Path) -> CollectorResult` method. Collectors independently detect whether their required tool is available; if not, they return `skipped=True` with a reason. The aggregator re-normalizes weights across only the non-skipped collectors.

**Scoring**: each collector returns a `score` (0.0–1.0). `ProjectHealthReport.overall_score` is a weighted average; `grade` maps to A/B/C/D/F at thresholds 0.90/0.80/0.70/0.60.

Default weights: `test_metrics=0.35`, `complexity=0.25`, `dependency_health=0.25`, `requirements_coverage=0.15`. These are overridable via `forge.toml` in the analyzed project.

## Key modules

| Module | Role |
|---|---|
| `forge/cli.py` | Typer app; `health` and `new` commands; Rich rendering |
| `forge/aggregator.py` | Runs all collectors, assembles `ProjectHealthReport` |
| `forge/models.py` | Pydantic v2 models: `ProjectHealthReport`, `CollectorWeights`, 4 `CollectorResult` subclasses |
| `forge/config.py` | Loads `forge.toml` into `ForgeConfig`; provides defaults if file absent |
| `forge/collectors/test_metrics.py` | Runs pytest + coverage.py subprocess; auto-detects project Python |
| `forge/collectors/complexity.py` | Runs radon for cyclomatic complexity + maintainability index |
| `forge/collectors/dependency_health.py` | Runs pip-audit; skips if no `requirements.txt` or `pyproject.toml` found |
| `forge/collectors/requirements_coverage.py` | YAML mode (preferred) or regex fallback — see below |
| `forge/scaffolder/engine.py` | Creates new project trees from templates using `$VAR` substitution |

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
test_metrics = 0.35
complexity = 0.25
dependency_health = 0.25
requirements_coverage = 0.15

[thresholds]
overall = 0.70
coverage = 0.80

[collectors.requirements]
tag_pattern = "REQ-\\d+"   # only used when no requirements.yaml found

[test_runner]
python = "/path/to/env/bin/python"   # overrides auto-detection
```

## Tests

- `tests/unit/` — pure unit tests using mocks, marked `@pytest.mark.unit`
- `tests/integration/` — filesystem + subprocess tests, marked `@pytest.mark.integration`

## Requirements traceability

`docs/REQUIREMENTS.md` defines REQ-001 through REQ-010 for forge itself. Source files reference these with inline `REQ-NNN` tags. When adding new features, tag them if they correspond to a requirement.
