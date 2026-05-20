"""Unit tests for forge gitsync — GIT-001, GIT-002, GIT-003, GIT-004."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from forge.cli import app

runner = CliRunner()


# ── helpers ───────────────────────────────────────────────────────────────────


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


def _git_mock(responses: dict[tuple[str, ...], MagicMock]):
    """Return a subprocess.run side_effect keyed on git args (after -C <repo>)."""
    def side_effect(cmd, **kwargs):
        # cmd = ["git", "-C", "<repo>", *args]
        key = tuple(cmd[3:])
        return responses.get(key, _proc())
    return side_effect


def _make_git_repo(path: Path) -> Path:
    (path / ".git").mkdir(parents=True, exist_ok=True)
    return path


# ── GIT-001: repository discovery ────────────────────────────────────────────


@pytest.mark.unit
class TestDiscoverRepos:
    def test_path_is_git_repo_returns_single_entry(self, tmp_path):
        """GIT-001: path containing .git/ is treated as a single repo."""
        from forge.git_sync import discover_repos

        _make_git_repo(tmp_path)
        assert discover_repos(tmp_path) == [tmp_path]

    def test_directory_of_repos_returns_all_git_subdirs(self, tmp_path):
        """GIT-001: directory of repos — all immediate subdirs with .git/ are returned."""
        from forge.git_sync import discover_repos

        repo_a = _make_git_repo(tmp_path / "repo_a")
        repo_b = _make_git_repo(tmp_path / "repo_b")
        (tmp_path / "not_a_repo").mkdir()

        result = discover_repos(tmp_path)
        assert set(result) == {repo_a, repo_b}

    def test_empty_directory_returns_empty_list(self, tmp_path):
        """GIT-001: directory with no git repos returns empty list."""
        from forge.git_sync import discover_repos

        assert discover_repos(tmp_path) == []

    def test_non_git_subdirs_are_excluded(self, tmp_path):
        """GIT-001: non-git subdirectories are excluded from discovery results."""
        from forge.git_sync import discover_repos

        _make_git_repo(tmp_path / "real_repo")
        (tmp_path / "docs").mkdir()
        (tmp_path / "scripts").mkdir()

        result = discover_repos(tmp_path)
        assert len(result) == 1
        assert result[0].name == "real_repo"


# ── GIT-002: fetch and prune ──────────────────────────────────────────────────


@pytest.mark.unit
class TestFetchAndPrune:
    def test_fetch_failure_records_error_and_returns_early(self, tmp_path):
        """GIT-002: fetch failure is recorded as an error and processing stops for that repo."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        responses = {
            ("fetch", "--prune"): _proc(returncode=128, stderr="fatal: not a git repo"),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)):
            result = sync_repo(tmp_path)

        assert any("fetch" in e for e in result.errors)
        assert result.pulled is False
        assert result.deleted == []

    def test_fetch_failure_does_not_prevent_other_repos(self, tmp_path):
        """GIT-002: one repo's fetch failure does not abort processing of remaining repos."""
        from forge.git_sync import sync

        _make_git_repo(tmp_path / "repo_a")
        _make_git_repo(tmp_path / "repo_b")

        vv_clean = "* dev abc1234 [origin/dev] msg\n"
        shared = {
            ("branch", "--list", "dev"): _proc(stdout="  dev\n"),
            ("checkout", "dev"): _proc(),
            ("pull", "origin", "dev"): _proc(stdout="Already up to date."),
            ("branch", "-vv"): _proc(stdout=vv_clean),
        }

        def side_effect(cmd, **kwargs):
            key = tuple(cmd[3:])
            if "repo_a" in str(cmd) and key == ("fetch", "--prune"):
                return _proc(returncode=128, stderr="fatal")
            return shared.get(key, _proc())

        with patch("subprocess.run", side_effect=side_effect):
            result = sync(tmp_path)

        names = [r.repo.name for r in result.repos]
        assert "repo_a" in names
        assert "repo_b" in names
        repo_a_result = next(r for r in result.repos if r.repo.name == "repo_a")
        assert repo_a_result.errors
        repo_b_result = next(r for r in result.repos if r.repo.name == "repo_b")
        assert repo_b_result.pulled


# ── GIT-003: landing branch detection and pull ────────────────────────────────


