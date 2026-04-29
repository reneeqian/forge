"""Integration tests for ScaffoldEngine — REQ-009."""

from pathlib import Path

import pytest

from forge.scaffolder.engine import ScaffoldConfig, ScaffoldEngine


@pytest.fixture()
def engine() -> ScaffoldEngine:
    return ScaffoldEngine()


@pytest.fixture()
def basic_config(tmp_path: Path) -> ScaffoldConfig:
    return ScaffoldConfig(
        project_name="my-test-project",
        destination=tmp_path / "my-test-project",
        python_version="3.11",
        license_type="MIT",
        author="Test Author",
        git_init=False,  # skip git in tests
    )


class TestScaffoldEngine:
    def test_creates_destination_directory(self, engine, basic_config):
        result = engine.create(basic_config)
        assert result.project_path.exists()
        assert result.project_path.is_dir()

    def test_raises_if_destination_exists(self, engine, basic_config):
        basic_config.destination.mkdir(parents=True)
        with pytest.raises(FileExistsError):
            engine.create(basic_config)

    def test_creates_src_package(self, engine, basic_config):
        engine.create(basic_config)
        pkg_dir = basic_config.destination / "src" / "my_test_project"
        assert pkg_dir.is_dir()
        assert (pkg_dir / "__init__.py").exists()
        assert (pkg_dir / "main.py").exists()

    def test_creates_tests_directory(self, engine, basic_config):
        engine.create(basic_config)
        tests_dir = basic_config.destination / "tests"
        assert tests_dir.is_dir()
        assert (tests_dir / "conftest.py").exists()

    def test_creates_starter_test_file(self, engine, basic_config):
        engine.create(basic_config)
        test_file = basic_config.destination / "tests" / "test_my_test_project.py"
        assert test_file.exists()

    def test_starter_test_references_req_001(self, engine, basic_config):
        engine.create(basic_config)
        test_file = basic_config.destination / "tests" / "test_my_test_project.py"
        content = test_file.read_text()
        assert "REQ-001" in content

    def test_creates_environment_yaml(self, engine, basic_config):
        engine.create(basic_config)
        env_file = basic_config.destination / "environment.yaml"
        assert env_file.exists()
        content = env_file.read_text()
        assert "my-test-project" in content
        assert "3.11" in content

    def test_creates_forge_toml(self, engine, basic_config):
        engine.create(basic_config)
        forge_toml = basic_config.destination / "forge.toml"
        assert forge_toml.exists()
        content = forge_toml.read_text()
        assert "my-test-project" in content

    def test_creates_pyproject_toml(self, engine, basic_config):
        engine.create(basic_config)
        pyproject = basic_config.destination / "pyproject.toml"
        assert pyproject.exists()
        content = pyproject.read_text()
        assert "my-test-project" in content
        assert "3.11" in content

    def test_creates_gitignore(self, engine, basic_config):
        engine.create(basic_config)
        assert (basic_config.destination / ".gitignore").exists()

    def test_creates_readme(self, engine, basic_config):
        engine.create(basic_config)
        readme = basic_config.destination / "README.md"
        assert readme.exists()
        assert "my-test-project" in readme.read_text()

    def test_creates_github_workflows(self, engine, basic_config):
        engine.create(basic_config)
        wf = basic_config.destination / ".github" / "workflows"
        assert (wf / "ci.yml").exists()
        assert (wf / "forge-health.yml").exists()
        assert (wf / "auto-merge.yml").exists()

    def test_auto_merge_workflow_targets_dev(self, engine, basic_config):
        engine.create(basic_config)
        content = (basic_config.destination / ".github" / "workflows" / "auto-merge.yml").read_text()
        assert "branches:" in content
        assert "- dev" in content
        assert "gh pr merge --auto" in content

    def test_creates_docs_requirements(self, engine, basic_config):
        engine.create(basic_config)
        req_doc = basic_config.destination / "docs" / "REQUIREMENTS.md"
        assert req_doc.exists()
        assert "REQ-001" in req_doc.read_text()

    def test_result_lists_all_created_files(self, engine, basic_config):
        result = engine.create(basic_config)
        assert len(result.created_files) > 10
        for f in result.created_files:
            assert f.exists()

    def test_project_name_with_spaces_sanitised(self, engine, tmp_path):
        config = ScaffoldConfig(
            project_name="My Cool Project",
            destination=tmp_path / "My Cool Project",
            git_init=False,
        )
        result = engine.create(config)
        pkg_dir = result.project_path / "src" / "my_cool_project"
        assert pkg_dir.exists()
