"""Unit tests for StaticAnalysisCollector — REQ-011."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from forge.collectors.static_analysis import StaticAnalysisCollector


@pytest.fixture()
def collector() -> StaticAnalysisCollector:
    return StaticAnalysisCollector()


# ── StaticAnalysisCollector.collect() ────────────────────────────────────────


class TestStaticAnalysisCollector:
    def test_skips_nonexistent_path(self, collector: StaticAnalysisCollector, tmp_path):
        result = collector.collect(tmp_path / "nope")
        assert result.skipped
        assert "does not exist" in (result.skip_reason or "").lower()

    def test_skips_when_no_python_files(self, collector: StaticAnalysisCollector, tmp_path):
        result = collector.collect(tmp_path)
        assert result.skipped
        assert "No Python source files" in (result.skip_reason or "")

    def test_skips_when_ruff_and_flake8_unavailable(
        self, collector: StaticAnalysisCollector, tmp_path
    ):
        (tmp_path / "main.py").write_text("x = 1\n")
        with (
            patch.object(collector, "_run_ruff", return_value=None),
            patch.object(collector, "_run_flake8", return_value=None),
        ):
            result = collector.collect(tmp_path)
        assert result.skipped
        assert "ruff not found" in (result.skip_reason or "")

    def test_score_1_when_no_errors(self, collector: StaticAnalysisCollector, tmp_path):
        (tmp_path / "main.py").write_text("x = 1\n")
        with patch.object(collector, "_run_ruff", return_value=(0, 0, 0, {})):
            result = collector.collect(tmp_path)
        assert result.score == 1.0
        assert result.total_errors == 0

    def test_all_safe_scores_higher_than_all_manual_same_count(
        self, collector: StaticAnalysisCollector, tmp_path
    ):
        # 1000 lines so neither scenario hits the density ceiling
        (tmp_path / "main.py").write_text("x = 1\n" * 1000)
        with patch.object(collector, "_run_ruff", return_value=(20, 0, 0, {})):
            safe_result = collector.collect(tmp_path)
        with patch.object(collector, "_run_ruff", return_value=(0, 0, 20, {})):
            manual_result = collector.collect(tmp_path)
        assert safe_result.score is not None
        assert manual_result.score is not None
        assert safe_result.score > manual_result.score

    def test_score_0_at_density_ceiling(self, collector: StaticAnalysisCollector, tmp_path):
        lines = "x = 1\n" * 1000
        (tmp_path / "main.py").write_text(lines)
        # 1000 lines * _DENSITY_CEILING = 50 weighted errors/1k lines → score 0.0
        # With manual_weight=1.0: 50 manual errors per 1000 lines hits ceiling exactly
        with patch.object(collector, "_run_ruff", return_value=(0, 0, 50, {})):
            result = collector.collect(tmp_path)
        assert result.score == 0.0

    def test_top_rules_stored_in_details(self, collector: StaticAnalysisCollector, tmp_path):
        (tmp_path / "main.py").write_text("x = 1\n")
        by_rule = {"F401": 5, "I001": 3}
        with patch.object(collector, "_run_ruff", return_value=(0, 0, 8, by_rule)):
            result = collector.collect(tmp_path)
        assert result.details.get("top_rules") == {"F401": 5, "I001": 3}

    def test_flake8_fallback_goes_to_manual(self, collector: StaticAnalysisCollector, tmp_path):
        (tmp_path / "main.py").write_text("x = 1\n")
        with (
            patch.object(collector, "_run_ruff", return_value=None),
            patch.object(collector, "_run_flake8", return_value=5),
        ):
            result = collector.collect(tmp_path)
        assert not result.skipped
        assert result.manual_errors == 5
        assert result.safe_errors == 0
        assert result.unsafe_errors == 0


# ── _run_ruff ─────────────────────────────────────────────────────────────────


class TestRunRuff:
    def _make_violation(self, code: str, applicability: str | None) -> dict:
        fix = None if applicability is None else {"applicability": applicability, "edits": []}
        return {"code": code, "filename": "f.py", "row": 1, "col": 0, "message": "x", "fix": fix}

    def test_safe_fix_counted_in_safe(self, collector: StaticAnalysisCollector, tmp_path):
        data = [self._make_violation("I001", "safe")]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = json.dumps(data)
            result = collector._run_ruff(tmp_path)
        assert result is not None
        safe, unsafe, manual, _ = result
        assert safe == 1
        assert unsafe == 0
        assert manual == 0

    def test_unsafe_fix_counted_in_unsafe(self, collector: StaticAnalysisCollector, tmp_path):
        data = [self._make_violation("UP007", "unsafe")]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = json.dumps(data)
            result = collector._run_ruff(tmp_path)
        assert result is not None
        safe, unsafe, manual, _ = result
        assert unsafe == 1
        assert safe == 0
        assert manual == 0

    def test_null_fix_counted_in_manual(self, collector: StaticAnalysisCollector, tmp_path):
        data = [self._make_violation("B017", None)]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = json.dumps(data)
            result = collector._run_ruff(tmp_path)
        assert result is not None
        safe, unsafe, manual, _ = result
        assert manual == 1
        assert safe == 0
        assert unsafe == 0

    def test_by_rule_dict_populated(self, collector: StaticAnalysisCollector, tmp_path):
        data = [
            self._make_violation("F401", "safe"),
            self._make_violation("F401", "safe"),
            self._make_violation("B017", None),
        ]
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = json.dumps(data)
            result = collector._run_ruff(tmp_path)
        assert result is not None
        _, _, _, by_rule = result
        assert by_rule["F401"] == 2
        assert by_rule["B017"] == 1

    def test_returns_none_on_nonzero_exit(self, collector: StaticAnalysisCollector, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 2
            mock_run.return_value.stdout = ""
            result = collector._run_ruff(tmp_path)
        assert result is None

    def test_returns_none_on_json_decode_error(
        self, collector: StaticAnalysisCollector, tmp_path
    ):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "not json"
            result = collector._run_ruff(tmp_path)
        assert result is None

    def test_zero_counts_when_no_violations(self, collector: StaticAnalysisCollector, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "[]"
            result = collector._run_ruff(tmp_path)
        assert result == (0, 0, 0, {})


# ── _compute_score ────────────────────────────────────────────────────────────


class TestComputeScore:
    def test_zero_errors_returns_1_0(self, collector: StaticAnalysisCollector):
        assert collector._compute_score(0, 0, 0, 1000) == 1.0

    def test_safe_only_higher_than_manual_only(self, collector: StaticAnalysisCollector):
        safe_score = collector._compute_score(100, 0, 0, 1000)
        manual_score = collector._compute_score(0, 0, 100, 1000)
        assert safe_score > manual_score

    def test_mixed_tiers_between_extremes(self, collector: StaticAnalysisCollector):
        all_safe = collector._compute_score(50, 0, 0, 1000)
        mixed = collector._compute_score(25, 0, 25, 1000)
        all_manual = collector._compute_score(0, 0, 50, 1000)
        assert all_safe > mixed > all_manual

    def test_score_clamped_to_zero(self, collector: StaticAnalysisCollector):
        assert collector._compute_score(0, 0, 10_000, 100) == 0.0