@pytest.mark.unit
class TestLandingBranch:
    def _base_responses(self, landing: str, vv_output: str = "* dev abc [origin/dev] msg\n") -> dict:
        return {
            ("fetch", "--prune"): _proc(),
            ("checkout", landing): _proc(),
            ("pull", "origin", landing): _proc(stdout="Already up to date."),
            ("branch", "-vv"): _proc(stdout=vv_output),
        }

    def test_uses_dev_when_dev_exists_locally(self, tmp_path):
        """GIT-003: landing branch is dev when dev exists locally."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        responses = {
            **self._base_responses("dev"),
            ("branch", "--list", "dev"): _proc(stdout="  dev\n"),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)):
            result = sync_repo(tmp_path)

        assert result.landed_on == "dev"
        assert result.pulled is True

    def test_falls_back_to_main_when_no_dev(self, tmp_path):
        """GIT-003: landing branch falls back to main when dev does not exist locally or remotely."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        responses = {
            ("fetch", "--prune"): _proc(),
            ("branch", "--list", "dev"): _proc(stdout=""),
            ("branch", "-r", "--list", "origin/dev"): _proc(stdout=""),
            ("checkout", "main"): _proc(),
            ("pull", "origin", "main"): _proc(stdout="Already up to date."),
            ("branch", "-vv"): _proc(stdout="* main abc [origin/main] msg\n"),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)):
            result = sync_repo(tmp_path)

        assert result.landed_on == "main"
        assert result.pulled is True

    def test_checkout_failure_records_error(self, tmp_path):
        """GIT-003: checkout failure is recorded as an error and pull is not attempted."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        responses = {
            ("fetch", "--prune"): _proc(),
            ("branch", "--list", "dev"): _proc(stdout="  dev\n"),
            ("checkout", "dev"): _proc(returncode=1, stderr="error: Your local changes"),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)):
            result = sync_repo(tmp_path)

        assert any("checkout" in e for e in result.errors)
        assert result.pulled is False

    def test_pull_failure_records_error(self, tmp_path):
        """GIT-003: pull failure is recorded as an error; pulled flag remains False."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        responses = {
            ("fetch", "--prune"): _proc(),
            ("branch", "--list", "dev"): _proc(stdout="  dev\n"),
            ("checkout", "dev"): _proc(),
            ("pull", "origin", "dev"): _proc(returncode=1, stderr="CONFLICT"),
            ("branch", "-vv"): _proc(stdout="* dev abc [origin/dev] msg\n"),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)):
            result = sync_repo(tmp_path)

        assert any("pull" in e for e in result.errors)
        assert result.pulled is False


# ── GIT-004: stale branch cleanup ────────────────────────────────────────────


