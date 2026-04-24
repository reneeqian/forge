"""Type coverage collector — REQ-012.

Uses mypy to count type errors. Count-based (not density-based) because
mypy errors cascade — one badly-typed module can surface many downstream errors.
Falls back gracefully if mypy is not installed (REQ-010).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from forge.models import TypeCoverageResult

_ERROR_CEILING = 100  # 100+ mypy errors → score 0.0


class TypeCoverageCollector:
    """Collect type-checking metrics via mypy."""

    def collect(self, project_path: Path) -> TypeCoverageResult:
        project_path = project_path.resolve()

        if not project_path.exists():
            return TypeCoverageResult(
                skipped=True,
                skip_reason=f"Project path does not exist: {project_path}",
            )

        py_files = [
            f for f in project_path.rglob("*.py")
            if "__pycache__" not in f.parts
        ]
        if not py_files:
            return TypeCoverageResult(
                skipped=True,
                skip_reason="No Python source files found",
            )

        result = self._run_mypy(project_path)
        if result is None:
            return TypeCoverageResult(
                skipped=True,
                skip_reason="mypy not found — install with: pip install mypy",
            )

        total_errors, files_checked = result
        score = self._compute_score(total_errors)

        return TypeCoverageResult(
            score=score,
            total_errors=total_errors,
            files_checked=files_checked,
            details={"python_files_found": len(py_files)},
        )

    def _run_mypy(self, project_path: Path) -> tuple[int, int] | None:
        """Run mypy and return (error_count, files_checked), or None if unavailable."""
        try:
            proc = subprocess.run(
                [
                    sys.executable, "-m", "mypy",
                    str(project_path),
                    "--ignore-missing-imports",
                    "--no-error-summary",
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            # mypy exits 0 (success), 1 (type errors found), 2 (fatal error)
            if proc.returncode == 2:
                return None
            return self._parse_mypy_stdout(proc.stdout)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _parse_mypy_stdout(self, stdout: str) -> tuple[int, int]:
        error_lines = [ln for ln in stdout.splitlines() if ": error:" in ln]
        file_paths = {ln.split(":")[0] for ln in error_lines if ln}
        return len(error_lines), len(file_paths)

    def _compute_score(self, total_errors: int) -> float:
        return round(max(0.0, 1.0 - min(total_errors / _ERROR_CEILING, 1.0)), 4)
