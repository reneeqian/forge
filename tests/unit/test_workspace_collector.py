"""Unit tests for WorkspaceCollector — WRK-002."""

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from forge.models import BranchProtectionStatus, RepoStatus, RulesetStatus
from forge.workspace.collector import WorkspaceCollector
from forge.workspace.config import RepoConfig, WorkspaceConfig

# ── helpers ────────────────────────────────────────────────────────────────────


def _make_config(repos: list[RepoConfig] | None = None) -> WorkspaceConfig:
    return WorkspaceConfig(
        owner="reneeqian",
        repos=repos or [],
    )


def _make_repo_config(name: str = "my_repo", repo_type: str = "code", local_path: Path | None = None) -> RepoConfig:
    return RepoConfig(name=name, owner="reneeqian", repo_type=repo_type, local_path=local_path)


def _ok(text: str) -> str:
    return text


# ── Step 3: Helper method tests ────────────────────────────────────────────────


class TestWorkspaceCollectorHelpers:
    def setup_method(self):
        self.collector = WorkspaceCollector(_make_config())

    def test_run_returns_stdout_on_success(self):
        mock = MagicMock(returncode=0, stdout="hello\n")
        with patch("subprocess.run", return_value=mock):
            result = self.collector._run(["echo", "hello"])
        assert result == "hello\n"

    def test_run_returns_none_on_nonzero_exit(self):
        mock = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=mock):
            result = self.collector._run(["false"])
        assert result is None

    def test_run_returns_none_when_command_not_found(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = self.collector._run(["nonexistent"])
        assert result is None

    def test_run_json_parses_valid_json(self):
        mock = MagicMock(returncode=0, stdout='{"key": "value"}')
        with patch("subprocess.run", return_value=mock):
            result = self.collector._run_json(["echo"])
        assert result == {"key": "value"}

    def test_run_json_returns_none_on_bad_json(self):
        mock = MagicMock(returncode=0, stdout="not json")
        with patch("subprocess.run", return_value=mock):
            result = self.collector._run_json(["echo"])
        assert result is None

    def test_run_json_returns_none_on_command_failure(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = self.collector._run_json(["echo"])
        assert result is None

    def test_gh_available_true_when_gh_found(self):
        mock = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=mock):
            assert self.collector._gh_available() is True

    def test_gh_available_false_when_missing(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert self.collector._gh_available() is False

    def test_gh_available_false_on_nonzero(self):
        mock = MagicMock(returncode=1)
        with patch("subprocess.run", return_value=mock):
            assert self.collector._gh_available() is False


# ── Step 4: Individual collection method tests ─────────────────────────────────


class TestCollectRepoSettings:
    def setup_method(self):
        self.collector = WorkspaceCollector(_make_config())
        self.repo = RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch=None,
        )

    def test_parses_visibility_and_description(self):
        api_response = {
            "visibility": "public",
            "description": "A test repo",
            "allow_auto_merge": False,
            "delete_branch_on_merge": False,
            "allow_rebase_merge": False,
            "allow_squash_merge": True,
            "allow_merge_commit": True,
        }
        with patch.object(self.collector, "_run_json", return_value=api_response):
            self.collector._collect_repo_settings(self.repo, "reneeqian/my_repo")
        assert self.repo.visibility == "public"
        assert self.repo.description == "A test repo"

    def test_parses_auto_merge_true(self):
        api_response = {
            "visibility": "public",
            "description": None,
            "allow_auto_merge": True,
            "delete_branch_on_merge": True,
            "allow_rebase_merge": False,
            "allow_squash_merge": True,
            "allow_merge_commit": True,
        }
        with patch.object(self.collector, "_run_json", return_value=api_response):
            self.collector._collect_repo_settings(self.repo, "reneeqian/my_repo")
        assert self.repo.auto_merge is True
        assert self.repo.delete_on_merge is True

    def test_parses_auto_merge_false(self):
        api_response = {
            "visibility": "private",
            "description": None,
            "allow_auto_merge": False,
            "delete_branch_on_merge": False,
            "allow_rebase_merge": True,
            "allow_squash_merge": True,
            "allow_merge_commit": True,
        }
        with patch.object(self.collector, "_run_json", return_value=api_response):
            self.collector._collect_repo_settings(self.repo, "reneeqian/my_repo")
        assert self.repo.auto_merge is False
        assert self.repo.rebase_allowed is True

    def test_sets_collection_error_when_api_fails(self):
        with patch.object(self.collector, "_run_json", return_value=None):
            self.collector._collect_repo_settings(self.repo, "reneeqian/my_repo")
        assert self.repo.collection_error is not None
        assert "settings" in self.repo.collection_error.lower()


class TestCollectBranchProtection:
    def setup_method(self):
        self.collector = WorkspaceCollector(_make_config())
        self.repo = RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch=None,
        )

    def test_protected_branch_with_check_and_reviews(self):
        api_response = {
            "required_status_checks": {
                "strict": True,
                "contexts": ["forge-health"],
            },
            "required_pull_request_reviews": {
                "required_approving_review_count": 1,
                "require_code_owner_reviews": True,
                "dismiss_stale_reviews": False,
            },
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
        }

        def fake_run_json(cmd):
            if "main" in " ".join(cmd):
                return api_response
            return None

        with patch.object(self.collector, "_run_json", side_effect=fake_run_json):
            self.collector._collect_branch_protection(self.repo, "reneeqian/my_repo")

        main_bp = next((b for b in self.repo.branch_protection if b.branch == "main"), None)
        assert main_bp is not None
        assert main_bp.protected is True
        assert "forge-health" in main_bp.required_checks
        assert main_bp.required_reviews == 1
        assert main_bp.code_owner_review is True

    def test_unprotected_branch_returns_protected_false(self):
        with patch.object(self.collector, "_run_json", return_value=None):
            self.collector._collect_branch_protection(self.repo, "reneeqian/my_repo")

        for bp in self.repo.branch_protection:
            assert bp.protected is False
        assert self.repo.collection_error is None

    def test_both_main_and_dev_collected(self):
        with patch.object(self.collector, "_run_json", return_value=None):
            self.collector._collect_branch_protection(self.repo, "reneeqian/my_repo")

        branches = {bp.branch for bp in self.repo.branch_protection}
        assert "main" in branches
        assert "dev" in branches


