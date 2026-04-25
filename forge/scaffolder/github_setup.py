"""GitHub repository setup for newly scaffolded projects.

Creates the remote repo, pushes the initial commit, creates a dev branch,
and applies the standard branch policy:
  - main: no direct pushes; all changes via pull request (ruleset)
  - dev:  direct pushes allowed; preferred workflow is feature branch → PR
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GitHubConfig:
    create_repo: bool = True
    private: bool = False
    description: str = ""


@dataclass
class GitHubSetupResult:
    repo_url: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class GitHubSetup:
    """Set up a GitHub remote for a freshly scaffolded project."""

    def run(self, project_path: Path, config: GitHubConfig) -> GitHubSetupResult:
        result = GitHubSetupResult()
        name = project_path.name

        if not self._gh_available():
            result.errors.append("gh CLI not found — skipping GitHub setup")
            return result

        if config.create_repo:
            url = self._create_repo(name, config, result)
            if not result.ok:
                return result
            result.repo_url = url

        self._initial_commit_and_push(project_path, result)
        if not result.ok:
            return result

        self._create_dev_branch(name, result)
        if not result.ok:
            return result

        self._apply_main_ruleset(name, result)
        self._update_ci_workflow(project_path)

        return result

    # ── steps ────────────────────────────────────────────────────────────────

    def _create_repo(self, name: str, config: GitHubConfig, result: GitHubSetupResult) -> str:
        cmd = ["gh", "repo", "create", name, "--source", ".", "--push"]
        cmd += ["--private"] if config.private else ["--public"]
        if config.description:
            cmd += ["--description", config.description]

        out = self._run(cmd)
        if out is None:
            result.errors.append("gh repo create failed")
            return ""
        # gh repo create prints the repo URL to stdout
        return out.strip()

    def _initial_commit_and_push(self, project_path: Path, result: GitHubSetupResult) -> None:
        cmds = [
            ["git", "-C", str(project_path), "add", "."],
            ["git", "-C", str(project_path), "commit", "-m", "chore: initial scaffold"],
            ["git", "-C", str(project_path), "push", "-u", "origin", "main"],
        ]
        for cmd in cmds:
            if self._run(cmd) is None:
                result.errors.append(f"Command failed: {' '.join(cmd[2:])}")
                return

    def _create_dev_branch(self, repo_name: str, result: GitHubSetupResult) -> None:
        # Resolve owner/name from gh
        owner = self._run(["gh", "api", "user", "--jq", ".login"])
        if owner is None:
            result.errors.append("Could not resolve GitHub username")
            return
        owner = owner.strip()

        sha = self._run([
            "gh", "api", f"repos/{owner}/{repo_name}/git/ref/heads/main", "--jq", ".object.sha"
        ])
        if sha is None:
            result.errors.append("Could not get main branch SHA")
            return

        out = self._run_json(["gh", "api", "--method", "POST",
                               f"repos/{owner}/{repo_name}/git/refs",
                               "--field", "ref=refs/heads/dev",
                               "--field", f"sha={sha.strip()}"])
        if out is None:
            result.errors.append("Could not create dev branch")

    def _apply_main_ruleset(self, repo_name: str, result: GitHubSetupResult) -> None:
        owner = self._run(["gh", "api", "user", "--jq", ".login"])
        if owner is None:
            result.errors.append("Could not resolve GitHub username for ruleset")
            return
        owner = owner.strip()

        ruleset = {
            "name": "Protect Main Branch",
            "target": "branch",
            "enforcement": "active",
            "conditions": {
                "ref_name": {"include": ["refs/heads/main"], "exclude": []}
            },
            "rules": [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {"type": "pull_request"},
            ],
        }

        out = self._run_json([
            "gh", "api", "--method", "POST",
            f"repos/{owner}/{repo_name}/rulesets",
            "--input", "-",
        ], stdin=json.dumps(ruleset))

        if out is None:
            result.errors.append("Could not apply main branch ruleset")

    def _update_ci_workflow(self, project_path: Path) -> None:
        """Rewrite the CI workflow to match the branch policy."""
        ci_path = project_path / ".github" / "workflows" / "ci.yml"
        if not ci_path.exists():
            return
        content = ci_path.read_text()
        # Replace push trigger to target dev, add pull_request targeting dev and main
        old = "on:\n  push:\n    branches: [main]\n  pull_request:"
        new = (
            "on:\n"
            "  push:\n"
            "    branches: [dev]\n"
            "  pull_request:\n"
            "    branches: [dev, main]"
        )
        ci_path.write_text(content.replace(old, new))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _gh_available(self) -> bool:
        try:
            subprocess.run(["gh", "--version"], capture_output=True, check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False

    def _run(self, cmd: list[str], stdin: str | None = None) -> str | None:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                input=stdin,
            )
            if result.returncode != 0:
                return None
            return result.stdout
        except FileNotFoundError:
            return None

    def _run_json(self, cmd: list[str], stdin: str | None = None) -> dict | None:
        out = self._run(cmd, stdin=stdin)
        if out is None:
            return None
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return None
