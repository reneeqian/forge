"""Shared pytest fixtures for the Forge test suite."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """A minimal Python project with one passing test and a source file.

    Structure:
        tmp_project/
          src/mylib/__init__.py
          src/mylib/core.py
          tests/__init__.py
          tests/test_core.py        ← references REQ-001
          docs/REQUIREMENTS.md      ← defines REQ-001, REQ-002
          pyproject.toml
    """
    src = tmp_path / "src" / "mylib"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (src / "core.py").write_text(
        textwrap.dedent("""\
            # REQ-001
            def add(a: int, b: int) -> int:
                return a + b
        """)
    )

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_core.py").write_text(
        textwrap.dedent("""\
            from mylib.core import add  # REQ-001

            def test_add():
                assert add(1, 2) == 3
        """)
    )

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "REQUIREMENTS.md").write_text(
        textwrap.dedent("""\
            ## REQ-001 · Addition
            The library SHALL expose an add() function.

            ## REQ-002 · Subtraction
            The library SHALL expose a subtract() function.
        """)
    )

    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent("""\
            [build-system]
            requires = ["hatchling"]
            build-backend = "hatchling.build"

            [project]
            name = "mylib"
            version = "0.1.0"
            requires-python = ">=3.11"
            dependencies = []
        """)
    )

    return tmp_path


@pytest.fixture()
def empty_project(tmp_path: Path) -> Path:
    """A project with no tests, no source, no config."""
    return tmp_path


@pytest.fixture()
def project_with_forge_toml(tmp_project: Path) -> Path:
    """tmp_project with a custom forge.toml."""
    (tmp_project / "forge.toml").write_text(
        textwrap.dedent("""\
            [project]
            name = "custom-name"

            [weights]
            test_metrics        = 0.30
            complexity          = 0.15
            dependency_health   = 0.20
            requirements_coverage = 0.10
            static_analysis     = 0.10
            type_coverage       = 0.10
            dead_code           = 0.05
            mutation_testing    = 0.00

            [thresholds]
            overall = 0.75
            coverage = 0.85
        """)
    )
    return tmp_project
