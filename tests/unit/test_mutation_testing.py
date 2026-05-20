"""Unit tests for MutationTestingCollector — COL-009, COL-010."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.collectors.mutation_testing import MutationTestingCollector


@pytest.fixture()
def collector() -> MutationTestingCollector:
    return MutationTestingCollector()


class TestMutationTestingCollector:
    def test_disabled_by_default(self, collector: MutationTestingCollector, tmp_path: Path) -> None:
        # COL-010: mutation testing is opt-in
        result = collector.collect(tmp_path, enabled=False)
        assert result.skipped
        assert "Disabled" in (result.skip_reason or "")

    def test_skips_nonexistent_path(self, collector: MutationTestingCollector, tmp_path: Path) -> None:
        result = collector.collect(tmp_path / "nope", enabled=True)
        assert result.skipped
        assert "does not exist" in (result.skip_reason or "").lower()

    def test_skips_when_no_src_dir(self, collector: MutationTestingCollector, tmp_path: Path) -> None:
        result = collector.collect(tmp_path, enabled=True)
        assert result.skipped
        assert "No src" in (result.skip_reason or "")

    def test_skips_when_mutmut_not_found(self, collector: MutationTestingCollector, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.py").write_text("def add(a, b): return a + b\n")
        with patch.object(collector, "_run_mutmut", return_value=None):
            result = collector.collect(tmp_path, enabled=True)
        assert result.skipped
        assert "mutmut" in (result.skip_reason or "").lower()

    def test_skips_when_zero_mutants_generated(self, collector: MutationTestingCollector, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.py").write_text("def add(a, b): return a + b\n")
        with patch.object(collector, "_run_mutmut", return_value=(0, 0)):
            result = collector.collect(tmp_path, enabled=True)
        assert result.skipped

    def test_returns_mutation_score(self, collector: MutationTestingCollector, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.py").write_text("def add(a, b): return a + b\n")
        with patch.object(collector, "_run_mutmut", return_value=(40, 50)):
            result = collector.collect(tmp_path, enabled=True)
        assert not result.skipped
        assert result.score == pytest.approx(0.8)
        assert result.killed_mutants == 40
        assert result.total_mutants == 50

    def test_parse_results_json_format(self, collector: MutationTestingCollector) -> None:
        output = json.dumps({"killed": 40, "total": 50})
        assert collector._parse_mutmut_results(output) == (40, 50)

    def test_parse_results_plain_text(self, collector: MutationTestingCollector) -> None:
        assert collector._parse_mutmut_results("Killed mutants: 30/40") == (30, 40)

    def test_parse_results_status_lines(self, collector: MutationTestingCollector) -> None:
        output = "killed: 25\nsurvived: 5\n"
        assert collector._parse_mutmut_results(output) == (25, 30)

    def test_parse_results_returns_none_for_unrecognised(self, collector: MutationTestingCollector) -> None:
        assert collector._parse_mutmut_results("no useful output") is None

    def test_find_src_dir_finds_src_subdir(self, collector: MutationTestingCollector, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "foo.py").write_text("def f(): pass\n")
        assert collector._find_src_dir(tmp_path) == src

    def test_find_src_dir_returns_none_when_no_python(self, collector: MutationTestingCollector, tmp_path: Path) -> None:
        assert collector._find_src_dir(tmp_path) is None
