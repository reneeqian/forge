"""Git sync engine for forge gitsync — GIT-001, GIT-002, GIT-003, GIT-004."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

PROTECTED_BRANCHES: frozenset[str] = frozenset({"main", "dev"})


@dataclass
class RepoBranchResult:
    repo: Path
    landed_on: str = ""
    pulled: bool = False
    deleted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    skip_reasons: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class GitSyncResult:
    repos: list[RepoBranchResult] = field(default_factory=list)


def _run_git(repo: Path, args: list[str]) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", "-C", str(repo)] + args,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def discover_repos(target: Path) -> list[Path]:
    """GIT-001: return [target] if it's a repo, else all git-repo subdirs."""
    if (target / ".git").exists():
        return [target]
    return sorted(p for p in target.iterdir() if p.is_dir() and (p / ".git").exists())


def _detect_landing_branch(repo: Path) -> str:
    """Return 'dev' if it exists locally or as a remote ref, else 'main'."""
    _, out, _ = _run_git(repo, ["branch", "--list", "dev"])
    if out.strip():
        return "dev"
    _, out, _ = _run_git(repo, ["branch", "-r", "--list", "origin/dev"])
    if out.strip():
        return "dev"
    return "main"


def _check_merged_pr(repo: Path, branch: str, landing: str) -> tuple[bool, str]:
    """Level 2: query GitHub for a merged PR from branch → landing.

    Returns (True, "")    — merged PR found, no local commits beyond headRefOid → safe to delete
    Returns (False, msg)  — local commits exist beyond the PR tip → skip with reason
    Returns (False, "")   — gh unavailable / not GitHub / no PR → fall through to Level 3
    """
    if not shutil.which("gh"):
        return False, ""

    try:
        pr_result = subprocess.run(
            ["gh", "pr", "list", "--head", branch, "--base", landing,
             "--state", "merged", "--limit", "1", "--json", "number,headRefOid"],
            capture_output=True, text=True, cwd=str(repo),
        )
        if pr_result.returncode != 0:
            return False, ""

        prs = json.loads(pr_result.stdout or "[]")
        if not prs:
            return False, ""

        head_oid = prs[0].get("headRefOid", "")
        if not head_oid:
            return False, ""

        rc, log_out, _ = _run_git(repo, ["log", f"{head_oid}..{branch}", "--oneline"])
        if rc != 0:
            return False, ""

        if not log_out.strip():
            return True, ""

        n = len(log_out.strip().splitlines())
        return False, f"{n} local commit(s) not in merged PR"

    except Exception:
        return False, ""


def _has_unpushed_commits(repo: Path, branch: str, landing: str) -> tuple[bool, str]:
    """Return (has_unpushed, reason). Three-level detection for squash-merge workflows.

    Level 1 — git log (2-dot): if branch has no commits not in origin/<landing>, delete.
    Level 2 — PR check (gh): if a merged PR exists with no local commits beyond headRefOid, delete.
    Level 3 — historical diff: compare branch additions to all lines ever added to landing.
    """
    # Level 1: fast git log check (handles non-squash merges)
    _, log_out, _ = _run_git(repo, ["log", f"origin/{landing}..{branch}", "--oneline"])
    if not log_out.strip():
        return False, ""

    # Level 2: PR-based check (requires gh CLI)
    pr_merged, pr_skip_reason = _check_merged_pr(repo, branch, landing)
    if pr_skip_reason:
        return True, pr_skip_reason
    if pr_merged:
        return False, ""

    # Level 3: historical git diff fallback (handles post-squash evolution on landing)
    rc, base, _ = _run_git(repo, ["merge-base", branch, f"origin/{landing}"])
    if rc != 0 or not base.strip():
        return True, "no common ancestor with landing"
    base = base.strip()

    _, branch_diff, _ = _run_git(repo, ["diff", base, branch])
    branch_added = {
        line for line in branch_diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    }
    if not branch_added:
        return False, ""

    _, landing_log, _ = _run_git(
        repo, ["log", f"{base}..origin/{landing}", "-p", "--no-merges"]
    )
    landing_added_ever = {
        line for line in landing_log.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    }
    missing = branch_added - landing_added_ever
    if not missing:
        return False, ""

    n = len(missing)
    return True, f"{n} unique line{'s' if n != 1 else ''} not in {landing}"


def _parse_gone_branches(vv_output: str) -> list[str]:
    """Extract branch names whose remote tracking ref is marked gone."""
    branches = []
    for line in vv_output.splitlines():
        if ": gone]" not in line:
            continue
        branch = line.strip().lstrip("* ").split()[0]
        if branch not in PROTECTED_BRANCHES:
            branches.append(branch)
    return branches


def sync_repo(repo: Path) -> RepoBranchResult:
    """GIT-002, GIT-003, GIT-004: fetch, checkout landing branch, prune gone branches."""
    result = RepoBranchResult(repo=repo)

    # GIT-002: fetch + prune remote tracking refs
    rc, _, err = _run_git(repo, ["fetch", "--prune"])
    if rc != 0:
        result.errors.append(f"fetch failed: {err}")
        return result

    # GIT-003: checkout and pull landing branch before any cleanup
    landing = _detect_landing_branch(repo)
    result.landed_on = landing

    rc, _, err = _run_git(repo, ["checkout", landing])
    if rc != 0:
        result.errors.append(f"checkout {landing} failed: {err}")
        return result

    rc, _, err = _run_git(repo, ["pull", "origin", landing])
    if rc != 0:
        result.errors.append(f"pull origin/{landing} failed: {err}")
    else:
        result.pulled = True

    # GIT-004: delete local branches whose remote is gone and have no unpushed commits
    _, vv_out, _ = _run_git(repo, ["branch", "-vv"])
    for branch in _parse_gone_branches(vv_out):
        has_unpushed, reason = _has_unpushed_commits(repo, branch, landing)
        if has_unpushed:
            result.skipped.append(branch)
            result.skip_reasons[branch] = reason
        else:
            rc, _, err = _run_git(repo, ["branch", "-D", branch])
            if rc == 0:
                result.deleted.append(branch)
            else:
                result.errors.append(f"delete {branch} failed: {err}")

    return result


def sync(target: Path) -> GitSyncResult:
    """Run sync_repo on every repository discovered under target."""
    sync_result = GitSyncResult()
    for repo in discover_repos(target):
        sync_result.repos.append(sync_repo(repo))
    return sync_result
