"""Mutation testing collector — REQ-014.

Uses mutmut to compute the mutation score (killed / total mutants).
Disabled by default — mutation testing is very slow on large projects.
Enable via forge.toml: [collectors.mutation_testing] enabled = true (REQ-015).
Falls back gracefully if mutmut is not installed (REQ-010).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from forge.models import MutationTestingResult

_MUTMUT_TIMEOUT = 1800  # 30 minutes


class MutationTestingCollector:
    """Collect mutation testing metrics via mutmut."""

    def collect(self, project_path: Path, enabled: bool = False) -> MutationTestingResult:
        if not enabled:
            return MutationTestingResult(
                skipped=True,
                skip_reason=(
                    "Disabled by default; set [collectors.mutation_testing] enabled = true "
                    "in forge.toml"
                ),
            )

        project_path = project_path.resolve()

        if not project_path.exists():
            return MutationTestingResult(
                skipped=True,
                skip_reason=f"Project path does not exist: {project_path}",
            )

        src_dir = self._find_src_dir(project_path)
        if src_dir is None:
            return MutationTestingResult(
                skipped=True,
                skip_reason="No src/ or source directory found for mutation testing",
            )

        result = self._run_mutmut(project_path, src_dir)
        if result is None:
            return MutationTestingResult(
                skipped=True,
                skip_reason="mutmut not found — install with: pip install mutmut",
            )

        killed, total = result
        if total == 0:
            return MutationTestingResult(
                skipped=True,
                skip_reason="mutmut generated no mutants (check that tests pass first)",
            )

        mutation_score = killed / total
        return MutationTestingResult(
            score=round(mutation_score, 4),
            total_mutants=total,
            killed_mutants=total - (total - killed),
            mutation_score=round(mutation_score, 4),
            details={"src_dir": str(src_dir)},
        )

    def _find_src_dir(self, project_path: Path) -> Path | None:
        """Return the primary source directory to mutate."""
        for candidate in ("src", project_path.name, "lib", "app"):
            p = project_path / candidate
            if p.is_dir() and any(p.rglob("*.py")):
                return p
        # Fall back to project root if it has Python files
        if any(f for f in project_path.glob("*.py") if f.name != "setup.py"):
            return project_path
        return None

    def _run_mutmut(self, project_path: Path, src_dir: Path) -> tuple[int, int] | None:
        """Run mutmut and return (killed, total), or None if unavailable."""
        try:
            subprocess.run(
                [
                    sys.executable, "-m", "mutmut", "run",
                    "--paths-to-mutate", str(src_dir),
                ],
                capture_output=True,
                text=True,
                cwd=str(project_path),
                timeout=_MUTMUT_TIMEOUT,
            )
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            # Still try to read partial results
            pass

        try:
            results_proc = subprocess.run(
                [sys.executable, "-m", "mutmut", "results"],
                capture_output=True,
                text=True,
                cwd=str(project_path),
                timeout=30,
            )
            return self._parse_mutmut_results(results_proc.stdout)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    def _parse_mutmut_results(self, stdout: str) -> tuple[int, int] | None:
        # Try JSON output from newer mutmut versions
        try:
            import json
            data = json.loads(stdout)
            if isinstance(data, dict):
                killed = data.get("killed", 0)
                total = data.get("total", 0)
                return int(killed), int(total)
        except (ValueError, TypeError):
            pass

        # Plain text: "Killed mutants: 42/50"
        match = re.search(r"Killed mutants[:\s]+(\d+)/(\d+)", stdout, re.IGNORECASE)
        if match:
            return int(match.group(1)), int(match.group(2))

        # Summarise from status lines: "killed: 42", "survived: 8"
        killed_match = re.search(r"killed[:\s]+(\d+)", stdout, re.IGNORECASE)
        survived_match = re.search(r"survived[:\s]+(\d+)", stdout, re.IGNORECASE)
        if killed_match and survived_match:
            killed = int(killed_match.group(1))
            survived = int(survived_match.group(1))
            return killed, killed + survived

        return None
