"""Code complexity collector — REQ-003.

Uses radon to compute cyclomatic complexity and maintainability index.
Falls back gracefully if radon is not installed (REQ-010).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from forge.models import ComplexityResult


# Cyclomatic complexity thresholds (per radon scale A–F)
# We normalise against a "bad" ceiling so scores feel intuitive.
_CC_CEILING = 10.0   # avg CC ≥ 10 → score 0.0
_CC_FLOOR = 1.0      # avg CC ≤ 1 → score 1.0

# Maintainability index: radon scores 0–100 (100 = best)
_MI_CEILING = 100.0


class ComplexityCollector:
    """Collect code complexity metrics using radon."""

    def collect(self, project_path: Path) -> ComplexityResult:
        project_path = project_path.resolve()

        if not project_path.exists():
            return ComplexityResult(
                skipped=True,
                skip_reason=f"Project path does not exist: {project_path}",
            )

        py_files = self._find_src_files(project_path)

        if not py_files:
            return ComplexityResult(
                skipped=True,
                skip_reason="No Python source files found (excluding tests)",
            )

        avg_cc = self._compute_avg_cyclomatic(project_path)
        avg_mi = self._compute_avg_mi(project_path)

        if avg_cc is None and avg_mi is None:
            return ComplexityResult(
                skipped=True,
                skip_reason="radon not found — install it with: pip install radon",
            )

        score = self._compute_score(avg_cc, avg_mi)

        return ComplexityResult(
            score=score,
            avg_cyclomatic=avg_cc,
            maintainability_index=avg_mi,
            details={"python_files_analysed": len(py_files)},
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _find_src_files(self, project_path: Path) -> list[Path]:
        """Return Python source files, excluding tests and __pycache__."""
        result = []
        for f in project_path.rglob("*.py"):
            rel_parts = f.relative_to(project_path).parts
            if (
                "__pycache__" not in rel_parts
                and not any(part.startswith("test") for part in rel_parts)
                and f.name != "conftest.py"
            ):
                result.append(f)
        return result

    def _find_src_dir(self, project_path: Path) -> list[Path] | None:
        """Return source Python files for the project, or None if none found."""
        files = self._find_src_files(project_path)
        return files if files else None

    def _run_radon(self, args: list[str], cwd: Path) -> str | None:
        """Run radon as a subprocess, return stdout or None on error."""
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "radon"] + args,
                capture_output=True,
                text=True,
                cwd=str(cwd),
                timeout=60,
            )
            return proc.stdout
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _compute_avg_cyclomatic(self, project_path: Path) -> float | None:
        """Return average cyclomatic complexity across all functions/methods."""
        output = self._run_radon(["cc", "-s", "-a", str(project_path)], project_path)
        if output is None:
            return None

        import re
        # radon outputs "Average complexity: B (3.14)" at the end
        match = re.search(r"Average complexity:\s+\w+\s+\(([0-9.]+)\)", output)
        if match:
            return round(float(match.group(1)), 2)
        return None

    def _compute_avg_mi(self, project_path: Path) -> float | None:
        """Return average maintainability index (0–100)."""
        output = self._run_radon(["mi", "-s", str(project_path)], project_path)
        if output is None:
            return None

        import re
        scores = [float(m) for m in re.findall(r"-\s+([0-9.]+)$", output, re.MULTILINE)]
        if not scores:
            return None
        return round(sum(scores) / len(scores), 2)

    def _compute_score(
        self, avg_cc: float | None, avg_mi: float | None
    ) -> float | None:
        """Blend CC and MI into a 0–1 score (higher = better)."""
        parts: list[float] = []

        if avg_cc is not None:
            # Invert: low CC is good
            cc_score = 1.0 - min(max(avg_cc - _CC_FLOOR, 0) / (_CC_CEILING - _CC_FLOOR), 1.0)
            parts.append(cc_score)

        if avg_mi is not None:
            mi_score = min(avg_mi / _MI_CEILING, 1.0)
            parts.append(mi_score)

        if not parts:
            return None
        return round(sum(parts) / len(parts), 4)
