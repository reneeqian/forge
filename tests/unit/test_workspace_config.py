"""Unit tests for WorkspaceConfig — REQ-016."""

from pathlib import Path

import pytest

from forge.workspace.config import RepoConfig, WorkspaceConfig


class TestWorkspaceConfigLoad:
    def _write_toml(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "workspace.toml"
        p.write_text(content)
        return p

    def test_loads_owner_and_repos_from_toml(self, tmp_path):
        p = self._write_toml(
            tmp_path,
            """
[workspace]
owner = "reneeqian"

[[repos]]
name = "medical_image_ai_toolkit"
type = "code"
""",
        )
        cfg = WorkspaceConfig.load(p)
        assert cfg.owner == "reneeqian"
        assert len(cfg.repos) == 1
        assert cfg.repos[0].name == "medical_image_ai_toolkit"

    def test_repo_inherits_default_owner(self, tmp_path):
        p = self._write_toml(
            tmp_path,
            """
[workspace]
owner = "reneeqian"

[[repos]]
name = "my_repo"
type = "code"
""",
        )
        cfg = WorkspaceConfig.load(p)
        assert cfg.repos[0].owner == "reneeqian"

    def test_repo_can_override_owner(self, tmp_path):
        p = self._write_toml(
            tmp_path,
            """
[workspace]
owner = "reneeqian"

[[repos]]
name = "other_repo"
owner = "anotheruser"
type = "code"
""",
        )
        cfg = WorkspaceConfig.load(p)
        assert cfg.repos[0].owner == "anotheruser"

    def test_repo_type_defaults_to_code(self, tmp_path):
        p = self._write_toml(
            tmp_path,
            """
[workspace]
owner = "reneeqian"

[[repos]]
name = "my_repo"
""",
        )
        cfg = WorkspaceConfig.load(p)
        assert cfg.repos[0].repo_type == "code"

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            WorkspaceConfig.load(tmp_path / "nonexistent.toml")

    def test_missing_repos_key_raises_value_error(self, tmp_path):
        p = self._write_toml(
            tmp_path,
            """
[workspace]
owner = "reneeqian"
""",
        )
        with pytest.raises(ValueError, match="repos"):
            WorkspaceConfig.load(p)

    def test_local_path_is_none_when_omitted(self, tmp_path):
        p = self._write_toml(
            tmp_path,
            """
[workspace]
owner = "reneeqian"

[[repos]]
name = "my_repo"
type = "code"
""",
        )
        cfg = WorkspaceConfig.load(p)
        assert cfg.repos[0].local_path is None

    def test_local_path_parsed_when_present(self, tmp_path):
        p = self._write_toml(
            tmp_path,
            f"""
[workspace]
owner = "reneeqian"

[[repos]]
name = "my_repo"
type = "code"
local_path = "{tmp_path}"
""",
        )
        cfg = WorkspaceConfig.load(p)
        assert cfg.repos[0].local_path == tmp_path

    def test_multiple_repos_all_loaded(self, tmp_path):
        p = self._write_toml(
            tmp_path,
            """
[workspace]
owner = "reneeqian"

[[repos]]
name = "repo_a"
type = "code"

[[repos]]
name = "repo_b"
type = "docs"
""",
        )
        cfg = WorkspaceConfig.load(p)
        assert len(cfg.repos) == 2
        names = [r.name for r in cfg.repos]
        assert "repo_a" in names
        assert "repo_b" in names

    def test_docs_repo_type_preserved(self, tmp_path):
        p = self._write_toml(
            tmp_path,
            """
[workspace]
owner = "reneeqian"

[[repos]]
name = "my_docs"
type = "docs"
""",
        )
        cfg = WorkspaceConfig.load(p)
        assert cfg.repos[0].repo_type == "docs"


class TestRepoConfig:
    def test_full_slug(self):
        repo = RepoConfig(name="my_repo", owner="reneeqian", repo_type="code")
        assert repo.full_slug == "reneeqian/my_repo"
