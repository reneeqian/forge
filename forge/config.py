"""Forge project configuration loader.

Reads forge.toml from a project directory (REQ-007).
Falls back to defaults when the file is absent or a key is missing.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from forge.models import CollectorWeights

try:
    import toml
except ImportError:  # pragma: no cover
    toml = None  # type: ignore[assignment]


CONFIG_FILENAME = "forge.toml"


class ForgeConfig(BaseModel):
    """Validated configuration for a single project."""

    project_name: str = ""
    weights: CollectorWeights = Field(default_factory=CollectorWeights)
    requirements_tag_pattern: str = r"REQ-\d+"

    # Thresholds — informational only in M1/M2 (used by gate in M3)
    threshold_overall: float = Field(0.70, ge=0.0, le=1.0)
    threshold_coverage: float = Field(0.80, ge=0.0, le=1.0)

    # Optional: override the Python interpreter used to run tests
    python_executable: str = ""

    # Mutation testing is disabled by default — it is very slow (REQ-015)
    mutation_testing_enabled: bool = False


def load_config(project_path: Path) -> ForgeConfig:
    """Load forge.toml from *project_path*, returning defaults if absent.

    REQ-007: If no forge.toml is present, all defaults are used.
    """
    config_file = project_path / CONFIG_FILENAME

    if not config_file.exists():
        name = project_path.name
        return ForgeConfig(project_name=name)

    if toml is None:
        raise RuntimeError("toml package is required to load forge.toml. pip install toml")

    raw: dict = toml.loads(config_file.read_text())

    project_name = raw.get("project", {}).get("name", project_path.name)
    weights_raw = raw.get("weights", {})
    thresholds_raw = raw.get("thresholds", {})
    collectors_raw = raw.get("collectors", {})
    req_raw = collectors_raw.get("requirements", {})
    mutation_raw = collectors_raw.get("mutation_testing", {})
    test_runner_raw = raw.get("test_runner", {})

    weights = CollectorWeights(**weights_raw) if weights_raw else CollectorWeights()

    return ForgeConfig(
        project_name=project_name,
        weights=weights,
        requirements_tag_pattern=req_raw.get("tag_pattern", r"REQ-\d+"),
        threshold_overall=thresholds_raw.get("overall", 0.70),
        threshold_coverage=thresholds_raw.get("coverage", 0.80),
        python_executable=test_runner_raw.get("python", ""),
        mutation_testing_enabled=mutation_raw.get("enabled", False),
    )
