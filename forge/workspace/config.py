"""Workspace configuration — parses workspace.toml. REQ-016"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import toml


@dataclass
class RepoConfig:
    name: str
    owner: str
    repo_type: str = "code"
    local_path: Path | None = None

    @property
    def full_slug(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass
class WorkspaceConfig:
    owner: str
    repos: list[RepoConfig] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> WorkspaceConfig:
        if not path.exists():
            raise FileNotFoundError(f"workspace config not found: {path}")

        data = toml.loads(path.read_text())

        workspace_section = data.get("workspace", {})
        default_owner = workspace_section.get("owner", "")

        raw_repos = data.get("repos")
        if raw_repos is None:
            raise ValueError("workspace.toml must contain at least one [[repos]] entry")

        repos: list[RepoConfig] = []
        for r in raw_repos:
            lp = r.get("local_path")
            repos.append(
                RepoConfig(
                    name=r["name"],
                    owner=r.get("owner", default_owner),
                    repo_type=r.get("type", "code"),
                    local_path=Path(lp) if lp else None,
                )
            )

        return cls(owner=default_owner, repos=repos)
