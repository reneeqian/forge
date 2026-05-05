"""Requirements coverage collector — COL-004.

Two modes depending on what the target project provides:

YAML mode (preferred): reads requirement IDs from a machine-readable
  requirements file (docs/requirements.yaml or similar). Checks which
  IDs are referenced in at least one test file.

Regex fallback: original behaviour — scans source files for tags
  matching tag_pattern and checks which appear in test files.
"""

from __future__ import annotations

import re
from pathlib import Path

from forge.models import RequirementsCoverageResult

# Candidate locations for a machine-readable requirements file, in priority order.
_REQUIREMENTS_YAML_CANDIDATES = [
    "docs/requirements.yaml",
    "docs/requirements.yml",
    "requirements.yaml",
    "requirements.yml",
]


class RequirementsCoverageCollector:
    """Trace requirement IDs from a requirements file (or source tags) into tests."""

    DEFAULT_PATTERN = r"[A-Z]+-\d+"

    def collect(
        self,
        project_path: Path,
        tag_pattern: str = DEFAULT_PATTERN,
    ) -> RequirementsCoverageResult:
        project_path = project_path.resolve()

        if not project_path.exists():
            return RequirementsCoverageResult(
                skipped=True,
                skip_reason=f"Project path does not exist: {project_path}",
            )

        req_file = self._find_requirements_yaml(project_path)

        if req_file is not None:
            return self._collect_yaml_mode(project_path, req_file)

        return self._collect_regex_mode(project_path, tag_pattern)

    # ── YAML mode ────────────────────────────────────────────────────────────

    def _collect_yaml_mode(
        self, project_path: Path, req_file: Path
    ) -> RequirementsCoverageResult:
        """Canonical mode: IDs come from the requirements YAML file."""
        all_ids = self._parse_requirements_yaml(req_file)

        if not all_ids:
            return RequirementsCoverageResult(
                skipped=True,
                skip_reason=f"No requirement IDs found in {req_file.relative_to(project_path)}",
            )

        covered = self._scan_test_files_for_ids(project_path, all_ids)
        uncovered = sorted(all_ids - covered)
        coverage_ratio = len(covered) / len(all_ids)

        return RequirementsCoverageResult(
            score=round(coverage_ratio, 4),
            total_requirements=len(all_ids),
            covered_requirements=len(covered),
            uncovered=uncovered,
            details={
                "mode": "yaml",
                "requirements_file": str(req_file.relative_to(project_path)),
                "covered": sorted(covered),
            },
        )

    def _find_requirements_yaml(self, project_path: Path) -> Path | None:
        """Return the first requirements YAML file found, or None."""
        for candidate in _REQUIREMENTS_YAML_CANDIDATES:
            path = project_path / candidate
            if path.exists():
                return path
        return None

    def _parse_requirements_yaml(self, req_file: Path) -> set[str]:
        """Extract all `- id: SOME-001` values from a requirements YAML file."""
        try:
            text = req_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return set()
        # Matches lines like:  "  - id: DAT-001"  anywhere in the file
        return set(re.findall(r"^\s*-\s+id:\s+(\S+)", text, re.MULTILINE))

    def _scan_test_files_for_ids(
        self, project_path: Path, req_ids: set[str]
    ) -> set[str]:
        """Return the subset of req_ids that appear in at least one test file."""
        covered: set[str] = set()
        remaining = set(req_ids)

        for py_file in project_path.rglob("*.py"):
            if not remaining:
                break
            if "__pycache__" in py_file.relative_to(project_path).parts:
                continue

            rel_parts = py_file.relative_to(project_path).parts
            is_test = (
                any(part.startswith("test") or part == "tests" for part in rel_parts)
                or py_file.name.startswith("test_")
                or py_file.name == "conftest.py"
            )
            if not is_test:
                continue

            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for req_id in list(remaining):
                if req_id in text:
                    covered.add(req_id)
                    remaining.discard(req_id)

        return covered

    # ── Regex fallback mode ───────────────────────────────────────────────────

    def _collect_regex_mode(
        self, project_path: Path, tag_pattern: str
    ) -> RequirementsCoverageResult:
        """Fallback: scan source files for tags matching tag_pattern."""
        source_tags = self._scan_tags(project_path, tag_pattern, include_tests=False)
        test_tags = self._scan_tags(project_path, tag_pattern, include_tests=True)

        if not source_tags:
            return RequirementsCoverageResult(
                skipped=True,
                skip_reason=(
                    f"No requirement tags matching '{tag_pattern}' found in source files. "
                    "Add tags like '# SYS-001' to your source or docs."
                ),
            )

        covered = source_tags & test_tags
        uncovered = sorted(source_tags - test_tags)
        coverage_ratio = len(covered) / len(source_tags)

        return RequirementsCoverageResult(
            score=round(coverage_ratio, 4),
            total_requirements=len(source_tags),
            covered_requirements=len(covered),
            uncovered=uncovered,
            details={
                "mode": "regex",
                "tag_pattern": tag_pattern,
                "covered": sorted(covered),
            },
        )

    def _scan_tags(
        self, project_path: Path, pattern: str, include_tests: bool
    ) -> set[str]:
        """Return all unique tags found in the relevant file set."""
        tags: set[str] = set()
        compiled = re.compile(pattern)

        for py_file in project_path.rglob("*.py"):
            if "__pycache__" in py_file.parts:
                continue

            rel_parts = py_file.relative_to(project_path).parts
            is_test_file = any(
                part.startswith("test") or part == "tests"
                for part in rel_parts
            ) or py_file.name.startswith("test_") or py_file.name == "conftest.py"

            if include_tests != is_test_file:
                continue

            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                tags.update(compiled.findall(text))
            except OSError:
                continue

        # Also scan docs/ directory for requirements documents
        if not include_tests:
            docs_dir = project_path / "docs"
            if docs_dir.exists():
                for doc_file in docs_dir.rglob("*"):
                    if doc_file.is_file() and doc_file.suffix in (".md", ".txt", ".rst"):
                        try:
                            text = doc_file.read_text(encoding="utf-8", errors="ignore")
                            tags.update(compiled.findall(text))
                        except OSError:
                            continue

        return tags
