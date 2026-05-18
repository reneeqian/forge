"""Unit tests for env_discovery module — WRK-004."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.env_discovery import EnvInfo, default_index, discover_envs, resolve_env


@pytest.mark.unit
class TestDiscoverEnvs:
    def test_includes_local_venv_when_present(self, tmp_path):
        venv_python = tmp_path / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()

        conda_payload = json.dumps({"envs": [], "root_prefix": ""})
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = conda_payload
            envs = discover_envs(project_path=tmp_path)

        venv_env = next((e for e in envs if e.name == ".venv (local)"), None)
        assert venv_env is not None
        assert venv_env.python == venv_python

    def test_venv_listed_before_conda_envs(self, tmp_path):
        venv_python = tmp_path / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()

        fake_conda = tmp_path / "envs" / "myenv" / "bin" / "python"
        fake_conda.parent.mkdir(parents=True)
        fake_conda.touch()

        conda_payload = json.dumps({
            "envs": [str(tmp_path / "envs" / "myenv")],
            "root_prefix": "/no/match",
        })
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = conda_payload
            envs = discover_envs(project_path=tmp_path)

        assert envs[0].name == ".venv (local)"

    def test_skips_conda_env_without_python_binary(self, tmp_path):
        conda_payload = json.dumps({
            "envs": [str(tmp_path / "empty_env")],
            "root_prefix": "/other",
        })
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = conda_payload
            envs = discover_envs()

        assert not any(e.name == "empty_env" for e in envs)

    def test_base_env_named_base(self, tmp_path):
        base_python = tmp_path / "base" / "bin" / "python"
        base_python.parent.mkdir(parents=True)
        base_python.touch()

        conda_payload = json.dumps({
            "envs": [str(tmp_path / "base")],
            "root_prefix": str(tmp_path / "base"),
        })
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = conda_payload
            envs = discover_envs()

        base = next((e for e in envs if e.name == "base"), None)
        assert base is not None

    def test_conda_unavailable_returns_empty_list(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            envs = discover_envs()
        assert envs == []

    def test_conda_json_error_returns_empty_list(self):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "not valid json"
            envs = discover_envs()
        assert envs == []

    def test_no_project_path_skips_venv_check(self, tmp_path):
        conda_payload = json.dumps({"envs": [], "root_prefix": ""})
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = conda_payload
            envs = discover_envs(project_path=None)
        assert not any(e.name == ".venv (local)" for e in envs)


@pytest.mark.unit
class TestResolveEnv:
    def _make_envs(self, tmp_path: Path) -> list[EnvInfo]:
        p1 = tmp_path / "forge" / "bin" / "python"
        p1.parent.mkdir(parents=True)
        p1.touch()
        p2 = tmp_path / "medimg" / "bin" / "python"
        p2.parent.mkdir(parents=True)
        p2.touch()
        return [EnvInfo("forge", p1), EnvInfo("medimg-base", p2)]

    def test_resolve_by_name(self, tmp_path):
        envs = self._make_envs(tmp_path)
        result = resolve_env("medimg-base", envs)
        assert result is not None
        assert result.name == "medimg-base"

    def test_resolve_by_python_path(self, tmp_path):
        envs = self._make_envs(tmp_path)
        result = resolve_env(str(envs[0].python), envs)
        assert result is not None
        assert result.name == "forge"

    def test_resolve_unknown_returns_none(self, tmp_path):
        envs = self._make_envs(tmp_path)
        assert resolve_env("nonexistent", envs) is None

    def test_resolve_empty_list_returns_none(self):
        assert resolve_env("anything", []) is None


@pytest.mark.unit
class TestDefaultIndex:
    def _make_envs(self, tmp_path: Path) -> list[EnvInfo]:
        paths = [tmp_path / f"e{i}" / "bin" / "python" for i in range(3)]
        for p in paths:
            p.parent.mkdir(parents=True)
            p.touch()
        return [EnvInfo(f"env{i}", p) for i, p in enumerate(paths)]

    def test_returns_zero_when_no_configured_python(self, tmp_path):
        envs = self._make_envs(tmp_path)
        assert default_index(envs, "") == 0

    def test_returns_matching_index_by_path(self, tmp_path):
        envs = self._make_envs(tmp_path)
        assert default_index(envs, str(envs[2].python)) == 2

    def test_returns_matching_index_by_name(self, tmp_path):
        envs = self._make_envs(tmp_path)
        assert default_index(envs, "env1") == 1

    def test_falls_back_to_zero_when_no_match(self, tmp_path):
        envs = self._make_envs(tmp_path)
        assert default_index(envs, "/no/such/python") == 0

    def test_str_representation(self, tmp_path):
        p = tmp_path / "bin" / "python"
        p.parent.mkdir(parents=True)
        p.touch()
        e = EnvInfo("myenv", p)
        assert str(e) == "myenv"
