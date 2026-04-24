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

Coverage threshold is 80%. Templates at `forge/scaffolder/templates/*` are excluded from coverage.

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
| `forge/collectors/test_metrics.py` | Runs pytest + coverage.py subprocess |
| `forge/collectors/complexity.py` | Runs radon for cyclomatic complexity + maintainability index |
| `forge/collectors/dependency_health.py` | Runs pip-audit and parses CVE JSON |
| `forge/collectors/requirements_coverage.py` | Regex-scans source for `REQ-\d+` tags |
| `forge/scaffolder/engine.py` | Creates new project trees from templates using `$VAR` substitution |

## Tests

- `tests/unit/` — pure unit tests using mocks, marked `@pytest.mark.unit`
- `tests/integration/` — filesystem + subprocess tests, marked `@pytest.mark.integration`

## Requirements traceability

`docs/REQUIREMENTS.md` defines REQ-001 through REQ-010. Source files reference these with inline `REQ-NNN` tags, which `RequirementsCoverageCollector` scans for. When adding new features, tag them if they correspond to a requirement.
