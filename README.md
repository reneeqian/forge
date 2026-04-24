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

## Project structure

```
forge/
├── forge/
│   ├── collectors/         # metric collectors (one per domain)
│   │   ├── test_metrics.py
│   │   ├── complexity.py
│   │   ├── dependency_health.py
│   │   └── requirements_coverage.py
│   ├── scaffolder/         # project quick-start generator
│   │   └── engine.py
│   ├── models.py           # Pydantic data models
│   ├── config.py           # forge.toml loader
│   ├── aggregator.py       # orchestrates collectors → report
│   └── cli.py              # Typer CLI
├── tests/
│   ├── unit/               # pure unit tests (mocked I/O)
│   └── integration/        # filesystem + subprocess tests
└── docs/
    └── REQUIREMENTS.md     # REQ-NNN requirement definitions
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
