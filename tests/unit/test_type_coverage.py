"""Unit tests for TypeCoverageCollector — COL-007."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.collectors.type_coverage import TypeCoverageCollector


@pytest.fixture()
def collector() -> TypeCoverageCollector:
    return TypeCoverageCollector()


class TestTypeCoverageCollector:
    def test_skips_nonexistent_path(self, collector: TypeCoverageCollector, tmp_path: Path) -> None:
        result = collector.collect(tmp_path / "nope")
        assert result.skipped
        assert "does not exist" in (result.skip_reason or "").lower()

    def test_skips_when_no_python_files(self, collector: TypeCoverageCollector, tmp_path: Path) -> None:
        result = collector.collect(tmp_path)
        assert result.skipped
        assert "No Python source files" in (result.skip_reason or "")

    def test_skips_when_mypy_not_found(self, collector: TypeCoverageCollector, tmp_path: Path) -> None:
        (tmp_path / "foo.py").write_text("x: int = 1\n")
        with patch.object(collector, "_run_mypy", return_value=None):
            result = collector.collect(tmp_path)
        assert result.skipped
        assert "mypy" in (result.skip_reason or "").lower()

    def test_perfect_score_when_zero_errors(self, collector: TypeCoverageCollector, tmp_path: Path) -> None:
        (tmp_path / "foo.py").write_text("x: int = 1\n")
        with patch.object(collector, "_run_mypy", return_value=(0, 1)):
            result = collector.collect(tmp_path)
        assert not result.skipped
        assert result.score == 1.0
        assert result.total_errors == 0

    def test_score_decreases_with_errors(self, collector: TypeCoverageCollector, tmp_path: Path) -> None:
        (tmp_path / "foo.py").write_text("x = 1\n")
        with patch.object(collector, "_run_mypy", return_value=(50, 3)):
            result = collector.collect(tmp_path)
        assert not result.skipped
        assert result.score == pytest.approx(0.5)
        assert result.total_errors == 50
        assert result.files_checked == 3

    def test_score_zero_at_ceiling(self, collector: TypeCoverageCollector) -> None:
        assert collector._compute_score(100) == 0.0

    def test_score_one_at_zero(self, collector: TypeCoverageCollector) -> None:
        assert collector._compute_score(0) == 1.0

    def test_parse_mypy_stdout_counts_errors(self, collector: TypeCoverageCollector) -> None:
        stdout = (
            "src/foo.py:1: error: Incompatible types\n"
            "src/bar.py:5: error: Missing return type\n"
            "src/foo.py:10: note: Something\n"
        )
        errors, files = collector._parse_mypy_stdout(stdout)
        assert errors == 2
        assert files == 2
