"""Scaffold engine — CLI-002.

Creates a new project with standard structure, forge.toml, environment.yaml,
pyproject.toml, .gitignore, README, and a passing starter test.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

from forge.scaffolder.github_setup import GitHubConfig, GitHubSetup, GitHubSetupResult


@dataclass
class ScaffoldConfig:
    project_name: str
    destination: Path
    python_version: str = "3.11"
    license_type: str = "MIT"
    author: str = ""
    git_init: bool = True
    github: GitHubConfig | None = None


@dataclass
class ScaffoldResult:
    project_path: Path
    created_files: list[Path] = field(default_factory=list)
    github: GitHubSetupResult | None = None


class ScaffoldEngine:
    """Write a new project tree to disk from in-memory templates."""

    def create(self, config: ScaffoldConfig) -> ScaffoldResult:
        dest = config.destination
        dest.mkdir(parents=True, exist_ok=False)

        result = ScaffoldResult(project_path=dest)
        pkg = config.project_name.lower().replace("-", "_").replace(" ", "_")

        vars: dict[str, str] = {
            "PROJECT_NAME": config.project_name,
            "PKG_NAME": pkg,
            "PYTHON_VERSION": config.python_version,
            "LICENSE": config.license_type,
            "AUTHOR": config.author,
        }

        files = self._file_tree(vars)
        for rel_path, content in files.items():
            full_path = dest / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)
            result.created_files.append(full_path)

        if config.git_init:
            try:
                subprocess.run(
                    ["git", "init", str(dest)],
                    capture_output=True,
                    check=False,
                )
            except FileNotFoundError:
                pass  # git not available — non-fatal

        if config.github is not None:
            result.github = GitHubSetup().run(dest, config.github)

        return result

    # ── file tree ─────────────────────────────────────────────────────────────

    def _file_tree(self, v: dict[str, str]) -> dict[str, str]:
        """Return {relative_path: rendered_content} for all files to create."""
        pkg = v["PKG_NAME"]
        name = v["PROJECT_NAME"]

        return {
            # Source package
            f"src/{pkg}/__init__.py": self._render(_INIT_PY, v),
            f"src/{pkg}/main.py": self._render(_MAIN_PY, v),

            # Tests
            "tests/__init__.py": "",
            "tests/conftest.py": self._render(_CONFTEST, v),
            f"tests/test_{pkg}.py": self._render(_STARTER_TEST, v),

            # Docs
            "docs/REQUIREMENTS.md": self._render(_REQUIREMENTS_MD, v),

            # Config files
            "pyproject.toml": self._render(_PYPROJECT_TOML, v),
            "environment.yaml": self._render(_ENVIRONMENT_YAML, v),
            "forge.toml": self._render(_FORGE_TOML, v),
            ".gitignore": _GITIGNORE,
            ".python-version": v["PYTHON_VERSION"],
            "README.md": self._render(_README, v),
            "CHANGELOG.md": self._render(_CHANGELOG, v),

            # GitHub Actions
            ".github/workflows/ci.yml": self._render(_CI_WORKFLOW, v),
            ".github/workflows/forge-health.yml": self._render(_FORGE_HEALTH_WORKFLOW, v),
            ".github/workflows/auto-merge.yml": self._render(_AUTO_MERGE_WORKFLOW, v),
        }

    def _render(self, template: str, vars: dict[str, str]) -> str:
        return Template(template).safe_substitute(vars)


# ── Templates ─────────────────────────────────────────────────────────────────

_INIT_PY = '''\
"""$PROJECT_NAME package."""

__version__ = "0.1.0"
'''

_MAIN_PY = '''\
"""$PROJECT_NAME — entry point."""


def main() -> None:
    print("Hello from $PROJECT_NAME")


if __name__ == "__main__":
    main()
'''

_CONFTEST = '''\
"""Shared pytest fixtures for $PROJECT_NAME."""

import pytest
'''

_STARTER_TEST = '''\
"""Starter tests for $PROJECT_NAME.

Tag requirement traces like: # REQ-001
"""

from $PKG_NAME.main import main  # REQ-001


def test_main_runs(capsys) -> None:
    """Verify main() runs without errors.  # REQ-001"""
    main()
    captured = capsys.readouterr()
    assert "$PROJECT_NAME" in captured.out
'''

_REQUIREMENTS_MD = '''\
# $PROJECT_NAME — Requirements

## REQ-001 · Hello World
The package SHALL expose a `main()` function that prints a greeting to stdout.

---

*Add requirements here. Reference them in source and tests with tags like `# REQ-001`.*
'''

_PYPROJECT_TOML = '''\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "$PROJECT_NAME"
version = "0.1.0"
description = ""
requires-python = ">=$PYTHON_VERSION"
license = { text = "$LICENSE" }
authors = [{ name = "$AUTHOR" }]
dependencies = []

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "ruff>=0.4",
    "mypy>=1.10",
]

[tool.hatch.build.targets.wheel]
packages = ["src/$PKG_NAME"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--cov=$PKG_NAME --cov-report=term-missing -v"

[tool.coverage.run]
source = ["src/$PKG_NAME"]
'''

_ENVIRONMENT_YAML = '''\
name: $PROJECT_NAME
channels:
  - conda-forge
  - defaults
dependencies:
  - python=$PYTHON_VERSION
  - pip
  - pip:
      - -e ".[dev]"
'''

_FORGE_TOML = '''\
[project]
name = "$PROJECT_NAME"

[thresholds]
overall = 0.70
coverage = 0.80

[weights]
test_metrics = 0.35
complexity = 0.25
dependency_health = 0.25
requirements_coverage = 0.15

[collectors.requirements]
tag_pattern = "REQ-\\\\d+"
sources = ["docs/REQUIREMENTS.md"]
'''

_GITIGNORE = '''\
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.eggs/

# Environments
.env
.venv
env/

# Coverage
.coverage
coverage.json
htmlcov/
.forge_coverage.json

# Editors
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# Forge
forge-report.json
'''

_README = '''\
# $PROJECT_NAME

> A brief description of what this project does.

## Setup

```bash
conda env create -f environment.yaml
conda activate $PROJECT_NAME
pip install -e ".[dev]"
```

## Usage

```python
from $PKG_NAME.main import main
main()
```

## Development

```bash
pytest          # run tests
forge health .  # project health check
ruff check .    # lint
```
'''

_CHANGELOG = '''\
# Changelog

## [Unreleased]

### Added
- Initial project scaffold
'''

_CI_WORKFLOW = '''\
name: CI

on:
  push:
    branches: [dev]
  pull_request:
    branches: [dev, main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "$PYTHON_VERSION"
      - run: pip install -e ".[dev]"
      - run: pytest
      - run: ruff check .
'''

_FORGE_HEALTH_WORKFLOW = '''\
name: Forge Health

on:
  push:
    branches: [main]
  schedule:
    - cron: "0 9 * * 1"  # Every Monday at 9am UTC

jobs:
  health:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "$PYTHON_VERSION"
      - run: pip install forge-utils[collectors]
      - run: forge health . --output forge-report.json
      - uses: actions/upload-artifact@v4
        with:
          name: forge-health-report
          path: forge-report.json
'''

_AUTO_MERGE_WORKFLOW = '''\
name: Auto-merge

on:
  pull_request:
    types: [opened, reopened, synchronize]
    branches:
      - dev

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

permissions:
  pull-requests: write
  contents: write

jobs:
  enable-auto-merge:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Enable auto-merge
        run: gh pr merge --auto --merge "$${{ github.event.pull_request.number }}"
        env:
          GH_TOKEN: $${{ github.token }}
'''
