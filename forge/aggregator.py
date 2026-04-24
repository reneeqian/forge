"""Forge aggregator — REQ-001, REQ-006.

Orchestrates all collectors and assembles a ProjectHealthReport.
"""

from __future__ import annotations

from pathlib import Path

from forge.collectors import (
    ComplexityCollector,
    DeadCodeCollector,
    DependencyHealthCollector,
    MutationTestingCollector,
    RequirementsCoverageCollector,
    StaticAnalysisCollector,
    TestMetricsCollector,
    TypeCoverageCollector,
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
        self._static_analysis = StaticAnalysisCollector()
        self._type_coverage = TypeCoverageCollector()
        self._dead_code = DeadCodeCollector()
        self._mutation = MutationTestingCollector()

    def run(
        self,
        project_path: Path,
        python_executable: str = "",
        skip_test_run: bool = False,
    ) -> ProjectHealthReport:
        """Collect all metrics for *project_path* and return the report.

        When *skip_test_run* is True, test_metrics reads an existing coverage
        report instead of executing pytest. Use this when the caller has already
        run the test suite (e.g. regulatory_tools) to avoid double test runs.
        """
        project_path = project_path.resolve()
        config: ForgeConfig = load_config(project_path)

        name = config.project_name or project_path.name

        # CLI flag overrides forge.toml, which overrides auto-detection
        python = python_executable or config.python_executable
        test_result = self._test_metrics.collect(
            project_path,
            python_executable=python,
            run_tests=not skip_test_run,
        )
        complexity_result = self._complexity.collect(project_path)
        dependency_result = self._dependency.collect(project_path)
        requirements_result = self._requirements.collect(
            project_path,
            tag_pattern=config.requirements_tag_pattern,
        )
        static_result = self._static_analysis.collect(project_path)
        type_result = self._type_coverage.collect(project_path)
        dead_result = self._dead_code.collect(project_path)
        mutation_result = self._mutation.collect(
            project_path,
            enabled=config.mutation_testing_enabled,
        )

        return ProjectHealthReport(
            project_name=name,
            project_path=str(project_path),
            weights=config.weights,
            test_metrics=test_result,
            complexity=complexity_result,
            dependency_health=dependency_result,
            requirements_coverage=requirements_result,
            static_analysis=static_result,
            type_coverage=type_result,
            dead_code=dead_result,
            mutation_testing=mutation_result,
        )
