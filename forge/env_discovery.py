"""Discovers local Python environments for the forge dashboard. WRK-004"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EnvInfo:
    name: str
    python: Path

    def __str__(self) -> str:
        return self.name


def discover_envs(project_path: Path | None = None) -> list[EnvInfo]:
    """Return available Python environments, project .venv first, then conda."""
    envs: list[EnvInfo] = []

    # Local .venv takes top priority
    if project_path:
        venv_python = project_path / ".venv" / "bin" / "python"
        if venv_python.exists():
            envs.append(EnvInfo(name=".venv (local)", python=venv_python))

    # Conda environments
    try:
        proc = subprocess.run(
            ["conda", "env", "list", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            data: dict = json.loads(proc.stdout)
            root_prefix = data.get("root_prefix", "")
            for env_path_str in data.get("envs", []):
                env_path = Path(env_path_str)
                python = env_path / "bin" / "python"
                if not python.exists():
                    continue
                name = "base" if env_path_str == root_prefix else env_path.name
                envs.append(EnvInfo(name=name, python=python))
    except (FileNotFoundError, json.JSONDecodeError, subprocess.TimeoutExpired):
        pass

    return envs


def resolve_env(name_or_path: str, envs: list[EnvInfo]) -> EnvInfo | None:
    """Find an env by name or python path string."""
    for e in envs:
        if e.name == name_or_path or str(e.python) == name_or_path:
            return e
    return None


def default_index(envs: list[EnvInfo], configured_python: str) -> int:
    """Return the 0-based index of the best default env.

    Prefers the forge.toml-configured python, then falls back to 0.
    """
    if configured_python:
        for i, e in enumerate(envs):
            if str(e.python) == configured_python or e.name == configured_python:
                return i
    return 0
