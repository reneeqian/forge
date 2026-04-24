"""Test metrics collector — REQ-002.

Runs pytest with coverage.py in a subprocess and parses the results.
Works on any project that has a pytest-compatible test suite.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from forge.models import TestMetricsResult


class TestMetricsCollector:
    """Collect test pass rate and line coverage via pytest + coverage.py."""

    def collect(
        self, project_path: Path, python_executable: str = ""
    ) -> TestMetricsResult:
        """Run pytest on *project_path* and return a TestMetricsResult.

        Uses --tb=no for speed and --json-report when available, otherwise
        falls back to parsing pytest's exit code + coverage JSON.
        """
        project_path = project_path.resolve()

        if not project_path.exists():
            return TestMetricsResult(
                skipped=True,
                skip_reason=f"Project path does not exist: {project_path}",
            )

        tests_dir = project_path / "tests"
        if not tests_dir.exists():
            # Also accept a flat layout (test_*.py at root)
            test_files = list(project_path.glob("test_*.py"))
            if not test_files:
                return TestMetricsResult(
                    skipped=True,
                    skip_reason="No tests directory or test_*.py files found",
                )

        python = python_executable or self._find_python(project_path)

        # Determine the source package directory
        src_dir = self._find_src_dir(project_path)

        # Build pytest command
        cov_source = src_dir.name if src_dir else "."
        coverage_json = project_path / ".forge_coverage.json"

        cmd = [
            python, "-m", "pytest",
            str(project_path),
            "--tb=no",
            "-q",
            f"--cov={cov_source}",
            "--cov-report=json:" + str(coverage_json),
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(project_path),
                timeout=120,
            )
        except FileNotFoundError:
            return TestMetricsResult(
                skipped=True,
                skip_reason="pytest not found — install it in the target project's environment",
            )
        except subprocess.TimeoutExpired:
            return TestMetricsResult(
                skipped=True,
                skip_reason="pytest timed out after 120 seconds",
            )

        # Parse pytest stdout for counts
        total, passed, failed, skipped_tests = self._parse_pytest_output(
            proc.stdout, proc.returncode
        )

        # Parse coverage JSON
        line_coverage = self._parse_coverage_json(coverage_json)

        # Clean up temp coverage file
        if coverage_json.exists():
            coverage_json.unlink()

        pass_rate = (passed / total) if total > 0 else None
        score = self._compute_score(pass_rate, line_coverage)

        return TestMetricsResult(
            score=score,
            total=total,
            passed=passed,
            failed=failed,
            skipped_tests=skipped_tests,
            pass_rate=pass_rate,
            line_coverage=line_coverage,
            details={"pytest_exit_code": proc.returncode},
        )

    # ── helpers ──────────────────────────────────────────────────────────────

    def _find_python(self, project_path: Path) -> str:
        """Return the best Python interpreter for the project.

        Priority:
        1. .venv or venv inside the project directory
        2. Conda env named in environment.yaml / environment.yml
        3. sys.executable (forge's own interpreter)
        """
        for venv_dir in (".venv", "venv", ".env"):
            candidate = project_path / venv_dir / "bin" / "python"
            if candidate.exists():
                return str(candidate)

        for fname in ("environment.yaml", "environment.yml"):
            env_file = project_path / fname
            if env_file.exists():
                try:
                    text = env_file.read_text(encoding="utf-8")
                except OSError:
                    continue
                for line in text.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("name:"):
                        env_name = stripped.split(":", 1)[1].strip()
                        for base in (
                            Path.home() / "miniconda3",
                            Path.home() / "anaconda3",
                            Path("/opt/miniconda3"),
                            Path("/opt/anaconda3"),
                        ):
                            candidate = base / "envs" / env_name / "bin" / "python"
                            if candidate.exists():
                                return str(candidate)
                        break

        return sys.executable

    def _find_src_dir(self, project_path: Path) -> Path | None:
        """Return the most likely source directory (src/ layout or package dir)."""
        src = project_path / "src"
        if src.is_dir():
            # src-layout: find the first Python package inside src/
            for child in src.iterdir():
                if child.is_dir() and (child / "__init__.py").exists():
                    return child
            return src

        # Flat layout: find the first package directory at root (not tests)
        for child in sorted(project_path.iterdir()):
            if (
                child.is_dir()
                and (child / "__init__.py").exists()
                and child.name not in ("tests", "test", "docs", "scripts")
                and not child.name.startswith(".")
            ):
                return child
        return None

    def _parse_pytest_output(
        self, stdout: str, exit_code: int
    ) -> tuple[int, int, int, int]:
        """Parse pytest summary line like '5 passed, 1 failed, 2 skipped'."""
        import re

        passed = failed = skipped = 0
        for line in stdout.splitlines():
            # Match lines like: "3 passed", "1 failed", "2 skipped" (may be combined)
            passed += sum(int(m) for m in re.findall(r"(\d+) passed", line))
            failed += sum(int(m) for m in re.findall(r"(\d+) failed", line))
            skipped += sum(int(m) for m in re.findall(r"(\d+) skipped", line))

        # If nothing parsed but exit code signals failure, report at least 1 failure
        if passed == 0 and failed == 0 and exit_code not in (0, 5):
            failed = 1

        total = passed + failed
        return total, passed, failed, skipped

    def _parse_coverage_json(self, coverage_file: Path) -> float | None:
        """Extract total line coverage % from coverage.py JSON report."""
        if not coverage_file.exists():
            return None
        try:
            data = json.loads(coverage_file.read_text())
            pct = data.get("totals", {}).get("percent_covered")
            return round(float(pct), 2) if pct is not None else None
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def _compute_score(
        self, pass_rate: float | None, line_coverage: float | None
    ) -> float | None:
        """Blend pass rate (70%) and coverage (30%) into a 0–1 score."""
        if pass_rate is None and line_coverage is None:
            return None
        pr = pass_rate if pass_rate is not None else 0.0
        cov = (line_coverage / 100.0) if line_coverage is not None else 0.0
        weight_pr = 0.7 if line_coverage is not None else 1.0
        weight_cov = 0.3 if pass_rate is not None else 1.0
        total_w = weight_pr + weight_cov
        return round((pr * weight_pr + cov * weight_cov) / total_w, 4)
