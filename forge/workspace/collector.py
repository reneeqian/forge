"""WorkspaceCollector — gathers repo status via gh CLI and local files. REQ-017"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from forge.models import BranchProtectionStatus, RepoStatus, RulesetStatus, WorkspaceStatusReport
from forge.workspace.config import RepoConfig, WorkspaceConfig

_RE_AHEAD  = re.compile(r"ahead (\d+)")
_RE_BEHIND = re.compile(r"behind (\d+)")

_STANDARD_RULESET_NAMES = {
    "protect the main",
    "Dev branch — require CI",
    "Dev branch — require CI before auto-merge",
}

_COLLECTOR_KEYS = (
    "test_metrics",
    "complexity",
    "dependency_health",
    "requirements_coverage",
    "static_analysis",
    "type_coverage",
    "dead_code",
    "mutation_testing",
)


class WorkspaceCollector:
    def __init__(self, config: WorkspaceConfig) -> None:
        self._config = config

    # ── public ────────────────────────────────────────────────────────────────

    def collect_all(self, run_health: bool = False) -> WorkspaceStatusReport:
        report = WorkspaceStatusReport()

        if not self._gh_available():
            for rc in self._config.repos:
                report.repos.append(
                    RepoStatus(
                        name=rc.name,
                        owner=rc.owner,
                        repo_type=rc.repo_type,
                        visibility="unknown",
                        description=None,
                        local_branch=None,
                        collection_error="gh CLI not available",
                    )
                )
            return report

        for rc in self._config.repos:
            repo = RepoStatus(
                name=rc.name,
                owner=rc.owner,
                repo_type=rc.repo_type,
                visibility="unknown",
                description=None,
                local_branch=None,
            )
            slug = rc.full_slug
            try:
                self._collect_repo_settings(repo, slug)
                self._collect_branch_protection(repo, slug)
                self._collect_rulesets(repo, slug)
                self._collect_ci_conclusion(repo, slug, "forge-health.yml")
                local_path = rc.local_path
                if local_path:
                    self._collect_local_files(repo, local_path)
                    self._collect_branch_details(repo, local_path)
                self._collect_branch_checks(repo, slug)
                self._collect_open_pr(repo, slug)
            except Exception as exc:
                repo.collection_error = f"collection failed: {exc}"

            if run_health:
                self._collect_forge_health(repo, rc)

            repo.issues = self._compute_issues(repo)
            report.repos.append(repo)

        return report

    # ── collection methods ────────────────────────────────────────────────────

    def _collect_repo_settings(self, repo: RepoStatus, slug: str) -> None:
        data = self._run_json(["gh", "api", f"repos/{slug}"])
        if data is None:
            repo.collection_error = f"could not fetch repo settings for {slug}"
            return
        repo.visibility = data.get("visibility", "unknown")
        repo.description = data.get("description") or None
        repo.auto_merge = bool(data.get("allow_auto_merge"))
        repo.delete_on_merge = bool(data.get("delete_branch_on_merge"))
        repo.rebase_allowed = bool(data.get("allow_rebase_merge"))
        repo.squash_allowed = bool(data.get("allow_squash_merge"))
        repo.merge_commit_allowed = bool(data.get("allow_merge_commit"))

    def _collect_branch_protection(self, repo: RepoStatus, slug: str) -> None:
        for branch in ("main", "dev"):
            data = self._run_json([
                "gh", "api", f"repos/{slug}/branches/{branch}/protection",
            ])
            if data is None:
                repo.branch_protection.append(
                    BranchProtectionStatus(branch=branch, protected=False)
                )
                continue

            checks_block = data.get("required_status_checks") or {}
            required_checks = checks_block.get("contexts", [])
            strict = checks_block.get("strict") if checks_block else None

            reviews_block = data.get("required_pull_request_reviews") or {}
            required_reviews = reviews_block.get("required_approving_review_count") if reviews_block else None
            code_owner = reviews_block.get("require_code_owner_reviews") if reviews_block else None
            dismiss_stale = reviews_block.get("dismiss_stale_reviews") if reviews_block else None

            fp_block = data.get("allow_force_pushes") or {}
            force_push = fp_block.get("enabled") if fp_block else None

            del_block = data.get("allow_deletions") or {}
            deletions = del_block.get("enabled") if del_block else None

            repo.branch_protection.append(
                BranchProtectionStatus(
                    branch=branch,
                    protected=True,
                    required_checks=required_checks,
                    strict=strict,
                    required_reviews=required_reviews,
                    code_owner_review=code_owner,
                    dismiss_stale=dismiss_stale,
                    force_push_allowed=force_push,
                    deletions_allowed=deletions,
                )
            )

    def _collect_rulesets(self, repo: RepoStatus, slug: str) -> None:
        data = self._run_json(["gh", "api", f"repos/{slug}/rulesets"])
        if data is None or not isinstance(data, list):
            return

        for rs in data:
            rules = rs.get("rules", [])
            rule_types = {r.get("type") for r in rules}
            has_ci = "required_status_checks" in rule_types
            bypass_actors = rs.get("bypass_actors", [])
            conditions = rs.get("conditions", {})
            ref_name = conditions.get("ref_name", {})
            includes = ref_name.get("include", [])
            scope = includes[0] if includes else rs.get("target", "unknown")

            repo.rulesets.append(
                RulesetStatus(
                    name=rs.get("name", ""),
                    scope=scope,
                    enforcement=rs.get("enforcement", "active"),
                    has_ci_check=has_ci,
                    has_bypass_actor=bool(bypass_actors),
                )
            )

    def _collect_local_files(self, repo: RepoStatus, local_path: Path) -> None:
        github_dir = local_path / ".github"
        repo.has_codeowners = (github_dir / "CODEOWNERS").exists()
        repo.has_dependabot = (github_dir / "dependabot.yml").exists()

        wf_dir = github_dir / "workflows"
        if wf_dir.is_dir():
            repo.workflows = [f.name for f in sorted(wf_dir.iterdir()) if f.suffix in (".yml", ".yaml")]

        try:
            proc = subprocess.run(
                ["git", "-C", str(local_path), "branch", "--show-current"],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                repo.local_branch = proc.stdout.strip() or None
        except FileNotFoundError:
            pass

    def _collect_ci_conclusion(self, repo: RepoStatus, slug: str, workflow_file: str) -> None:
        data = self._run_json([
            "gh", "api",
            f"repos/{slug}/actions/workflows/{workflow_file}/runs",
            "--jq",
            "{workflow_runs: [.workflow_runs[:1][] | {conclusion: .conclusion, html_url: .html_url}]}",
        ])
        if data is None:
            return
        runs = data.get("workflow_runs", [])
        if runs:
            repo.last_ci_conclusion = runs[0].get("conclusion")
            repo.last_ci_run_url    = runs[0].get("html_url") or None

    def _collect_branch_details(self, repo: RepoStatus, local_path: Path) -> None:
        git = ["git", "-C", str(local_path)]
        try:
            proc = subprocess.run([*git, "branch", "--list"], capture_output=True, text=True)
            if proc.returncode == 0:
                branches = [b.strip().lstrip("* ") for b in proc.stdout.splitlines() if b.strip()]
                repo.branch_count = len(branches)

            current = repo.local_branch or ""
            stale: set[str] = set()
            for target in ("origin/main", "origin/dev"):
                proc = subprocess.run(
                    [*git, "branch", "--merged", target], capture_output=True, text=True
                )
                if proc.returncode == 0:
                    for b in proc.stdout.splitlines():
                        name = b.strip().lstrip("* ")
                        if name and name not in ("main", "dev", current):
                            stale.add(name)
            repo.stale_branches = sorted(stale)

            proc = subprocess.run(
                [*git, "for-each-ref",
                 "--format=%(refname:short)|%(upstream:short)|%(upstream:track)",
                 "refs/heads/"],
                capture_output=True, text=True,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    parts = line.split("|", 2)
                    if len(parts) < 3:
                        continue
                    bname, upstream, track = parts
                    track = track.strip()
                    if not track:
                        continue
                    ahead_m  = _RE_AHEAD.search(track)
                    behind_m = _RE_BEHIND.search(track)
                    ahead  = int(ahead_m.group(1))  if ahead_m  else 0
                    behind = int(behind_m.group(1)) if behind_m else 0
                    if ahead and behind:
                        repo.branches_diverged.append(
                            f"{bname} (ahead {ahead}, behind {behind} vs {upstream})")
                    elif behind:
                        repo.branches_behind.append(f"{bname} ({behind} behind {upstream})")
        except FileNotFoundError:
            pass

    def _collect_forge_health(self, repo: RepoStatus, rc: RepoConfig) -> None:
        if not rc.local_path:
            return
        try:
            proc = subprocess.run(
                ["forge", "health", str(rc.local_path), "--json"],
                capture_output=True,
                text=True,
            )
            if proc.returncode not in (0, 1):
                return
            data = json.loads(proc.stdout)
            repo.forge_health_grade = data.get("grade")
            repo.forge_health_score = data.get("overall_score")
            for key in _COLLECTOR_KEYS:
                c_data = data.get(key) or {}
                repo.forge_health_collectors[key] = c_data.get("score")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _collect_branch_checks(self, repo: RepoStatus, slug: str) -> None:
        if not repo.local_branch:
            return
        data = self._run_json([
            "gh", "api",
            f"repos/{slug}/commits/{repo.local_branch}/check-runs",
        ])
        if not isinstance(data, dict):
            return
        runs = data.get("check_runs", [])
        if not runs:
            return
        repo.branch_ci_total = len(runs)
        repo.branch_ci_passed = sum(1 for r in runs if r.get("conclusion") == "success")

    def _collect_open_pr(self, repo: RepoStatus, slug: str) -> None:
        if not repo.local_branch:
            return
        data = self._run_json([
            "gh", "api",
            f"repos/{slug}/pulls?state=open&head={repo.owner}:{repo.local_branch}&per_page=5",
        ])
        if not isinstance(data, list) or not data:
            return
        pr = data[0]
        repo.open_pr_number = pr.get("number")
        repo.open_pr_url = pr.get("html_url")

    # ── issue detection ───────────────────────────────────────────────────────

    def _compute_issues(self, repo: RepoStatus) -> list[str]:
        issues: list[str] = []

        if not repo.auto_merge:
            issues.append("auto-merge is disabled (auto-merge.yml will not trigger)")

        if repo.rebase_allowed:
            issues.append("rebase merge is enabled (breaks config history integrity)")

        if not repo.delete_on_merge:
            issues.append("delete branch on merge is disabled")

        main_bp = next((b for b in repo.branch_protection if b.branch == "main"), None)
        if main_bp is None or not main_bp.protected:
            issues.append("main has no classic branch protection")
        elif not main_bp.required_checks:
            issues.append("main has no required CI check")

        if not repo.has_codeowners:
            issues.append("CODEOWNERS file missing")

        if repo.repo_type == "code":
            if "forge-health.yml" not in repo.workflows:
                issues.append("missing forge-health.yml workflow")
        else:
            if not repo.workflows:
                issues.append("no CI workflows configured")

        for rs in repo.rulesets:
            if rs.name not in _STANDARD_RULESET_NAMES:
                issues.append(f"non-standard ruleset: '{rs.name}'")

        if not repo.description:
            issues.append("no repository description")

        return issues

    # ── helpers ───────────────────────────────────────────────────────────────

    def _gh_available(self) -> bool:
        try:
            result = subprocess.run(["gh", "--version"], capture_output=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def _run(self, cmd: list[str]) -> str | None:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return None
            return result.stdout
        except FileNotFoundError:
            return None

    def _run_json(self, cmd: list[str]) -> dict | list | None:
        out = self._run(cmd)
        if out is None:
            return None
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return None
