"""Unit tests for workspace data models — REQ-016."""

import json
from datetime import datetime, timezone

from forge.models import (
    BranchProtectionStatus,
    RepoStatus,
    RulesetStatus,
    WorkspaceStatusReport,
)


class TestBranchProtectionStatus:
    def test_unprotected_branch_defaults(self):
        bp = BranchProtectionStatus(branch="dev", protected=False)
        assert bp.branch == "dev"
        assert bp.protected is False
        assert bp.required_checks == []
        assert bp.strict is None
        assert bp.required_reviews is None
        assert bp.code_owner_review is None
        assert bp.dismiss_stale is None
        assert bp.force_push_allowed is None
        assert bp.deletions_allowed is None

    def test_protected_branch_with_checks(self):
        bp = BranchProtectionStatus(
            branch="main",
            protected=True,
            required_checks=["forge-health"],
            strict=True,
            required_reviews=1,
            code_owner_review=True,
            dismiss_stale=False,
            force_push_allowed=False,
            deletions_allowed=False,
        )
        assert bp.protected is True
        assert bp.required_checks == ["forge-health"]
        assert bp.strict is True
        assert bp.required_reviews == 1
        assert bp.code_owner_review is True
        assert bp.force_push_allowed is False

    def test_protected_branch_serialises_to_json(self):
        bp = BranchProtectionStatus(
            branch="main",
            protected=True,
            required_checks=["forge-health"],
            strict=True,
        )
        data = json.loads(bp.model_dump_json())
        assert data["branch"] == "main"
        assert data["protected"] is True
        assert data["required_checks"] == ["forge-health"]
        assert data["strict"] is True


class TestRulesetStatus:
    def test_basic_ruleset(self):
        rs = RulesetStatus(
            name="protect the main",
            scope="~DEFAULT_BRANCH",
            enforcement="active",
            has_ci_check=True,
            has_bypass_actor=True,
        )
        assert rs.name == "protect the main"
        assert rs.scope == "~DEFAULT_BRANCH"
        assert rs.enforcement == "active"
        assert rs.has_ci_check is True
        assert rs.has_bypass_actor is True

    def test_ruleset_without_ci(self):
        rs = RulesetStatus(
            name="Protect Main Branch",
            scope="refs/heads/main",
            enforcement="active",
            has_ci_check=False,
            has_bypass_actor=False,
        )
        assert rs.has_ci_check is False
        assert rs.has_bypass_actor is False


class TestRepoStatus:
    def test_defaults_all_false(self):
        repo = RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch=None,
        )
        assert repo.auto_merge is False
        assert repo.delete_on_merge is False
        assert repo.rebase_allowed is False
        assert repo.squash_allowed is False
        assert repo.merge_commit_allowed is False
        assert repo.has_codeowners is False
        assert repo.has_dependabot is False

    def test_issues_defaults_to_empty_list(self):
        repo = RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch=None,
        )
        assert repo.issues == []

    def test_collection_error_defaults_to_none(self):
        repo = RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch=None,
        )
        assert repo.collection_error is None

    def test_open_counts_default_to_zero(self):
        repo = RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch=None,
        )
        assert repo.open_prs == 0
        assert repo.open_issues == 0

    def test_health_fields_default_to_none(self):
        repo = RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch=None,
        )
        assert repo.forge_health_grade is None
        assert repo.forge_health_score is None
        assert repo.last_ci_conclusion is None

    def test_workflows_defaults_to_empty_list(self):
        repo = RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch=None,
        )
        assert repo.workflows == []
        assert repo.branch_protection == []
        assert repo.rulesets == []


class TestWorkspaceStatusReport:
    def _make_repo(self, name: str, issues: list[str] | None = None, error: str | None = None) -> RepoStatus:
        return RepoStatus(
            name=name,
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch="dev",
            issues=issues or [],
            collection_error=error,
        )

    def test_total_repos_computed_from_list(self):
        report = WorkspaceStatusReport(
            repos=[self._make_repo("a"), self._make_repo("b"), self._make_repo("c")]
        )
        assert report.total_repos == 3

    def test_total_repos_zero_when_empty(self):
        report = WorkspaceStatusReport()
        assert report.total_repos == 0

    def test_repos_with_issues_counts_correctly(self):
        report = WorkspaceStatusReport(
            repos=[
                self._make_repo("clean"),
                self._make_repo("bad", issues=["auto-merge is disabled"]),
                self._make_repo("also_bad", issues=["rebase merge is enabled"]),
            ]
        )
        assert report.repos_with_issues == 2

    def test_repos_with_collection_error_counted(self):
        report = WorkspaceStatusReport(
            repos=[
                self._make_repo("clean"),
                self._make_repo("broken", error="gh CLI not found"),
            ]
        )
        assert report.repos_with_issues == 1

    def test_repo_with_both_issues_and_error_counted_once(self):
        report = WorkspaceStatusReport(
            repos=[
                self._make_repo("both", issues=["some issue"], error="some error"),
            ]
        )
        assert report.repos_with_issues == 1

    def test_generated_at_set_automatically(self):
        before = datetime.now(timezone.utc)  # noqa: UP017
        report = WorkspaceStatusReport()
        after = datetime.now(timezone.utc)  # noqa: UP017
        assert before <= report.generated_at <= after

    def test_generated_at_is_timezone_aware(self):
        report = WorkspaceStatusReport()
        assert report.generated_at.tzinfo is not None
