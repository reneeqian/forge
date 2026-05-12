"""Dependency health collector — COL-003.

Uses pip-audit to detect known CVEs in a project's dependencies.
Falls back gracefully when pip-audit is absent (SYS-002).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from forge.models import DependencyHealthResult


class DependencyHealthCollector:
    """Audit project dependencies for known CVEs using pip-audit."""

    def collect(self, project_path: Path) -> DependencyHealthResult:
        project_path = project_path.resolve()

        if not project_path.exists():
            return DependencyHealthResult(
                skipped=True,
                skip_reason=f"Project path does not exist: {project_path}",
            )

        # Locate a requirements file or pyproject.toml to audit
        req_file = self._find_requirements(project_path)
        has_pyproject = (project_path / "pyproject.toml").exists()

        if req_file is None and not has_pyproject:
            return DependencyHealthResult(
                skipped=True,
                skip_reason="No requirements.txt or pyproject.toml found",
            )

        output = self._run_pip_audit(project_path, req_file)
        if output is None:
            return DependencyHealthResult(
                skipped=True,
                skip_reason="pip-audit not found — install it with: pip install pip-audit",
            )

        return self._parse_output(output)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _find_requirements(self, project_path: Path) -> Path | None:
        """Return the best requirements file to audit, or None to audit the env."""
        for name in ("requirements.txt", "requirements-base.txt", "requirements/base.txt"):
            candidate = project_path / name
            if candidate.exists():
                return candidate
        return None  # pip-audit will audit the current environment / pyproject.toml

    def _run_pip_audit(self, project_path: Path, req_file: Path | None) -> str | None:
        """Run pip-audit with JSON output. Returns raw JSON string or None."""
        cmd = [sys.executable, "-m", "pip_audit", "--format=json", "--progress-spinner=off"]

        if req_file:
            cmd += ["-r", str(req_file)]
        else:
            # Audit the project as installed (reads pyproject.toml / setup.cfg)
            cmd += ["--local"]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(project_path),
                timeout=120,
            )
            # pip-audit exits 1 when vulnerabilities are found — that's expected
            return proc.stdout
        except FileNotFoundError:
            return None
        except subprocess.TimeoutExpired:
            return None

    def _parse_output(self, raw_json: str) -> DependencyHealthResult:
        """Parse pip-audit JSON output into a DependencyHealthResult."""
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            return DependencyHealthResult(
                skipped=True,
                skip_reason="Could not parse pip-audit output",
            )

        dependencies = data.get("dependencies", [])
        total = len(dependencies)
        vulns: list[dict] = []

        for dep in dependencies:
            for vuln in dep.get("vulns", []):
                vulns.append({
                    "package": dep.get("name"),
                    "version": dep.get("version"),
                    "id": vuln.get("id"),
                    "description": vuln.get("description", "")[:200],
                    "fix_versions": vuln.get("fix_versions", []),
                })

        vulnerable_packages = len({v["package"] for v in vulns})
        score = self._compute_score(total, vulnerable_packages)

        return DependencyHealthResult(
            score=score,
            total_packages=total,
            vulnerable_packages=vulnerable_packages,
            vulnerabilities=vulns,
            details={"requirements_file": "environment" if total == 0 else str(total) + " pkgs"},
        )

    def _compute_score(self, total: int, vulnerable: int) -> float | None:
        """Score: 1.0 for zero vulns, decreasing by 0.15 per vulnerable package."""
        if total == 0:
            return None  # Nothing audited
        if vulnerable == 0:
            return 1.0
        penalty = min(vulnerable * 0.15, 1.0)
        return round(max(1.0 - penalty, 0.0), 4)
