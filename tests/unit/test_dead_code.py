"""Unit tests for DeadCodeCollector — COL-008."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from forge.collectors.dead_code import DeadCodeCollector


@pytest.fixture()
def collector() -> DeadCodeCollector:
    return DeadCodeCollector()


class TestDeadCodeCollector:
    def test_skips_nonexistent_path(self, collector: DeadCodeCollector, tmp_path: Path) -> None:
        result = collector.collect(tmp_path / "nope")
        assert result.skipped
        assert "does not exist" in (result.skip_reason or "").lower()

    def test_skips_when_no_python_files(self, collector: DeadCodeCollector, tmp_path: Path) -> None:
        result = collector.collect(tmp_path)
        assert result.skipped

    def test_skips_when_vulture_not_found(self, collector: DeadCodeCollector, tmp_path: Path) -> None:
        (tmp_path / "foo.py").write_text("def hello(): pass\n")
        with patch.object(collector, "_run_vulture", return_value=None):
            result = collector.collect(tmp_path)
        assert result.skipped
        assert "vulture" in (result.skip_reason or "").lower()

    def test_perfect_score_when_no_unused(self, collector: DeadCodeCollector, tmp_path: Path) -> None:
        (tmp_path / "foo.py").write_text("def hello(): pass\n")
        with patch.object(collector, "_run_vulture", return_value=0):
            result = collector.collect(tmp_path)
        assert not result.skipped
        assert result.score == 1.0
        assert result.unused_items == 0

    def test_score_decreases_with_dead_code(self, collector: DeadCodeCollector, tmp_path: Path) -> None:
        py = tmp_path / "foo.py"
        py.write_text("def a(): pass\n" * 100)
        with patch.object(collector, "_run_vulture", return_value=10):
            result = collector.collect(tmp_path)
        assert not result.skipped
        assert result.score is not None
        assert result.score < 1.0
        assert result.unused_density is not None

    def test_score_zero_at_density_ceiling(self, collector: DeadCodeCollector) -> None:
        assert collector._compute_score(20, 1000) == 0.0

    def test_score_one_at_zero_unused(self, collector: DeadCodeCollector) -> None:
        assert collector._compute_score(0, 1000) == 1.0

    def test_count_python_lines_excludes_blank(self, collector: DeadCodeCollector, tmp_path: Path) -> None:
        py = tmp_path / "foo.py"
        py.write_text("def f(): pass\n\n# comment\n")
        files = [py]
        count = collector._count_python_lines(files)
        assert count == 2