class TestCollectRulesets:
    def setup_method(self):
        self.collector = WorkspaceCollector(_make_config())
        self.repo = RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch=None,
        )

    def _make_ruleset_api(self, name: str, target: str, conditions_ref: str, rules: list, bypass_actors: list) -> dict:
        return {
            "name": name,
            "target": target,
            "enforcement": "active",
            "conditions": {"ref_name": {"include": [conditions_ref], "exclude": []}},
            "rules": rules,
            "bypass_actors": bypass_actors,
        }

    def test_parses_name_scope_and_enforcement(self):
        api_list = [
            self._make_ruleset_api(
                "protect the main", "branch", "~DEFAULT_BRANCH",
                [{"type": "deletion"}, {"type": "pull_request"}], []
            )
        ]
        with patch.object(self.collector, "_run_json", return_value=api_list):
            self.collector._collect_rulesets(self.repo, "reneeqian/my_repo")

        assert len(self.repo.rulesets) == 1
        rs = self.repo.rulesets[0]
        assert rs.name == "protect the main"
        assert rs.enforcement == "active"

    def test_detects_ci_check_in_rules(self):
        api_list = [
            self._make_ruleset_api(
                "Dev branch — require CI", "branch", "refs/heads/dev",
                [{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "forge-health"}]}}],
                [],
            )
        ]
        with patch.object(self.collector, "_run_json", return_value=api_list):
            self.collector._collect_rulesets(self.repo, "reneeqian/my_repo")

        assert self.repo.rulesets[0].has_ci_check is True

    def test_detects_bypass_actor(self):
        api_list = [
            self._make_ruleset_api(
                "protect the main", "branch", "~DEFAULT_BRANCH",
                [{"type": "deletion"}],
                [{"actor_id": 1, "actor_type": "RepositoryRole"}],
            )
        ]
        with patch.object(self.collector, "_run_json", return_value=api_list):
            self.collector._collect_rulesets(self.repo, "reneeqian/my_repo")

        assert self.repo.rulesets[0].has_bypass_actor is True

    def test_returns_empty_list_when_api_fails(self):
        with patch.object(self.collector, "_run_json", return_value=None):
            self.collector._collect_rulesets(self.repo, "reneeqian/my_repo")

        assert self.repo.rulesets == []


