"""Git sync engine for forge gitsync — GIT-001, GIT-002, GIT-003, GIT-004."""

from __future__ import annotations

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


def _unique_line_count(repo: Path, branch: str, landing: str) -> int:
    """Lines present in branch but absent from origin/<landing>. 0 = fully incorporated."""
    _, diff_out, _ = _run_git(repo, ["diff", branch, f"origin/{landing}"])
    return sum(
        1 for line in diff_out.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )


def _has_unpushed_commits(repo: Path, branch: str, landing: str) -> tuple[bool, str]:
    """Return (has_unpushed, reason). Handles squash-merge workflows correctly.

    Comparing git diff <branch> origin/<landing> (branch → landing direction)
    isolates lines that are in the branch but absent from origin/<landing>.
    Zero such lines means the branch was squash-merged; non-zero means
    genuinely unpushed content remains.
    """
    _, log_out, _ = _run_git(repo, ["log", f"origin/{landing}...{branch}", "--oneline"])
    if not log_out.strip():
        return False, ""
    n = _unique_line_count(repo, branch, landing)
    if n == 0:
        return False, ""
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
