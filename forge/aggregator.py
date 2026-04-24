"""Forge aggregator — REQ-001, REQ-006.

Orchestrates all collectors and assembles a ProjectHealthReport.
"""

from __future__ import annotations

from pathlib import Path

from forge.collectors import (
    ComplexityCollector,
    DependencyHealthCollector,
    RequirementsCoverageCollector,
    TestMetricsCollector,
)
from forge.config import ForgeConfig, load_config
from forge.models import ProjectHealthReport


class Aggregator:
    """Run all collectors and return a unified ProjectHealthReport."""

    def __init__(self) -> None:
        self._test_metrics = TestMetricsCollector()
        self._complexity = ComplexityCollector()
        self._dependency = DependencyHealthCollector()
        self._requirements = RequirementsCoverageCollector()

    def run(self, project_path: Path, python_executable: str = "") -> ProjectHealthReport:
        """Collect all metrics for *project_path* and return the report."""
        project_path = project_path.resolve()
        config: ForgeConfig = load_config(project_path)

        name = config.project_name or project_path.name

        # CLI flag overrides forge.toml, which overrides auto-detection
        python = python_executable or config.python_executable
        test_result = self._test_metrics.collect(project_path, python_executable=python)
        complexity_result = self._complexity.collect(project_path)
        dependency_result = self._dependency.collect(project_path)
        requirements_result = self._requirements.collect(
            project_path,
            tag_pattern=config.requirements_tag_pattern,
        )

        return ProjectHealthReport(
            project_name=name,
            project_path=str(project_path),
            weights=config.weights,
            test_metrics=test_result,
            complexity=complexity_result,
            dependency_health=dependency_result,
            requirements_coverage=requirements_result,
        )
