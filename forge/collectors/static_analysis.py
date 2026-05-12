"""Static analysis collector — COL-006.

Uses ruff (preferred) or flake8 (fallback) to count lint errors.
Ruff violations are bucketed by fix applicability:
  safe    — auto-fixable with no behavior change (weight 0.3)
  unsafe  — auto-fixable but may change behavior  (weight 0.7)
  manual  — no fix available, requires manual work (weight 1.0)
The score uses weighted error density so safe formatting noise
penalises the score less than genuine logic issues.
Falls back gracefully if neither tool is installed (SYS-002).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from forge.models import StaticAnalysisResult

_SAFE_WEIGHT = 0.3
_UNSAFE_WEIGHT = 0.7
_MANUAL_WEIGHT = 1.0
_DENSITY_CEILING = 50.0  # weighted errors per 1000 lines → score 0.0


class StaticAnalysisCollector:
    """Collect static analysis metrics via ruff or flake8."""

    def collect(self, project_path: Path) -> StaticAnalysisResult:
        project_path = project_path.resolve()

        if not project_path.exists():
            return StaticAnalysisResult(
                skipped=True,
                skip_reason=f"Project path does not exist: {project_path}",
            )

        py_files = list(project_path.rglob("*.py"))
        py_files = [f for f in py_files if "__pycache__" not in f.parts]
        if not py_files:
            return StaticAnalysisResult(
                skipped=True,
                skip_reason="No Python source files found",
            )

        total_lines = self._count_python_lines(py_files)
        ruff_result = self._run_ruff(project_path)

        if ruff_result is not None:
            safe, unsafe, manual, by_rule = ruff_result
        else:
            flake8_count = self._run_flake8(project_path)
            if flake8_count is None:
                return StaticAnalysisResult(
                    skipped=True,
                    skip_reason="ruff not found — install with: pip install ruff",
                )
            safe, unsafe, manual, by_rule = 0, 0, flake8_count, {}

        score = self._compute_score(safe, unsafe, manual, total_lines)
        weighted = safe * _SAFE_WEIGHT + unsafe * _UNSAFE_WEIGHT + manual * _MANUAL_WEIGHT
        density = weighted / max(total_lines, 1) * 1000

        top_rules = dict(sorted(by_rule.items(), key=lambda x: -x[1])[:5])

        return StaticAnalysisResult(
            score=score,
            safe_errors=safe,
            unsafe_errors=unsafe,
            manual_errors=manual,
            total_lines=total_lines,
            error_density=round(density, 2),
            details={"python_files_analysed": len(py_files), "top_rules": top_rules},
        )

    def _run_ruff(self, project_path: Path) -> tuple[int, int, int, dict[str, int]] | None:
        """Run ruff check and return (safe, unsafe, manual, by_rule), or None if unavailable."""
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "--output-format=json", str(project_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            # exit 0 = no errors, exit 1 = errors found — both are valid data
            if proc.returncode not in (0, 1):
                return None
            data = json.loads(proc.stdout or "[]")
            safe = unsafe = manual = 0
            by_rule: dict[str, int] = {}
            for v in data:
                fix = v.get("fix")
                if fix is None:
                    manual += 1
                elif fix.get("applicability") == "safe":
                    safe += 1
                else:
                    unsafe += 1
                code = v.get("code") or "?"
                by_rule[code] = by_rule.get(code, 0) + 1
            return safe, unsafe, manual, by_rule
        except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return None

    def _run_flake8(self, project_path: Path) -> int | None:
        """Fallback: run flake8 and count error lines from stdout."""
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "flake8", str(project_path)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode not in (0, 1):
                return None
            lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
            return len(lines)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _count_python_lines(self, py_files: list[Path]) -> int:
        total = 0
        for f in py_files:
            try:
                total += sum(1 for ln in f.read_text(errors="replace").splitlines() if ln.strip())
            except OSError:
                pass
        return total

    def _compute_score(self, safe: int, unsafe: int, manual: int, total_lines: int) -> float:
        weighted = safe * _SAFE_WEIGHT + unsafe * _UNSAFE_WEIGHT + manual * _MANUAL_WEIGHT
        density = weighted / max(total_lines, 1) * 1000
        return round(max(0.0, 1.0 - min(density / _DENSITY_CEILING, 1.0)), 4)
