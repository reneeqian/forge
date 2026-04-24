"""Dead code collector — REQ-013.

Uses vulture to detect unused code. Supports vulture's JSON output (v2.3+)
with a plain-text line-count fallback.
Falls back gracefully if vulture is not installed (REQ-010).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from forge.models import DeadCodeResult

_DENSITY_CEILING = 20.0  # unused items per 1000 lines → score 0.0
_MIN_CONFIDENCE = 80


class DeadCodeCollector:
    """Collect dead code metrics via vulture."""

    def collect(self, project_path: Path) -> DeadCodeResult:
        project_path = project_path.resolve()

        if not project_path.exists():
            return DeadCodeResult(
                skipped=True,
                skip_reason=f"Project path does not exist: {project_path}",
            )

        py_files = [
            f for f in project_path.rglob("*.py")
            if "__pycache__" not in f.parts
        ]
        if not py_files:
            return DeadCodeResult(
                skipped=True,
                skip_reason="No Python source files found",
            )

        total_lines = self._count_python_lines(py_files)
        unused = self._run_vulture(project_path)

        if unused is None:
            return DeadCodeResult(
                skipped=True,
                skip_reason="vulture not found — install with: pip install vulture",
            )

        density = unused / max(total_lines, 1) * 1000
        score = self._compute_score(unused, total_lines)

        return DeadCodeResult(
            score=score,
            unused_items=unused,
            total_lines=total_lines,
            unused_density=round(density, 2),
            details={"python_files_analysed": len(py_files), "min_confidence": _MIN_CONFIDENCE},
        )

    def _run_vulture(self, project_path: Path) -> int | None:
        """Return unused item count, or None if vulture is unavailable."""
        # Try JSON output first (vulture 2.3+)
        try:
            proc = subprocess.run(
                [
                    sys.executable, "-m", "vulture",
                    str(project_path),
                    f"--min-confidence={_MIN_CONFIDENCE}",
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode in (0, 1):
                stdout = proc.stdout.strip()
                if stdout:
                    try:
                        data = json.loads(stdout)
                        return len(data)
                    except json.JSONDecodeError:
                        pass
                else:
                    return 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        # Fallback: plain-text output — one finding per line
        try:
            proc = subprocess.run(
                [
                    sys.executable, "-m", "vulture",
                    str(project_path),
                    f"--min-confidence={_MIN_CONFIDENCE}",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if proc.returncode not in (0, 1):
                return None
            lines = [
                ln for ln in proc.stdout.splitlines()
                if re.search(r"unused\s+(import|variable|function|class|method|attribute|property)", ln)
            ]
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

    def _compute_score(self, unused: int, total_lines: int) -> float:
        density = unused / max(total_lines, 1) * 1000
        return round(max(0.0, 1.0 - min(density / _DENSITY_CEILING, 1.0)), 4)