@pytest.mark.unit
class TestStaleBranchCleanup:
    _VV_GONE = (
        "* dev          abc1234 [origin/dev] latest\n"
        "  stale-feat   def5678 [origin/stale-feat: gone] old commit\n"
    )
    _VV_GONE_UNPUSHED = (
        "* dev          abc1234 [origin/dev] latest\n"
        "  wip-branch   def5678 [origin/wip-branch: gone] wip\n"
    )
    _VV_PROTECTED_GONE = (
        "  main   abc [origin/main: gone] x\n"
        "* dev    def [origin/dev: gone] y\n"
    )

    def _base(self, vv: str) -> dict:
        return {
            ("fetch", "--prune"): _proc(),
            ("branch", "--list", "dev"): _proc(stdout="  dev\n"),
            ("checkout", "dev"): _proc(),
            ("pull", "origin", "dev"): _proc(stdout="Already up to date."),
            ("branch", "-vv"): _proc(stdout=vv),
        }

    def test_gone_branch_with_no_unpushed_commits_is_deleted(self, tmp_path):
        """GIT-004: gone-remote branch with all commits in origin/landing is deleted locally."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        responses = {
            **self._base(self._VV_GONE),
            ("log", "origin/dev..stale-feat", "--oneline"): _proc(stdout=""),
            ("branch", "-D", "stale-feat"): _proc(stdout="Deleted branch stale-feat."),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)):
            result = sync_repo(tmp_path)

        assert "stale-feat" in result.deleted
        assert result.skipped == []

    def test_gone_branch_with_unpushed_commits_is_skipped(self, tmp_path):
        """GIT-004: gone-remote branch with unpushed commits is skipped and reported."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        responses = {
            **self._base(self._VV_GONE_UNPUSHED),
            ("log", "origin/dev..wip-branch", "--oneline"): _proc(stdout="def5678 wip commit\n"),
            ("merge-base", "wip-branch", "origin/dev"): _proc(stdout="base000\n"),
            ("diff", "base000", "wip-branch"): _proc(stdout="+x = 1\n"),
            ("log", "base000..origin/dev", "-p", "--no-merges"): _proc(stdout=""),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)), \
             patch("forge.git_sync._check_merged_pr", return_value=(False, "")):
            result = sync_repo(tmp_path)

        assert "wip-branch" in result.skipped
        assert result.deleted == []

    def test_main_and_dev_are_never_deleted(self, tmp_path):
        """GIT-004: main and dev are never deleted regardless of remote tracking state."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        responses = self._base(self._VV_PROTECTED_GONE)
        with patch("subprocess.run", side_effect=_git_mock(responses)):
            result = sync_repo(tmp_path)

        assert "main" not in result.deleted
        assert "dev" not in result.deleted
        assert result.skipped == []

    def test_multiple_gone_branches_processed_independently(self, tmp_path):
        """GIT-004: multiple gone branches are each evaluated; clean ones deleted, dirty ones skipped."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        vv = (
            "* dev          abc [origin/dev] ok\n"
            "  clean-feat   111 [origin/clean-feat: gone] merged\n"
            "  wip-feat     222 [origin/wip-feat: gone] wip\n"
        )
        responses = {
            **self._base(vv),
            ("log", "origin/dev..clean-feat", "--oneline"): _proc(stdout=""),
            ("log", "origin/dev..wip-feat", "--oneline"): _proc(stdout="222 wip commit\n"),
            ("merge-base", "wip-feat", "origin/dev"): _proc(stdout="base000\n"),
            ("diff", "base000", "wip-feat"): _proc(stdout="+x = 1\n"),
            ("log", "base000..origin/dev", "-p", "--no-merges"): _proc(stdout=""),
            ("branch", "-D", "clean-feat"): _proc(stdout="Deleted branch clean-feat."),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)), \
             patch("forge.git_sync._check_merged_pr", return_value=(False, "")):
            result = sync_repo(tmp_path)

        assert "clean-feat" in result.deleted
        assert "wip-feat" in result.skipped

    def test_squash_merged_branch_is_deleted_despite_commit_history_mismatch(self, tmp_path):
        """GIT-004: gone branch whose commits were squash-merged is deleted via Level 3 fallback."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        vv = (
            "* dev            abc [origin/dev] latest\n"
            "  squash-feat    111 [origin/squash-feat: gone] squash merged\n"
        )
        # Level 1 non-empty (squash commit has different SHA), Level 2 falls through,
        # Level 3: branch added "+x = 1", landing's historical log also has "+x = 1" → delete.
        responses = {
            **self._base(vv),
            ("log", "origin/dev..squash-feat", "--oneline"): _proc(stdout="111 some commit\n"),
            ("merge-base", "squash-feat", "origin/dev"): _proc(stdout="base000\n"),
            ("diff", "base000", "squash-feat"): _proc(stdout="+x = 1\n"),
            ("log", "base000..origin/dev", "-p", "--no-merges"): _proc(stdout="+x = 1\n"),
            ("branch", "-D", "squash-feat"): _proc(),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)), \
             patch("forge.git_sync._check_merged_pr", return_value=(False, "")):
            result = sync_repo(tmp_path)

        assert "squash-feat" in result.deleted
        assert result.skipped == []

    def test_branch_with_real_unmerged_content_is_skipped(self, tmp_path):
        """GIT-004: gone branch with genuinely unpushed content is skipped via Level 3 fallback."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        vv = (
            "* dev       abc [origin/dev] latest\n"
            "  wip-real  222 [origin/wip-real: gone] real wip\n"
        )
        responses = {
            **self._base(vv),
            ("log", "origin/dev..wip-real", "--oneline"): _proc(stdout="222 wip commit\n"),
            ("merge-base", "wip-real", "origin/dev"): _proc(stdout="base000\n"),
            ("diff", "base000", "wip-real"): _proc(stdout="+x = 1\n"),
            ("log", "base000..origin/dev", "-p", "--no-merges"): _proc(stdout=""),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)), \
             patch("forge.git_sync._check_merged_pr", return_value=(False, "")):
            result = sync_repo(tmp_path)

        assert "wip-real" in result.skipped
        assert result.deleted == []

    def test_skipped_branch_result_includes_reason(self, tmp_path):
        """GIT-004: skip_reasons field records unique line count for each skipped branch."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        vv = (
            "* dev    abc [origin/dev] ok\n"
            "  my-wip 111 [origin/my-wip: gone] wip\n"
        )
        responses = {
            **self._base(vv),
            ("log", "origin/dev..my-wip", "--oneline"): _proc(stdout="111 wip\n"),
            ("merge-base", "my-wip", "origin/dev"): _proc(stdout="base000\n"),
            ("diff", "base000", "my-wip"): _proc(stdout="+x = 1\n+y = 2\n"),
            ("log", "base000..origin/dev", "-p", "--no-merges"): _proc(stdout=""),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)), \
             patch("forge.git_sync._check_merged_pr", return_value=(False, "")):
            result = sync_repo(tmp_path)

        assert "my-wip" in result.skipped
        assert "my-wip" in result.skip_reasons
        assert "2" in result.skip_reasons["my-wip"]

    # ── new GIT-004 Level 2 / Level 3 tests (fail until implementation) ──────

    def test_squash_merged_via_pr_is_deleted(self, tmp_path):
        """GIT-004 Level 2: merged PR with no local commits beyond headRefOid → delete."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        vv = (
            "* dev          abc [origin/dev] latest\n"
            "  squash-feat  111 [origin/squash-feat: gone] squash merged\n"
        )
        responses = {
            **self._base(vv),
            ("log", "origin/dev..squash-feat", "--oneline"): _proc(stdout="111 some commit\n"),
            ("branch", "-D", "squash-feat"): _proc(),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)), \
             patch("forge.git_sync._check_merged_pr", return_value=(True, "")):
            result = sync_repo(tmp_path)

        assert "squash-feat" in result.deleted
        assert result.skipped == []

    def test_squash_merged_via_pr_with_local_commits_is_skipped(self, tmp_path):
        """GIT-004 Level 2: merged PR but local commits beyond headRefOid → skip with reason."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        vv = (
            "* dev          abc [origin/dev] latest\n"
            "  feat-local   111 [origin/feat-local: gone] wip\n"
        )
        responses = {
            **self._base(vv),
            ("log", "origin/dev..feat-local", "--oneline"): _proc(stdout="111 local commit\n"),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)), \
             patch("forge.git_sync._check_merged_pr",
                   return_value=(False, "1 local commit(s) not in merged PR")):
            result = sync_repo(tmp_path)

        assert "feat-local" in result.skipped
        assert result.skip_reasons.get("feat-local") == "1 local commit(s) not in merged PR"
        assert result.deleted == []

    def test_squash_merged_with_post_squash_landing_evolution_is_deleted(self, tmp_path):
        """GIT-004 Level 3: squash-merged branch whose content was later modified on landing is deleted."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        vv = (
            "* dev          abc [origin/dev] latest\n"
            "  squash-old   111 [origin/squash-old: gone] squash merged\n"
        )
        # branch added "+x = 2"; squash added "+x = 2" to landing; later commit changed to "+x = 3".
        # current-state diff would show "-x = 2" (false positive skip), but historical log has "+x = 2".
        responses = {
            **self._base(vv),
            ("log", "origin/dev..squash-old", "--oneline"): _proc(stdout="111 old commit\n"),
            ("merge-base", "squash-old", "origin/dev"): _proc(stdout="base000\n"),
            ("diff", "base000", "squash-old"): _proc(stdout="+x = 2\n"),
            ("log", "base000..origin/dev", "-p", "--no-merges"): _proc(
                stdout="+x = 2\n+x = 3\n"
            ),
            ("branch", "-D", "squash-old"): _proc(),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)), \
             patch("forge.git_sync._check_merged_pr", return_value=(False, "")):
            result = sync_repo(tmp_path)

        assert "squash-old" in result.deleted
        assert result.skipped == []

    def test_genuinely_unpushed_branch_skipped_via_level3(self, tmp_path):
        """GIT-004 Level 3: branch with content absent from landing's historical log is skipped."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        vv = (
            "* dev      abc [origin/dev] latest\n"
            "  wip-real 111 [origin/wip-real: gone] wip\n"
        )
        responses = {
            **self._base(vv),
            ("log", "origin/dev..wip-real", "--oneline"): _proc(stdout="111 wip commit\n"),
            ("merge-base", "wip-real", "origin/dev"): _proc(stdout="base000\n"),
            ("diff", "base000", "wip-real"): _proc(stdout="+my_wip_line\n"),
            ("log", "base000..origin/dev", "-p", "--no-merges"): _proc(stdout="+other_content\n"),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)), \
             patch("forge.git_sync._check_merged_pr", return_value=(False, "")):
            result = sync_repo(tmp_path)

        assert "wip-real" in result.skipped
        assert result.deleted == []

    def test_git003_checkout_precedes_git004_deletion(self, tmp_path):
        """GIT-003, GIT-004: landing branch checkout happens before stale branch deletion."""
        from forge.git_sync import sync_repo

        _make_git_repo(tmp_path)
        call_order: list[str] = []
        vv = (
            "* dev        abc [origin/dev] ok\n"
            "  old-branch 111 [origin/old-branch: gone] done\n"
        )

        def ordered_mock(cmd, **kwargs):
            args = tuple(cmd[3:])
            if args == ("checkout", "dev"):
                call_order.append("checkout")
                return _proc()
            if args == ("branch", "-D", "old-branch"):
                call_order.append("delete")
                return _proc()
            responses = {
                ("fetch", "--prune"): _proc(),
                ("branch", "--list", "dev"): _proc(stdout="  dev\n"),
                ("pull", "origin", "dev"): _proc(stdout="Already up to date."),
                ("branch", "-vv"): _proc(stdout=vv),
                ("log", "origin/dev..old-branch", "--oneline"): _proc(stdout=""),
            }
            return responses.get(args, _proc())

        with patch("subprocess.run", side_effect=ordered_mock):
            result = sync_repo(tmp_path)

        assert call_order.index("checkout") < call_order.index("delete")
        assert "old-branch" in result.deleted


# ── CLI: forge gitsync ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestGitsyncCommand:
    def test_exits_1_when_no_repos_found(self, tmp_path):
        """GIT-001: gitsync exits 1 with a clear message when no git repos are found."""
        result = runner.invoke(app, ["gitsync", str(tmp_path)])
        assert result.exit_code == 1
        assert "no" in result.output.lower() or "not found" in result.output.lower()

    def test_exits_1_when_path_does_not_exist(self, tmp_path):
        """GIT-001: gitsync exits 1 when the given path does not exist."""
        result = runner.invoke(app, ["gitsync", str(tmp_path / "nonexistent")])
        assert result.exit_code == 1

    def test_exits_0_and_prints_table_on_success(self, tmp_path):
        """GIT-001, GIT-002, GIT-003: successful sync exits 0 and renders repo in output table."""
        # Short repo name so Rich doesn't truncate it in the table column.
        repo = _make_git_repo(tmp_path / "myrepo")
        vv = "* dev abc [origin/dev] msg\n"
        responses = {
            ("fetch", "--prune"): _proc(),
            ("branch", "--list", "dev"): _proc(stdout="  dev\n"),
            ("checkout", "dev"): _proc(),
            ("pull", "origin", "dev"): _proc(stdout="Already up to date."),
            ("branch", "-vv"): _proc(stdout=vv),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)):
            result = runner.invoke(app, ["gitsync", str(tmp_path)])

        assert result.exit_code == 0
        assert repo.name in result.output

    def test_skipped_branch_appears_in_output_with_skip_marker(self, tmp_path):
        """GIT-004: branch skipped due to unpushed commits appears in CLI output as skipped (not deleted)."""
        _make_git_repo(tmp_path)
        vv = (
            "* dev     abc [origin/dev] ok\n"
            "  my-wip  111 [origin/my-wip: gone] wip\n"
        )
        responses = {
            ("fetch", "--prune"): _proc(),
            ("branch", "--list", "dev"): _proc(stdout="  dev\n"),
            ("checkout", "dev"): _proc(),
            ("pull", "origin", "dev"): _proc(stdout="Already up to date."),
            ("branch", "-vv"): _proc(stdout=vv),
            ("log", "origin/dev..my-wip", "--oneline"): _proc(stdout="111 wip\n"),
            ("merge-base", "my-wip", "origin/dev"): _proc(stdout="base000\n"),
            ("diff", "base000", "my-wip"): _proc(stdout="+wip_content\n"),
            ("log", "base000..origin/dev", "-p", "--no-merges"): _proc(stdout=""),
        }
        with patch("subprocess.run", side_effect=_git_mock(responses)), \
             patch("forge.git_sync._check_merged_pr", return_value=(False, "")):
            result = runner.invoke(app, ["gitsync", str(tmp_path)])

        assert result.exit_code == 0
        assert "my-wip" in result.output
        # "not in dev" only appears in the Skipped column's skip reason; deleted branches
        # never produce this text, so its presence proves the branch was skipped, not deleted.
        assert "not in dev" in result.output
