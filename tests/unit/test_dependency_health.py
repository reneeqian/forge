"""Unit tests for DependencyHealthCollector — COL-003."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.collectors.dependency_health import DependencyHealthCollector


@pytest.fixture()
def collector() -> DependencyHealthCollector:
    return DependencyHealthCollector()


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A minimal project dir with a requirements.txt so the early-exit guard passes."""
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n")
    return tmp_path


def _pip_audit_output(packages: list[dict]) -> str:
    """Build a minimal pip-audit JSON response."""
    return json.dumps({"dependencies": packages})


class TestDependencyHealthCollector:
    def test_skips_nonexistent_path(self, collector, tmp_path):
        result = collector.collect(tmp_path / "nope")
        assert result.skipped

    def test_skips_when_no_requirements_file(self, collector, tmp_path):
        result = collector.collect(tmp_path)
        assert result.skipped
        assert "requirements" in (result.skip_reason or "").lower()

    def test_skips_when_pip_audit_not_available(self, collector, project):
        with patch.object(collector, "_run_pip_audit", return_value=None):
            result = collector.collect(project)
        assert result.skipped
        assert "pip-audit not found" in (result.skip_reason or "")

    def test_perfect_score_when_no_vulnerabilities(self, collector, project):
        packages = [
            {"name": "requests", "version": "2.31.0", "vulns": []},
            {"name": "numpy", "version": "1.26.0", "vulns": []},
        ]
        with patch.object(collector, "_run_pip_audit", return_value=_pip_audit_output(packages)):
            result = collector.collect(project)
        assert result.score == 1.0
        assert result.total_packages == 2
        assert result.vulnerable_packages == 0
        assert result.vulnerabilities == []

    def test_reduced_score_for_one_vulnerability(self, collector, project):
        packages = [
            {"name": "requests", "version": "2.1.0", "vulns": [
                {"id": "GHSA-abc", "description": "SSRF vulnerability", "fix_versions": ["2.31.0"]}
            ]},
            {"name": "numpy", "version": "1.26.0", "vulns": []},
        ]
        with patch.object(collector, "_run_pip_audit", return_value=_pip_audit_output(packages)):
            result = collector.collect(project)
        assert result.score == pytest.approx(0.85, abs=0.01)
        assert result.vulnerable_packages == 1
        assert len(result.vulnerabilities) == 1
        assert result.vulnerabilities[0]["package"] == "requests"

    def test_score_zero_for_many_vulnerabilities(self, collector, project):
        packages = [
            {"name": f"pkg{i}", "version": "0.1", "vulns": [
                {"id": f"CVE-{i}", "description": "vuln", "fix_versions": []}
            ]}
            for i in range(10)
        ]
        with patch.object(collector, "_run_pip_audit", return_value=_pip_audit_output(packages)):
            result = collector.collect(project)
        assert result.score == 0.0

    def test_none_score_when_no_packages_audited(self, collector, project):
        with patch.object(
            collector, "_run_pip_audit", return_value=json.dumps({"dependencies": []})
        ):
            result = collector.collect(project)
        assert result.score is None

    def test_handles_malformed_json(self, collector, project):
        with patch.object(collector, "_run_pip_audit", return_value="not json at all"):
            result = collector.collect(project)
        assert result.skipped
        assert "parse" in (result.skip_reason or "").lower()

    def test_finds_requirements_txt(self, collector, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("requests==2.31.0\n")
        found = collector._find_requirements(tmp_path)
        assert found == req_file

    def test_prefers_requirements_txt_over_none(self, collector, tmp_path):
        """No requirements file → returns None."""
        found = collector._find_requirements(tmp_path)
        assert found is None

    def test_vulnerability_description_truncated(self, collector, project):
        long_desc = "x" * 500
        packages = [
            {"name": "pkg", "version": "0.1", "vulns": [
                {"id": "CVE-1", "description": long_desc, "fix_versions": []}
            ]}
        ]
        with patch.object(collector, "_run_pip_audit", return_value=_pip_audit_output(packages)):
            result = collector.collect(project)
        assert len(result.vulnerabilities[0]["description"]) <= 200