class TestCollectLocalFiles:
    def setup_method(self):
        self.collector = WorkspaceCollector(_make_config())

    def _make_repo(self, local_path: Path | None = None) -> RepoStatus:
        return RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch=None,
        )

    def test_detects_codeowners_when_present(self, tmp_path):
        github_dir = tmp_path / ".github"
        github_dir.mkdir()
        (github_dir / "CODEOWNERS").write_text("* @reneeqian\n")
        repo = self._make_repo(tmp_path)
        self.collector._collect_local_files(repo, tmp_path)
        assert repo.has_codeowners is True

    def test_detects_codeowners_absent(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self.collector._collect_local_files(repo, tmp_path)
        assert repo.has_codeowners is False

    def test_lists_workflow_filenames(self, tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "forge-health.yml").write_text("")
        (wf_dir / "auto-merge.yml").write_text("")
        repo = self._make_repo(tmp_path)
        self.collector._collect_local_files(repo, tmp_path)
        assert "forge-health.yml" in repo.workflows
        assert "auto-merge.yml" in repo.workflows

    def test_no_workflows_returns_empty_list(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self.collector._collect_local_files(repo, tmp_path)
        assert repo.workflows == []

    def test_detects_dependabot_present(self, tmp_path):
        github_dir = tmp_path / ".github"
        github_dir.mkdir()
        (github_dir / "dependabot.yml").write_text("")
        repo = self._make_repo(tmp_path)
        self.collector._collect_local_files(repo, tmp_path)
        assert repo.has_dependabot is True

    def test_detects_dependabot_absent(self, tmp_path):
        repo = self._make_repo(tmp_path)
        self.collector._collect_local_files(repo, tmp_path)
        assert repo.has_dependabot is False

    def test_reads_current_git_branch(self, tmp_path):
        mock = MagicMock(returncode=0, stdout="dev\n")
        with patch("subprocess.run", return_value=mock):
            repo = self._make_repo(tmp_path)
            self.collector._collect_local_files(repo, tmp_path)
        assert repo.local_branch == "dev"

    def test_local_branch_none_when_git_fails(self, tmp_path):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            repo = self._make_repo(tmp_path)
            self.collector._collect_local_files(repo, tmp_path)
        assert repo.local_branch is None


class TestCollectCiConclusion:
    def setup_method(self):
        self.collector = WorkspaceCollector(_make_config())
        self.repo = RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description=None,
            local_branch=None,
        )

    def test_returns_success_when_last_run_passed(self):
        api_response = {"workflow_runs": [{"conclusion": "success"}]}
        with patch.object(self.collector, "_run_json", return_value=api_response):
            self.collector._collect_ci_conclusion(self.repo, "reneeqian/my_repo", "forge-health.yml")
        assert self.repo.last_ci_conclusion == "success"

    def test_returns_failure_when_last_run_failed(self):
        api_response = {"workflow_runs": [{"conclusion": "failure"}]}
        with patch.object(self.collector, "_run_json", return_value=api_response):
            self.collector._collect_ci_conclusion(self.repo, "reneeqian/my_repo", "forge-health.yml")
        assert self.repo.last_ci_conclusion == "failure"

    def test_returns_none_when_no_runs(self):
        api_response = {"workflow_runs": []}
        with patch.object(self.collector, "_run_json", return_value=api_response):
            self.collector._collect_ci_conclusion(self.repo, "reneeqian/my_repo", "forge-health.yml")
        assert self.repo.last_ci_conclusion is None

    def test_returns_none_when_api_fails(self):
        with patch.object(self.collector, "_run_json", return_value=None):
            self.collector._collect_ci_conclusion(self.repo, "reneeqian/my_repo", "forge-health.yml")
        assert self.repo.last_ci_conclusion is None


# ── Step 5: _compute_issues tests ─────────────────────────────────────────────


class TestComputeIssues:
    def setup_method(self):
        self.collector = WorkspaceCollector(_make_config())

    def _fully_configured_code_repo(self) -> RepoStatus:
        return RepoStatus(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            visibility="public",
            description="A well-configured repo",
            local_branch="dev",
            auto_merge=True,
            delete_on_merge=True,
            rebase_allowed=False,
            has_codeowners=True,
            workflows=["forge-health.yml", "auto-merge.yml"],
            branch_protection=[
                BranchProtectionStatus(
                    branch="main",
                    protected=True,
                    required_checks=["forge-health"],
                    strict=True,
                    required_reviews=1,
                ),
                BranchProtectionStatus(branch="dev", protected=True, required_checks=["forge-health"]),
            ],
            rulesets=[
                RulesetStatus(
                    name="protect the main",
                    scope="~DEFAULT_BRANCH",
                    enforcement="active",
                    has_ci_check=False,
                    has_bypass_actor=True,
                ),
                RulesetStatus(
                    name="Dev branch — require CI",
                    scope="refs/heads/dev",
                    enforcement="active",
                    has_ci_check=True,
                    has_bypass_actor=False,
                ),
            ],
        )

    def _fully_configured_docs_repo(self) -> RepoStatus:
        return RepoStatus(
            name="SaMD-DHF-Templates",
            owner="reneeqian",
            repo_type="docs",
            visibility="public",
            description="A documentation repo",
            local_branch="dev",
            auto_merge=True,
            delete_on_merge=True,
            rebase_allowed=False,
            has_codeowners=True,
            workflows=["forge-health.yml", "auto-merge.yml"],
            branch_protection=[
                BranchProtectionStatus(
                    branch="main",
                    protected=True,
                    required_checks=["forge-health"],
                ),
            ],
            rulesets=[
                RulesetStatus(
                    name="protect the main",
                    scope="~DEFAULT_BRANCH",
                    enforcement="active",
                    has_ci_check=False,
                    has_bypass_actor=True,
                ),
            ],
        )

    def test_no_issues_for_fully_configured_code_repo(self):
        repo = self._fully_configured_code_repo()
        issues = self.collector._compute_issues(repo)
        assert issues == []

    def test_no_issues_for_fully_configured_docs_repo(self):
        repo = self._fully_configured_docs_repo()
        issues = self.collector._compute_issues(repo)
        assert issues == []

    def test_flags_auto_merge_off(self):
        repo = self._fully_configured_code_repo()
        repo.auto_merge = False
        issues = self.collector._compute_issues(repo)
        assert any("auto-merge" in i for i in issues)

    def test_flags_rebase_on(self):
        repo = self._fully_configured_code_repo()
        repo.rebase_allowed = True
        issues = self.collector._compute_issues(repo)
        assert any("rebase" in i for i in issues)

    def test_flags_delete_on_merge_off(self):
        repo = self._fully_configured_code_repo()
        repo.delete_on_merge = False
        issues = self.collector._compute_issues(repo)
        assert any("delete branch" in i for i in issues)

    def test_flags_no_classic_protection_on_main(self):
        repo = self._fully_configured_code_repo()
        repo.branch_protection = [
            BranchProtectionStatus(branch="main", protected=False),
            BranchProtectionStatus(branch="dev", protected=True, required_checks=["forge-health"]),
        ]
        issues = self.collector._compute_issues(repo)
        assert any("no classic branch protection" in i for i in issues)

    def test_flags_no_ci_check_on_main(self):
        repo = self._fully_configured_code_repo()
        repo.branch_protection = [
            BranchProtectionStatus(branch="main", protected=True, required_checks=[]),
            BranchProtectionStatus(branch="dev", protected=True),
        ]
        issues = self.collector._compute_issues(repo)
        assert any("no required CI check" in i for i in issues)

    def test_flags_missing_codeowners(self):
        repo = self._fully_configured_code_repo()
        repo.has_codeowners = False
        issues = self.collector._compute_issues(repo)
        assert any("CODEOWNERS" in i for i in issues)

    def test_flags_missing_forge_health_workflow_for_code_repo(self):
        repo = self._fully_configured_code_repo()
        repo.workflows = ["auto-merge.yml"]
        issues = self.collector._compute_issues(repo)
        assert any("forge-health.yml" in i for i in issues)

    def test_does_not_flag_missing_forge_health_for_docs_repo(self):
        repo = self._fully_configured_docs_repo()
        repo.workflows = ["auto-merge.yml"]
        issues = self.collector._compute_issues(repo)
        assert not any("forge-health.yml" in i for i in issues)

    def test_flags_no_workflows_for_docs_repo(self):
        repo = self._fully_configured_docs_repo()
        repo.workflows = []
        issues = self.collector._compute_issues(repo)
        assert any("no CI workflows" in i for i in issues)

    def test_flags_non_standard_ruleset_name(self):
        repo = self._fully_configured_code_repo()
        repo.rulesets = [
            RulesetStatus(
                name="Protect Main Branch",
                scope="refs/heads/main",
                enforcement="active",
                has_ci_check=False,
                has_bypass_actor=False,
            )
        ]
        issues = self.collector._compute_issues(repo)
        assert any("non-standard ruleset" in i for i in issues)

    def test_flags_missing_repo_description(self):
        repo = self._fully_configured_code_repo()
        repo.description = None
        issues = self.collector._compute_issues(repo)
        assert any("no repository description" in i for i in issues)

    def test_empty_description_string_also_flagged(self):
        repo = self._fully_configured_code_repo()
        repo.description = ""
        issues = self.collector._compute_issues(repo)
        assert any("no repository description" in i for i in issues)

    def test_multiple_issues_all_returned(self):
        repo = self._fully_configured_code_repo()
        repo.auto_merge = False
        repo.rebase_allowed = True
        repo.has_codeowners = False
        issues = self.collector._compute_issues(repo)
        assert len(issues) >= 3


# ── Step 5b: branch checks and open PR collection ─────────────────────────────


class TestCollectBranchChecks:
    def setup_method(self):
        self.collector = WorkspaceCollector(_make_config())
        self.repo = RepoStatus(
            name="my_repo", owner="reneeqian", repo_type="code",
            visibility="public", description=None, local_branch="dev",
        )

    def test_parses_passed_and_total(self):
        api_response = {
            "check_runs": [
                {"conclusion": "success"},
                {"conclusion": "success"},
                {"conclusion": "failure"},
            ]
        }
        with patch.object(self.collector, "_run_json", return_value=api_response):
            self.collector._collect_branch_checks(self.repo, "reneeqian/my_repo")
        assert self.repo.branch_ci_passed == 2
        assert self.repo.branch_ci_total == 3

    def test_all_pass(self):
        api_response = {"check_runs": [{"conclusion": "success"}, {"conclusion": "success"}]}
        with patch.object(self.collector, "_run_json", return_value=api_response):
            self.collector._collect_branch_checks(self.repo, "reneeqian/my_repo")
        assert self.repo.branch_ci_passed == 2
        assert self.repo.branch_ci_total == 2

    def test_empty_runs_leaves_totals_none(self):
        api_response = {"check_runs": []}
        with patch.object(self.collector, "_run_json", return_value=api_response):
            self.collector._collect_branch_checks(self.repo, "reneeqian/my_repo")
        assert self.repo.branch_ci_total is None
        assert self.repo.branch_ci_passed is None

    def test_no_branch_skips_call(self):
        self.repo.local_branch = None
        with patch.object(self.collector, "_run_json") as mock_rj:
            self.collector._collect_branch_checks(self.repo, "reneeqian/my_repo")
        mock_rj.assert_not_called()

    def test_api_failure_leaves_totals_none(self):
        with patch.object(self.collector, "_run_json", return_value=None):
            self.collector._collect_branch_checks(self.repo, "reneeqian/my_repo")
        assert self.repo.branch_ci_total is None


class TestCollectOpenPR:
    def setup_method(self):
        self.collector = WorkspaceCollector(_make_config())
        self.repo = RepoStatus(
            name="my_repo", owner="reneeqian", repo_type="code",
            visibility="public", description=None, local_branch="feat-my-feature",
        )

    def test_parses_pr_number_and_url(self):
        api_response = [{"number": 42, "html_url": "https://github.com/reneeqian/my_repo/pull/42"}]
        with patch.object(self.collector, "_run_json", return_value=api_response):
            self.collector._collect_open_pr(self.repo, "reneeqian/my_repo")
        assert self.repo.open_pr_number == 42
        assert self.repo.open_pr_url == "https://github.com/reneeqian/my_repo/pull/42"

    def test_no_open_prs_leaves_none(self):
        with patch.object(self.collector, "_run_json", return_value=[]):
            self.collector._collect_open_pr(self.repo, "reneeqian/my_repo")
        assert self.repo.open_pr_number is None
        assert self.repo.open_pr_url is None

    def test_no_branch_skips_call(self):
        self.repo.local_branch = None
        with patch.object(self.collector, "_run_json") as mock_rj:
            self.collector._collect_open_pr(self.repo, "reneeqian/my_repo")
        mock_rj.assert_not_called()

    def test_api_failure_leaves_none(self):
        with patch.object(self.collector, "_run_json", return_value=None):
            self.collector._collect_open_pr(self.repo, "reneeqian/my_repo")
        assert self.repo.open_pr_number is None


# ── Step 6: collect_all orchestration tests ────────────────────────────────────


class TestCollectAll:
    def setup_method(self):
        self.repo_cfg = _make_repo_config("medical_image_ai_toolkit")
        self.config = _make_config([self.repo_cfg])
        self.collector = WorkspaceCollector(self.config)

    def _patch_all_steps(self):
        """Returns a context manager that no-ops all individual collection methods."""
        stack = ExitStack()
        for method in [
            "_collect_repo_settings",
            "_collect_branch_protection",
            "_collect_rulesets",
            "_collect_ci_conclusion",
            "_collect_branch_checks",
            "_collect_open_pr",
        ]:
            stack.enter_context(patch.object(self.collector, method))
        stack.enter_context(patch.object(self.collector, "_collect_local_files"))
        stack.enter_context(patch.object(self.collector, "_compute_issues", return_value=[]))
        return stack

    def test_returns_workspace_report_with_one_repo(self):
        with self._patch_all_steps():
            report = self.collector.collect_all()
        assert report.total_repos == 1
        assert report.repos[0].name == "medical_image_ai_toolkit"

    def test_returns_workspace_report_with_multiple_repos(self):
        cfg = _make_config([
            _make_repo_config("repo_a"),
            _make_repo_config("repo_b"),
        ])
        c = WorkspaceCollector(cfg)
        with patch.object(c, "_collect_repo_settings"), \
             patch.object(c, "_collect_branch_protection"), \
             patch.object(c, "_collect_rulesets"), \
             patch.object(c, "_collect_ci_conclusion"), \
             patch.object(c, "_collect_local_files"), \
             patch.object(c, "_compute_issues", return_value=[]):
            report = c.collect_all()
        assert report.total_repos == 2

    def test_collection_error_stored_not_raised(self):
        with patch.object(self.collector, "_collect_repo_settings", side_effect=RuntimeError("boom")), \
             patch.object(self.collector, "_collect_branch_protection"), \
             patch.object(self.collector, "_collect_rulesets"), \
             patch.object(self.collector, "_collect_ci_conclusion"), \
             patch.object(self.collector, "_collect_local_files"), \
             patch.object(self.collector, "_compute_issues", return_value=[]):
            report = self.collector.collect_all()

        assert report.repos[0].collection_error is not None

    def test_gh_unavailable_sets_error_on_all_repos(self):
        cfg = _make_config([_make_repo_config("a"), _make_repo_config("b")])
        c = WorkspaceCollector(cfg)
        with patch.object(c, "_gh_available", return_value=False):
            report = c.collect_all()
        assert all(r.collection_error is not None for r in report.repos)

    def test_run_health_false_skips_health_collection(self):
        with self._patch_all_steps():
            with patch.object(self.collector, "_collect_forge_health") as mock_health:
                self.collector.collect_all(run_health=False)
            mock_health.assert_not_called()

    def test_run_health_true_calls_forge_health(self):
        with self._patch_all_steps():
            with patch.object(self.collector, "_collect_forge_health") as mock_health:
                self.collector.collect_all(run_health=True)
            mock_health.assert_called_once()

    def test_health_grade_parsed_from_json_output(self):
        health_json = '{"grade": "A", "overall_score": 0.95, "test_metrics": {"score": 0.90}, "complexity": {"score": null}}'
        mock_proc = MagicMock(returncode=0, stdout=health_json)
        repo_cfg_with_path = RepoConfig(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            local_path=Path("/tmp/fake"),
        )
        cfg = _make_config([repo_cfg_with_path])
        c = WorkspaceCollector(cfg)
        with patch.object(c, "_collect_repo_settings"), \
             patch.object(c, "_collect_branch_protection"), \
             patch.object(c, "_collect_rulesets"), \
             patch.object(c, "_collect_ci_conclusion"), \
             patch.object(c, "_collect_local_files"), \
             patch.object(c, "_compute_issues", return_value=[]), \
             patch("subprocess.run", return_value=mock_proc):
            report = c.collect_all(run_health=True)

        repo = report.repos[0]
        assert repo.forge_health_grade == "A"
        assert repo.forge_health_score == 0.95
        assert repo.forge_health_collectors["test_metrics"] == 0.90
        assert repo.forge_health_collectors["complexity"] is None

    def test_health_collectors_absent_in_json_stored_as_none(self):
        health_json = '{"grade": "B", "overall_score": 0.85}'
        mock_proc = MagicMock(returncode=0, stdout=health_json)
        repo_cfg_with_path = RepoConfig(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            local_path=Path("/tmp/fake"),
        )
        cfg = _make_config([repo_cfg_with_path])
        c = WorkspaceCollector(cfg)
        with patch.object(c, "_collect_repo_settings"), \
             patch.object(c, "_collect_branch_protection"), \
             patch.object(c, "_collect_rulesets"), \
             patch.object(c, "_collect_ci_conclusion"), \
             patch.object(c, "_collect_local_files"), \
             patch.object(c, "_compute_issues", return_value=[]), \
             patch("subprocess.run", return_value=mock_proc):
            report = c.collect_all(run_health=True)

        repo = report.repos[0]
        assert repo.forge_health_collectors["test_metrics"] is None
        assert repo.forge_health_collectors["static_analysis"] is None

    def test_health_collection_failure_does_not_fail_repo(self):
        repo_cfg_with_path = RepoConfig(
            name="my_repo",
            owner="reneeqian",
            repo_type="code",
            local_path=Path("/tmp/fake"),
        )
        cfg = _make_config([repo_cfg_with_path])
        c = WorkspaceCollector(cfg)
        with patch.object(c, "_gh_available", return_value=True), \
             patch.object(c, "_collect_repo_settings"), \
             patch.object(c, "_collect_branch_protection"), \
             patch.object(c, "_collect_rulesets"), \
             patch.object(c, "_collect_ci_conclusion"), \
             patch.object(c, "_collect_local_files"), \
             patch.object(c, "_compute_issues", return_value=[]), \
             patch("subprocess.run", side_effect=FileNotFoundError):
            report = c.collect_all(run_health=True)

        assert report.repos[0].forge_health_grade is None
        assert report.repos[0].collection_error is None
