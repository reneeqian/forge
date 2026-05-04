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

        # Commit locally first — gh repo create --push requires existing commits
        self._initial_local_commit(project_path, result)
        if not result.ok:
            return result

        if config.create_repo:
            url = self._create_repo(name, project_path, config, result)
            if not result.ok:
                return result
            result.repo_url = url
            self._push_to_remote(project_path, result)
            if not result.ok:
                return result

        self._create_dev_branch(name, result)
        if not result.ok:
            return result

        self._apply_main_ruleset(name, result)
        self._apply_dev_ruleset(name, result)
        self._enable_auto_merge_setting(name, result)

        return result

    # ── steps ────────────────────────────────────────────────────────────────

    def _create_repo(self, name: str, project_path: Path, config: GitHubConfig, result: GitHubSetupResult) -> str:
        # --source sets up origin remote; omit --push to push as a separate step
        cmd = ["gh", "repo", "create", name, "--source", str(project_path)]
        cmd += ["--private"] if config.private else ["--public"]
        if config.description:
            cmd += ["--description", config.description]

        out = self._run(cmd)
        if out is None:
            result.errors.append("gh repo create failed")
            return ""
        return out.strip()

    def _push_to_remote(self, project_path: Path, result: GitHubSetupResult) -> None:
        cmd = ["git", "-C", str(project_path), "push", "-u", "origin", "main"]
        if self._run(cmd) is None:
            result.errors.append("Command failed: push -u origin main")

    def _initial_local_commit(self, project_path: Path, result: GitHubSetupResult) -> None:
        cmds = [
            ["git", "-C", str(project_path), "add", "."],
            ["git", "-C", str(project_path), "commit", "-m", "chore: initial scaffold"],
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
                {
                    "type": "pull_request",
                    "parameters": {
                        "required_approving_review_count": 1,
                        "dismiss_stale_reviews_on_push": True,
                        "required_reviewers": [],
                        "require_code_owner_review": False,
                        "require_last_push_approval": False,
                        "required_review_thread_resolution": False,
                        "allowed_merge_methods": ["merge", "squash", "rebase"],
                    },
                },
            ],
            "bypass_actors": [
                {
                    "actor_id": 5,
                    "actor_type": "RepositoryRole",
                    "bypass_mode": "always",
                }
            ],
        }

        out = self._run_json([
            "gh", "api", "--method", "POST",
            f"repos/{owner}/{repo_name}/rulesets",
            "--input", "-",
        ], stdin=json.dumps(ruleset))

        if out is None:
            result.errors.append("Could not apply main branch ruleset")

    def _apply_dev_ruleset(self, repo_name: str, result: GitHubSetupResult) -> None:
        owner = self._run(["gh", "api", "user", "--jq", ".login"])
        if owner is None:
            result.errors.append("Could not resolve GitHub username for dev ruleset")
            return
        owner = owner.strip()

        ruleset = {
            "name": "Dev branch — require CI before auto-merge",
            "target": "branch",
            "enforcement": "active",
            "conditions": {
                "ref_name": {"include": ["refs/heads/dev"], "exclude": []}
            },
            "rules": [
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "required_status_checks": [{"context": "test"}],
                        "strict_required_status_checks_policy": False,
                    },
                }
            ],
        }

        out = self._run_json([
            "gh", "api", "--method", "POST",
            f"repos/{owner}/{repo_name}/rulesets",
            "--input", "-",
        ], stdin=json.dumps(ruleset))

        if out is None:
            result.errors.append("Could not apply dev branch ruleset")

    def _enable_auto_merge_setting(self, repo_name: str, result: GitHubSetupResult) -> None:
        owner = self._run(["gh", "api", "user", "--jq", ".login"])
        if owner is None:
            result.errors.append("Could not resolve GitHub username for auto-merge setting")
            return
        owner = owner.strip()

        out = self._run([
            "gh", "api", "--method", "PATCH",
            f"repos/{owner}/{repo_name}",
            "--field", "allow_auto_merge=true",
        ])
        if out is None:
            result.errors.append("Could not enable auto-merge on repository")

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
