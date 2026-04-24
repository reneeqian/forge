"""Static analysis collector — REQ-011.

Uses ruff (preferred) or flake8 (fallback) to count lint errors.
Falls back gracefully if neither tool is installed (REQ-010).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from forge.models import StaticAnalysisResult

_DENSITY_CEILING = 50.0  # errors per 1000 lines → score 0.0


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
        errors = self._run_ruff(project_path)

        if errors is None:
            errors = self._run_flake8(project_path)

        if errors is None:
            return StaticAnalysisResult(
                skipped=True,
                skip_reason="ruff not found — install with: pip install ruff",
            )

        density = errors / max(total_lines, 1) * 1000
        score = self._compute_score(errors, total_lines)

        return StaticAnalysisResult(
            score=score,
            total_errors=errors,
            total_lines=total_lines,
            error_density=round(density, 2),
            details={"python_files_analysed": len(py_files)},
        )

    def _run_ruff(self, project_path: Path) -> int | None:
        """Run ruff check and return error count, or None if ruff unavailable."""
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
            return len(data)
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

    def _compute_score(self, errors: int, total_lines: int) -> float:
        density = errors / max(total_lines, 1) * 1000
        return round(max(0.0, 1.0 - min(density / _DENSITY_CEILING, 1.0)), 4)
