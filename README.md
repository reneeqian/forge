# forge

> Personal project automation toolkit — health metrics, scaffolding, and workflow utilities.

## Install

```bash
conda env create -f environment.yaml
conda activate forge
pip install -e ".[all]"
```

## Commands

### Health check
```bash
forge health .                          # check current directory
forge health /path/to/project           # check a specific project
forge health . --output report.json     # save full JSON report
forge health . --json                   # raw JSON to stdout
```

### New project
```bash
forge new my-project                    # interactive scaffold
forge new my-project --dest ~/Projects  # specify parent directory
forge new my-project --no-git           # skip git init
```

## Collector Metrics

The overall health score is a weighted average of up to eight collector scores (0.0–1.0). Skipped collectors (missing tool, no files) are excluded and their weight is redistributed proportionally. Grades: **A** ≥ 0.90 · **B** ≥ 0.80 · **C** ≥ 0.70 · **D** ≥ 0.60 · **F** < 0.60.

| Collector | Default weight | Tool | What it measures |
|---|---|---|---|
| `test_metrics` | 30 % | pytest + coverage.py | Blends test pass rate (70 %) and line coverage (30 %). Score 1.0 requires all tests passing and 100 % line coverage. |
| `dependency_health` | 20 % | pip-audit | Audits dependencies against the OSV/PyPI vulnerability database. Starts at 1.0; −0.15 per package with a known CVE. |
| `complexity` | 15 % | radon | Averages two radon metrics: cyclomatic complexity (CC, lower = better; avg CC ≥ 10 → 0.0, ≤ 1 → 1.0) and maintainability index (MI, 0–100 scale). Score = mean of the two normalised values. |
| `requirements_coverage` | 10 % | — | Traces requirement IDs from `docs/requirements.yaml` into test files. Falls back to scanning source for tags matching `tag_pattern` in `forge.toml`. Score = covered IDs / total IDs. |
| `static_analysis` | 10 % | ruff (flake8 fallback) | Counts lint errors and normalises by code size. Error density ≥ 50 per 1 000 lines → 0.0; zero errors → 1.0. |
| `type_coverage` | 10 % | mypy | Counts mypy type errors (not density-based, since one badly-typed module cascades). 0 errors → 1.0; ≥ 100 errors → 0.0. |
| `dead_code` | 5 % | vulture | Detects unused code (imports, variables, functions, classes) at ≥ 80 % confidence. Unused-item density ≥ 20 per 1 000 lines → 0.0. |
| `mutation_testing` | 0 % | mutmut | **Disabled by default** (slow). Enable via `[collectors.mutation_testing] enabled = true` in `forge.toml`. Score = killed mutants / total mutants. |

### Scoring formulas

```
test_metrics       = 0.7 × (passed / total) + 0.3 × (line_coverage / 100)
complexity         = mean(cc_score, mi_score)
                     cc_score  = 1 − clamp((avg_cc − 1) / 9, 0, 1)
                     mi_score  = avg_mi / 100
dependency_health  = max(0, 1 − 0.15 × vulnerable_packages)
static_analysis    = max(0, 1 − clamp(errors_per_1000 / 50, 0, 1))
type_coverage      = max(0, 1 − clamp(mypy_errors / 100, 0, 1))
dead_code          = max(0, 1 − clamp(unused_per_1000 / 20, 0, 1))
requirements_cov   = covered_ids / total_ids
mutation_testing   = killed_mutants / total_mutants
```

## Project structure

```
forge/
├── forge/
│   ├── collectors/              # metric collectors (one per domain)
│   │   ├── test_metrics.py      # pytest + coverage.py
│   │   ├── complexity.py        # radon CC + MI
│   │   ├── dependency_health.py # pip-audit CVE scan
│   │   ├── requirements_coverage.py  # YAML / regex tag tracing
│   │   ├── static_analysis.py   # ruff / flake8
│   │   ├── type_coverage.py     # mypy
│   │   ├── dead_code.py         # vulture
│   │   └── mutation_testing.py  # mutmut (opt-in)
│   ├── scaffolder/              # project quick-start generator
│   │   └── engine.py
│   ├── models.py                # Pydantic data models + CollectorWeights
│   ├── config.py                # forge.toml loader
│   ├── aggregator.py            # orchestrates collectors → report
│   └── cli.py                   # Typer CLI
├── tests/
│   ├── unit/                    # pure unit tests (mocked I/O)
│   └── integration/             # filesystem + subprocess tests
└── docs/
    └── REQUIREMENTS.md          # REQ-NNN requirement definitions
```

## forge.toml

Drop a `forge.toml` in any project to customise behaviour:

```toml
[project]
name = "my-project"

[thresholds]
overall = 0.70
coverage = 0.80

[weights]
test_metrics = 0.35
complexity = 0.25
dependency_health = 0.25
requirements_coverage = 0.15

[collectors.requirements]
tag_pattern = "REQ-\\d+"
```

## Development

```bash
pytest                  # run full test suite with coverage
ruff check .            # lint
ruff format .           # format
mypy forge/             # type check
```

## Requirements

See [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md).
