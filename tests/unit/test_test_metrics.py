"""Unit tests for TestMetricsCollector — COL-001."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from forge.collectors.test_metrics import TestMetricsCollector


@pytest.fixture()
def collector() -> TestMetricsCollector:
    return TestMetricsCollector()


def _make_proc(stdout: str = "", returncode: int = 0) -> MagicMock:
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = returncode
    return proc


class TestTestMetricsCollector:
    def test_skips_nonexistent_path(self, collector, tmp_path):
        result = collector.collect(tmp_path / "nope")
        assert result.skipped
        assert "does not exist" in (result.skip_reason or "")

    def test_skips_when_no_tests_found(self, collector, tmp_path):
        result = collector.collect(tmp_path)
        assert result.skipped
        assert "No tests" in (result.skip_reason or "")

    def test_skips_when_pytest_not_found(self, collector, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_pass(): assert True\n")
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = collector.collect(tmp_path)
        assert result.skipped
        assert "pytest not found" in (result.skip_reason or "")

    def test_parses_all_passing(self, collector, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_pass(): assert True\n")
        stdout = "5 passed in 0.12s"
        with patch("subprocess.run", return_value=_make_proc(stdout=stdout)):
            result = collector.collect(tmp_path)
        assert result.passed == 5
        assert result.failed == 0
        assert result.pass_rate == 1.0

    def test_parses_mixed_results(self, collector, tmp_path):
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("def test_pass(): assert True\n")
        stdout = "3 passed, 2 failed, 1 skipped in 0.5s"
        with patch("subprocess.run", return_value=_make_proc(stdout=stdout, returncode=1)):
            result = collector.collect(tmp_path)
        assert result.passed == 3
        assert result.failed == 2
        assert result.skipped_tests == 1
        assert result.pass_rate == pytest.approx(0.6, abs=0.01)

    def test_score_is_none_when_no_tests_ran(self, collector):
        score = collector._compute_score(None, None)
        assert score is None

    def test_score_perfect_all_pass_full_coverage(self, collector):
        score = collector._compute_score(1.0, 100.0)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_score_low_for_failing_tests(self, collector):
        score = collector._compute_score(0.0, 0.0)
        assert score == pytest.approx(0.0, abs=0.01)

    def test_coverage_parsed_from_json(self, collector, tmp_path):
        cov_file = tmp_path / ".forge_coverage.json"
        cov_file.write_text(json.dumps({"totals": {"percent_covered": 87.5}}))
        pct = collector._parse_coverage_json(cov_file)
        assert pct == pytest.approx(87.5)

    def test_coverage_returns_none_for_missing_file(self, collector, tmp_path):
        pct = collector._parse_coverage_json(tmp_path / "missing.json")
        assert pct is None

    def test_coverage_returns_none_for_malformed_json(self, collector, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        pct = collector._parse_coverage_json(bad)
        assert pct is None

    def test_find_src_dir_flat_layout(self, collector, tmp_path):
        pkg = tmp_path / "mylib"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        found = collector._find_src_dir(tmp_path)
        assert found == pkg

    def test_find_src_dir_src_layout(self, collector, tmp_path):
        src = tmp_path / "src" / "mylib"
        src.mkdir(parents=True)
        (src / "__init__.py").write_text("")
        found = collector._find_src_dir(tmp_path)
        assert found == src

    def test_find_src_dir_returns_none_when_no_package(self, collector, tmp_path):
        found = collector._find_src_dir(tmp_path)
        assert found is None
