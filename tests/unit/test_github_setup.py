"""Unit tests for GitHubSetup — all subprocess calls are mocked."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from forge.scaffolder.github_setup import GitHubConfig, GitHubSetup


# ── helpers ───────────────────────────────────────────────────────────────────

def _ok(stdout: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = 0
    m.stdout = stdout
    return m


def _fail() -> MagicMock:
    m = MagicMock()
    m.returncode = 1
    m.stdout = ""
    return m


# ── _gh_available ─────────────────────────────────────────────────────────────

class TestGhAvailable:
    def test_returns_true_when_gh_found(self):
        with patch("subprocess.run", return_value=_ok()):
            assert GitHubSetup()._gh_available() is True

    def test_returns_false_when_gh_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert GitHubSetup()._gh_available() is False

    def test_returns_false_when_gh_exits_nonzero(self):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "gh")):
            assert GitHubSetup()._gh_available() is False


# ── _run ──────────────────────────────────────────────────────────────────────

class TestRun:
    def test_returns_stdout_on_success(self):
        with patch("subprocess.run", return_value=_ok("hello\n")):
            assert GitHubSetup()._run(["gh", "version"]) == "hello\n"

    def test_returns_none_on_failure(self):
        with patch("subprocess.run", return_value=_fail()):
            assert GitHubSetup()._run(["gh", "bad"]) is None

    def test_returns_none_when_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert GitHubSetup()._run(["gh", "version"]) is None

    def test_passes_stdin(self):
        with patch("subprocess.run", return_value=_ok("ok")) as mock_run:
            GitHubSetup()._run(["gh", "api"], stdin='{"key": "val"}')
            _, kwargs = mock_run.call_args
            assert kwargs["input"] == '{"key": "val"}'


# ── _run_json ─────────────────────────────────────────────────────────────────

class TestRunJson:
    def test_parses_json_output(self):
        with patch("subprocess.run", return_value=_ok('{"id": 1}')):
            assert GitHubSetup()._run_json(["gh", "api", "/x"]) == {"id": 1}

    def test_returns_none_on_command_failure(self):
        with patch("subprocess.run", return_value=_fail()):
            assert GitHubSetup()._run_json(["gh", "api", "/x"]) is None

    def test_returns_none_on_invalid_json(self):
        with patch("subprocess.run", return_value=_ok("not-json")):
            assert GitHubSetup()._run_json(["gh", "api", "/x"]) is None


# ── run() top-level ───────────────────────────────────────────────────────────

class TestGitHubSetupRun:
    def test_error_when_gh_not_available(self, tmp_path):
        with patch.object(GitHubSetup, "_gh_available", return_value=False):
            result = GitHubSetup().run(tmp_path, GitHubConfig())
        assert not result.ok
        assert "gh CLI not found" in result.errors[0]

    def test_error_propagates_from_create_repo(self, tmp_path):
        with patch.object(GitHubSetup, "_gh_available", return_value=True), \
             patch.object(GitHubSetup, "_initial_local_commit"), \
             patch.object(GitHubSetup, "_create_repo", return_value="") as mock_create:
            def _set_error(name, path, config, result):
                result.errors.append("gh repo create failed")
                return ""
            mock_create.side_effect = _set_error
            result = GitHubSetup().run(tmp_path, GitHubConfig())
        assert not result.ok

    def test_full_success(self, tmp_path):
        with patch.object(GitHubSetup, "_gh_available", return_value=True), \
             patch.object(GitHubSetup, "_initial_local_commit"), \
             patch.object(GitHubSetup, "_create_repo", return_value="https://github.com/u/p"), \
             patch.object(GitHubSetup, "_push_to_remote"), \
             patch.object(GitHubSetup, "_create_dev_branch"), \
             patch.object(GitHubSetup, "_apply_main_ruleset"), \
             patch.object(GitHubSetup, "_apply_dev_ruleset"), \
             patch.object(GitHubSetup, "_enable_auto_merge_setting"):
            result = GitHubSetup().run(tmp_path, GitHubConfig())

        assert result.ok
        assert result.repo_url == "https://github.com/u/p"


# ── _initial_local_commit ─────────────────────────────────────────────────────

class TestInitialLocalCommit:
    def test_success(self, tmp_path):
        with patch.object(GitHubSetup, "_run", return_value="ok"):
            result = MagicMock()
            result.errors = []
            GitHubSetup()._initial_local_commit(tmp_path, result)
        assert not result.errors

    def test_sets_error_on_git_failure(self, tmp_path):
        with patch.object(GitHubSetup, "_run", return_value=None):
            result = MagicMock()
            result.errors = []
            GitHubSetup()._initial_local_commit(tmp_path, result)
        assert result.errors

    def test_stops_after_first_failure(self, tmp_path):
        side_effects = [None]  # first command fails
        with patch.object(GitHubSetup, "_run", side_effect=side_effects) as mock_run:
            result = MagicMock()
            result.errors = []
            GitHubSetup()._initial_local_commit(tmp_path, result)
        assert mock_run.call_count == 1


# ── _push_to_remote ───────────────────────────────────────────────────────────

class TestPushToRemote:
    def test_success(self, tmp_path):
        with patch.object(GitHubSetup, "_run", return_value="ok"):
            result = MagicMock()
            result.errors = []
            GitHubSetup()._push_to_remote(tmp_path, result)
        assert not result.errors

    def test_sets_error_on_failure(self, tmp_path):
        with patch.object(GitHubSetup, "_run", return_value=None):
            result = MagicMock()
            result.errors = []
            GitHubSetup()._push_to_remote(tmp_path, result)
        assert result.errors


# ── _create_dev_branch ────────────────────────────────────────────────────────

class TestCreateDevBranch:
    def test_success(self):
        with patch.object(GitHubSetup, "_run", return_value="myuser\n"), \
             patch.object(GitHubSetup, "_run_json", return_value={"ref": "refs/heads/dev"}):
            # _create_dev_branch calls _run twice (owner + sha), so side_effect it
            pass

        run_results = ["myuser\n", "abc123\n"]
        with patch.object(GitHubSetup, "_run", side_effect=run_results), \
             patch.object(GitHubSetup, "_run_json", return_value={"ref": "refs/heads/dev"}):
            result = MagicMock()
            result.errors = []
            GitHubSetup()._create_dev_branch("myrepo", result)
        assert not result.errors

    def test_error_when_owner_fails(self):
        with patch.object(GitHubSetup, "_run", return_value=None):
            result = MagicMock()
            result.errors = []
            GitHubSetup()._create_dev_branch("myrepo", result)
        assert result.errors

    def test_error_when_sha_fails(self):
        with patch.object(GitHubSetup, "_run", side_effect=["myuser\n", None]):
            result = MagicMock()
            result.errors = []
            GitHubSetup()._create_dev_branch("myrepo", result)
        assert result.errors

    def test_error_when_api_fails(self):
        with patch.object(GitHubSetup, "_run", side_effect=["myuser\n", "abc123\n"]), \
             patch.object(GitHubSetup, "_run_json", return_value=None):
            result = MagicMock()
            result.errors = []
            GitHubSetup()._create_dev_branch("myrepo", result)
        assert result.errors


# ── _create_repo ──────────────────────────────────────────────────────────────

class TestCreateRepo:
    def test_public_repo(self, tmp_path):
        with patch.object(GitHubSetup, "_run", return_value="https://github.com/u/p\n") as mock_run:
            result = MagicMock()
            result.errors = []
            url = GitHubSetup()._create_repo("myproj", tmp_path, GitHubConfig(private=False), result)
        cmd = mock_run.call_args[0][0]
        assert "--public" in cmd
        assert "--private" not in cmd
        assert url == "https://github.com/u/p"

    def test_private_repo(self, tmp_path):
        with patch.object(GitHubSetup, "_run", return_value="https://github.com/u/p\n"):
            result = MagicMock()
            result.errors = []
            GitHubSetup()._create_repo("myproj", tmp_path, GitHubConfig(private=True), result)

    def test_sets_error_on_failure(self, tmp_path):
        with patch.object(GitHubSetup, "_run", return_value=None):
            result = MagicMock()
            result.errors = []
            GitHubSetup()._create_repo("myproj", tmp_path, GitHubConfig(), result)
        assert result.errors

    def test_includes_description(self, tmp_path):
        with patch.object(GitHubSetup, "_run", return_value="url\n") as mock_run:
            result = MagicMock()
            result.errors = []
            GitHubSetup()._create_repo("p", tmp_path, GitHubConfig(description="My desc"), result)
        cmd = mock_run.call_args[0][0]
        assert "--description" in cmd
        assert "My desc" in cmd


# ── _apply_main_ruleset ───────────────────────────────────────────────────────

class TestApplyMainRuleset:
    def test_posts_correct_ruleset(self):
        result = MagicMock()
        result.errors = []
        with patch.object(GitHubSetup, "_run", return_value="myuser\n"), \
             patch.object(GitHubSetup, "_run_json", return_value={"id": 1}) as mock_json:
            GitHubSetup()._apply_main_ruleset("myrepo", result)
        cmd, kwargs = mock_json.call_args
        stdin_data = json.loads(kwargs.get("stdin") or cmd[1].get("stdin", "{}"))
        rule_types = [r["type"] for r in stdin_data["rules"]]
        assert "pull_request" in rule_types
        assert "deletion" in rule_types
        assert "non_fast_forward" in rule_types
        pr_rule = next(r for r in stdin_data["rules"] if r["type"] == "pull_request")
        assert pr_rule["parameters"]["required_approving_review_count"] == 1
        bypass = stdin_data.get("bypass_actors", [])
        assert any(a["actor_type"] == "RepositoryRole" for a in bypass)

    def test_sets_error_when_owner_lookup_fails(self):
        result = MagicMock()
        result.errors = []
        with patch.object(GitHubSetup, "_run", return_value=None):
            GitHubSetup()._apply_main_ruleset("myrepo", result)
        assert result.errors

    def test_sets_error_when_api_fails(self):
        result = MagicMock()
        result.errors = []
        with patch.object(GitHubSetup, "_run", return_value="myuser\n"), \
             patch.object(GitHubSetup, "_run_json", return_value=None):
            GitHubSetup()._apply_main_ruleset("myrepo", result)
        assert result.errors


# ── _apply_dev_ruleset ────────────────────────────────────────────────────────

class TestApplyDevRuleset:
    def test_posts_required_status_check_for_test_job(self):
        result = MagicMock()
        result.errors = []
        with patch.object(GitHubSetup, "_run", return_value="myuser\n"), \
             patch.object(GitHubSetup, "_run_json", return_value={"id": 2}) as mock_json:
            GitHubSetup()._apply_dev_ruleset("myrepo", result)
        cmd, kwargs = mock_json.call_args
        stdin_data = json.loads(kwargs.get("stdin") or cmd[1].get("stdin", "{}"))
        assert stdin_data["conditions"]["ref_name"]["include"] == ["refs/heads/dev"]
        checks = stdin_data["rules"][0]["parameters"]["required_status_checks"]
        assert any(c["context"] == "test" for c in checks)
        assert not result.errors

    def test_sets_error_when_owner_lookup_fails(self):
        result = MagicMock()
        result.errors = []
        with patch.object(GitHubSetup, "_run", return_value=None):
            GitHubSetup()._apply_dev_ruleset("myrepo", result)
        assert result.errors

    def test_sets_error_when_api_fails(self):
        result = MagicMock()
        result.errors = []
        with patch.object(GitHubSetup, "_run", return_value="myuser\n"), \
             patch.object(GitHubSetup, "_run_json", return_value=None):
            GitHubSetup()._apply_dev_ruleset("myrepo", result)
        assert result.errors


# ── _enable_auto_merge_setting ────────────────────────────────────────────────

class TestEnableAutoMergeSetting:
    def test_patches_allow_auto_merge(self):
        result = MagicMock()
        result.errors = []
        with patch.object(GitHubSetup, "_run", return_value="myuser\n") as mock_run:
            GitHubSetup()._enable_auto_merge_setting("myrepo", result)
        calls = [" ".join(c[0][0]) for c in mock_run.call_args_list]
        assert any("allow_auto_merge=true" in c for c in calls)
        assert not result.errors

    def test_sets_error_when_owner_lookup_fails(self):
        result = MagicMock()
        result.errors = []
        with patch.object(GitHubSetup, "_run", return_value=None):
            GitHubSetup()._enable_auto_merge_setting("myrepo", result)
        assert result.errors

    def test_sets_error_when_patch_fails(self):
        result = MagicMock()
        result.errors = []
        with patch.object(GitHubSetup, "_run", side_effect=["myuser\n", None]):
            GitHubSetup()._enable_auto_merge_setting("myrepo", result)
        assert result.errors
