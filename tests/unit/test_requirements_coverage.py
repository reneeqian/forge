"""Unit tests for RequirementsCoverageCollector — COL-004."""

import textwrap
from pathlib import Path

import pytest

from forge.collectors.requirements_coverage import RequirementsCoverageCollector


@pytest.fixture()
def collector() -> RequirementsCoverageCollector:
    return RequirementsCoverageCollector()


class TestRequirementsCoverageCollector:
    def test_skips_nonexistent_path(self, collector, tmp_path):
        result = collector.collect(tmp_path / "nope")
        assert result.skipped
        assert "does not exist" in (result.skip_reason or "")

    def test_skips_when_no_tags_in_source(self, collector, tmp_path):
        """No REQ tags in source → skip with helpful message."""
        src = tmp_path / "src" / "mylib"
        src.mkdir(parents=True)
        (src / "core.py").write_text("def add(a, b): return a + b\n")
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_core.py").write_text("def test_add(): assert True\n")

        result = collector.collect(tmp_path)
        assert result.skipped
        assert "No requirement tags" in (result.skip_reason or "")

    def test_full_coverage_when_all_reqs_in_tests(self, collector, tmp_path):
        src = tmp_path / "src" / "mylib"
        src.mkdir(parents=True)
        (src / "core.py").write_text("# REQ-001\ndef add(a, b): return a + b\n")

        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_core.py").write_text("# REQ-001\ndef test_add(): assert True\n")

        result = collector.collect(tmp_path)
        assert not result.skipped
        assert result.score == 1.0
        assert result.total_requirements == 1
        assert result.covered_requirements == 1
        assert result.uncovered == []

    def test_partial_coverage(self, collector, tmp_path):
        src = tmp_path / "src" / "mylib"
        src.mkdir(parents=True)
        (src / "core.py").write_text("# REQ-001\n# REQ-002\ndef f(): pass\n")

        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_core.py").write_text("# REQ-001\ndef test_f(): assert True\n")

        result = collector.collect(tmp_path)
        assert result.score == pytest.approx(0.5, abs=0.01)
        assert result.total_requirements == 2
        assert result.covered_requirements == 1
        assert "REQ-002" in result.uncovered

    def test_zero_coverage(self, collector, tmp_path):
        src = tmp_path / "src" / "mylib"
        src.mkdir(parents=True)
        (src / "core.py").write_text("# REQ-001\ndef f(): pass\n")

        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_core.py").write_text("def test_f(): assert True\n")

        result = collector.collect(tmp_path)
        assert result.score == 0.0
        assert result.uncovered == ["REQ-001"]

    def test_tags_in_docs_count_as_source(self, collector, tmp_path):
        """REQ tags in docs/ are treated as source requirements."""
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "REQUIREMENTS.md").write_text("## REQ-001\n## REQ-002\n")

        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_stuff.py").write_text("# REQ-001\ndef test_x(): pass\n")

        result = collector.collect(tmp_path)
        assert result.total_requirements == 2
        assert result.covered_requirements == 1

    def test_custom_tag_pattern(self, collector, tmp_path):
        src = tmp_path / "src" / "pkg"
        src.mkdir(parents=True)
        (src / "main.py").write_text("# TICKET-42\ndef f(): pass\n")

        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_main.py").write_text("# TICKET-42\ndef test_f(): pass\n")

        result = collector.collect(tmp_path, tag_pattern=r"TICKET-\d+")
        assert result.score == 1.0

    def test_duplicate_tags_counted_once(self, collector, tmp_path):
        src = tmp_path / "src" / "pkg"
        src.mkdir(parents=True)
        # REQ-001 appears three times — should count as 1 unique requirement
        (src / "main.py").write_text("# REQ-001\n# REQ-001\n# REQ-001\ndef f(): pass\n")

        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_main.py").write_text("# REQ-001\ndef test_f(): pass\n")

        result = collector.collect(tmp_path)
        assert result.total_requirements == 1


class TestRequirementsCoverageYamlMode:
    """Tests for YAML-driven requirements coverage (preferred mode)."""

    YAML_CONTENT = """\
metadata:
  project: mylib

requirements:
  - id: DAT-001
    title: Data Validation
  - id: DAT-002
    title: Boundary Checks
  - id: SYS-001
    title: Interface Consistency
"""

    def _make_yaml_project(self, tmp_path, yaml_content=None):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "requirements.yaml").write_text(yaml_content or self.YAML_CONTENT)
        tests = tmp_path / "tests"
        tests.mkdir()
        return tmp_path

    def test_uses_yaml_ids_as_canonical_set(self, collector, tmp_path):
        self._make_yaml_project(tmp_path)
        (tmp_path / "tests" / "test_data.py").write_text(
            "# DAT-001\n# DAT-002\n# SYS-001\ndef test_x(): pass\n"
        )
        result = collector.collect(tmp_path)
        assert result.total_requirements == 3
        assert result.covered_requirements == 3
        assert result.score == 1.0
        assert result.details.get("mode") == "yaml"

    def test_yaml_partial_coverage(self, collector, tmp_path):
        self._make_yaml_project(tmp_path)
        (tmp_path / "tests" / "test_data.py").write_text(
            "# DAT-001\ndef test_x(): pass\n"
        )
        result = collector.collect(tmp_path)
        assert result.total_requirements == 3
        assert result.covered_requirements == 1
        assert result.score == pytest.approx(1 / 3, abs=0.01)
        assert "DAT-002" in result.uncovered
        assert "SYS-001" in result.uncovered

    def test_yaml_zero_coverage(self, collector, tmp_path):
        self._make_yaml_project(tmp_path)
        (tmp_path / "tests" / "test_data.py").write_text("def test_x(): pass\n")
        result = collector.collect(tmp_path)
        assert result.score == 0.0
        assert result.covered_requirements == 0
        assert len(result.uncovered) == 3

    def test_yaml_details_include_requirements_file(self, collector, tmp_path):
        self._make_yaml_project(tmp_path)
        (tmp_path / "tests" / "test_data.py").write_text("# DAT-001\ndef test_x(): pass\n")
        result = collector.collect(tmp_path)
        assert "requirements_file" in result.details
        assert "requirements.yaml" in result.details["requirements_file"]

    def test_yaml_not_required_to_be_in_docs(self, collector, tmp_path):
        """requirements.yaml at project root also works."""
        (tmp_path / "requirements.yaml").write_text(self.YAML_CONTENT)
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_x.py").write_text("# DAT-001\ndef test_x(): pass\n")
        result = collector.collect(tmp_path)
        assert result.total_requirements == 3

    def test_yaml_takes_priority_over_regex(self, collector, tmp_path):
        """When requirements.yaml exists, regex mode is not used."""
        self._make_yaml_project(tmp_path)
        src = tmp_path / "src"
        src.mkdir()
        # REQ-001 in source — but no requirements.yaml has REQ- IDs
        (src / "core.py").write_text("# REQ-001\ndef f(): pass\n")
        (tmp_path / "tests" / "test_core.py").write_text("# REQ-001\ndef test_f(): pass\n")
        result = collector.collect(tmp_path)
        # YAML has DAT/SYS IDs only; REQ-001 is irrelevant in yaml mode
        assert result.total_requirements == 3
        assert result.details.get("mode") == "yaml"

    def test_empty_yaml_skips(self, collector, tmp_path):
        """An empty or ID-free requirements YAML should skip."""
        self._make_yaml_project(tmp_path, yaml_content="metadata:\n  project: empty\n")
        result = collector.collect(tmp_path)
        assert result.skipped
