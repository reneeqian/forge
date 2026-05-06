"""Unit tests for forge.config — INF-001."""

import textwrap
from pathlib import Path

import pytest

from forge.config import ForgeConfig, load_config


class TestLoadConfig:
    def test_returns_defaults_when_no_forge_toml(self, tmp_path: Path):
        """INF-001: missing forge.toml → all defaults used."""
        config = load_config(tmp_path)
        assert isinstance(config, ForgeConfig)
        assert config.project_name == tmp_path.name
        assert config.weights.test_metrics == 0.30

    def test_reads_project_name(self, tmp_path: Path):
        (tmp_path / "forge.toml").write_text(
            textwrap.dedent("""\
                [project]
                name = "my-cool-project"
            """)
        )
        config = load_config(tmp_path)
        assert config.project_name == "my-cool-project"

    def test_reads_custom_weights(self, tmp_path: Path):
        (tmp_path / "forge.toml").write_text(
            textwrap.dedent("""\
                [weights]
                test_metrics = 0.35
                complexity = 0.15
                dependency_health = 0.20
                requirements_coverage = 0.10
                static_analysis = 0.10
                type_coverage = 0.05
                dead_code = 0.05
                mutation_testing = 0.00
            """)
        )
        config = load_config(tmp_path)
        assert config.weights.test_metrics == 0.35

    def test_reads_thresholds(self, tmp_path: Path):
        (tmp_path / "forge.toml").write_text(
            textwrap.dedent("""\
                [thresholds]
                overall = 0.80
                coverage = 0.90
            """)
        )
        config = load_config(tmp_path)
        assert config.threshold_overall == 0.80
        assert config.threshold_coverage == 0.90

    def test_reads_requirements_tag_pattern(self, tmp_path: Path):
        (tmp_path / "forge.toml").write_text(
            textwrap.dedent("""\
                [collectors.requirements]
                tag_pattern = "TICKET-\\\\d+"
            """)
        )
        config = load_config(tmp_path)
        assert "TICKET" in config.requirements_tag_pattern

    def test_partial_config_uses_defaults_for_missing_keys(self, tmp_path: Path):
        """Only project name set; weights should be defaults."""
        (tmp_path / "forge.toml").write_text("[project]\nname = 'partial'\n")
        config = load_config(tmp_path)
        assert config.weights.test_metrics == 0.30

    def test_fallback_name_when_project_section_absent(self, tmp_path: Path):
        (tmp_path / "forge.toml").write_text("[thresholds]\noverall = 0.75\n")
        config = load_config(tmp_path)
        assert config.project_name == tmp_path.name
