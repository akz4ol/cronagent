"""
GitHub skill for repository operations.

Provides tools for:
- Repository management
- Pull request operations
- Issue tracking
- Code review
"""

from __future__ import annotations

import logging
import os
from typing import Any

from cronagent.skills.base import (
    DecoratorSkill,
    Skill,
    SkillCategory,
    SkillMetadata,
    SkillTool,
    ToolParameter,
    skill_tool,
)

logger = logging.getLogger(__name__)


class GitHubSkill(DecoratorSkill):
    """
    GitHub operations skill.

    Provides tools for interacting with GitHub repositories,
    pull requests, issues, and more.

    Requires:
    - GITHUB_TOKEN environment variable

    Config options:
        default_owner: Default repository owner
        default_repo: Default repository name
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._client: Any = None
        self._default_owner = self.config.get("default_owner", "")
        self._default_repo = self.config.get("default_repo", "")

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="github",
            description="GitHub repository operations",
            version="1.0.0",
            category=SkillCategory.DEVELOPMENT,
            tags=["git", "vcs", "repository", "pr", "issues"],
            requires_auth=True,
            auth_env_vars=["GITHUB_TOKEN"],
        )

    async def initialize(self) -> None:
        """Initialize GitHub client."""
        try:
            from github import Github

            token = os.environ.get("GITHUB_TOKEN", "")
            if token:
                self._client = Github(token)
                logger.info("GitHub skill initialized")
            else:
                logger.warning("GITHUB_TOKEN not set, GitHub skill will be limited")

        except ImportError:
            logger.warning("PyGithub not installed, GitHub skill unavailable")

        await super().initialize()

    async def shutdown(self) -> None:
        """Shutdown GitHub client."""
        if self._client:
            self._client.close()
            self._client = None
        await super().shutdown()

    def _get_repo(self, owner: str | None = None, repo: str | None = None) -> Any:
        """Get repository object."""
        if not self._client:
            raise RuntimeError("GitHub client not initialized")

        owner = owner or self._default_owner
        repo = repo or self._default_repo

        if not owner or not repo:
            raise ValueError("Owner and repo must be specified")

        return self._client.get_repo(f"{owner}/{repo}")

    @skill_tool(
        name="github_create_pr",
        description="Create a pull request",
    )
    async def create_pr(
        self,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        owner: str = "",
        repo: str = "",
        draft: bool = False,
    ) -> dict[str, Any]:
        """Create a pull request."""
        repository = self._get_repo(owner, repo)

        pr = repository.create_pull(
            title=title,
            body=body,
            head=head,
            base=base,
            draft=draft,
        )

        return {
            "number": pr.number,
            "url": pr.html_url,
            "state": pr.state,
            "title": pr.title,
        }

    @skill_tool(
        name="github_list_prs",
        description="List pull requests",
    )
    async def list_prs(
        self,
        state: str = "open",
        owner: str = "",
        repo: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """List pull requests."""
        repository = self._get_repo(owner, repo)

        prs = repository.get_pulls(state=state)[:limit]

        return [
            {
                "number": pr.number,
                "title": pr.title,
                "state": pr.state,
                "author": pr.user.login,
                "url": pr.html_url,
                "created_at": pr.created_at.isoformat(),
            }
            for pr in prs
        ]

    @skill_tool(
        name="github_get_pr",
        description="Get pull request details",
    )
    async def get_pr(
        self,
        number: int,
        owner: str = "",
        repo: str = "",
    ) -> dict[str, Any]:
        """Get pull request details."""
        repository = self._get_repo(owner, repo)
        pr = repository.get_pull(number)

        return {
            "number": pr.number,
            "title": pr.title,
            "body": pr.body,
            "state": pr.state,
            "author": pr.user.login,
            "url": pr.html_url,
            "mergeable": pr.mergeable,
            "additions": pr.additions,
            "deletions": pr.deletions,
            "changed_files": pr.changed_files,
            "created_at": pr.created_at.isoformat(),
            "labels": [l.name for l in pr.labels],
        }

    @skill_tool(
        name="github_merge_pr",
        description="Merge a pull request",
        requires_confirmation=True,
        is_destructive=True,
    )
    async def merge_pr(
        self,
        number: int,
        merge_method: str = "squash",
        owner: str = "",
        repo: str = "",
    ) -> dict[str, Any]:
        """Merge a pull request."""
        repository = self._get_repo(owner, repo)
        pr = repository.get_pull(number)

        result = pr.merge(merge_method=merge_method)

        return {
            "merged": result.merged,
            "sha": result.sha,
            "message": result.message,
        }

    @skill_tool(
        name="github_create_issue",
        description="Create an issue",
    )
    async def create_issue(
        self,
        title: str,
        body: str = "",
        labels: list[str] = [],
        owner: str = "",
        repo: str = "",
    ) -> dict[str, Any]:
        """Create an issue."""
        repository = self._get_repo(owner, repo)

        issue = repository.create_issue(
            title=title,
            body=body,
            labels=labels,
        )

        return {
            "number": issue.number,
            "url": issue.html_url,
            "title": issue.title,
        }

    @skill_tool(
        name="github_list_issues",
        description="List issues",
    )
    async def list_issues(
        self,
        state: str = "open",
        labels: list[str] = [],
        owner: str = "",
        repo: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """List issues."""
        repository = self._get_repo(owner, repo)

        issues = repository.get_issues(
            state=state,
            labels=labels if labels else None,
        )[:limit]

        return [
            {
                "number": issue.number,
                "title": issue.title,
                "state": issue.state,
                "author": issue.user.login,
                "url": issue.html_url,
                "labels": [l.name for l in issue.labels],
                "created_at": issue.created_at.isoformat(),
            }
            for issue in issues
            if not issue.pull_request  # Exclude PRs
        ]

    @skill_tool(
        name="github_add_comment",
        description="Add a comment to an issue or PR",
    )
    async def add_comment(
        self,
        number: int,
        body: str,
        owner: str = "",
        repo: str = "",
    ) -> dict[str, Any]:
        """Add a comment to an issue or PR."""
        repository = self._get_repo(owner, repo)
        issue = repository.get_issue(number)

        comment = issue.create_comment(body)

        return {
            "id": comment.id,
            "url": comment.html_url,
        }

    @skill_tool(
        name="github_get_file",
        description="Get file contents from repository",
    )
    async def get_file(
        self,
        path: str,
        ref: str = "main",
        owner: str = "",
        repo: str = "",
    ) -> dict[str, Any]:
        """Get file contents."""
        repository = self._get_repo(owner, repo)

        try:
            content = repository.get_contents(path, ref=ref)

            if isinstance(content, list):
                # Directory
                return {
                    "type": "directory",
                    "path": path,
                    "contents": [
                        {"name": f.name, "type": f.type, "path": f.path}
                        for f in content
                    ],
                }
            else:
                # File
                return {
                    "type": "file",
                    "path": content.path,
                    "size": content.size,
                    "sha": content.sha,
                    "content": content.decoded_content.decode("utf-8"),
                }

        except Exception as e:
            return {
                "error": str(e),
                "path": path,
            }

    @skill_tool(
        name="github_list_branches",
        description="List repository branches",
    )
    async def list_branches(
        self,
        owner: str = "",
        repo: str = "",
    ) -> list[dict[str, Any]]:
        """List branches."""
        repository = self._get_repo(owner, repo)

        return [
            {
                "name": branch.name,
                "sha": branch.commit.sha,
                "protected": branch.protected,
            }
            for branch in repository.get_branches()
        ]

    @skill_tool(
        name="github_get_workflow_runs",
        description="Get recent workflow runs",
    )
    async def get_workflow_runs(
        self,
        workflow: str = "",
        status: str = "",
        owner: str = "",
        repo: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Get workflow runs."""
        repository = self._get_repo(owner, repo)

        kwargs = {}
        if status:
            kwargs["status"] = status

        if workflow:
            runs = repository.get_workflow(workflow).get_runs(**kwargs)
        else:
            runs = repository.get_workflow_runs(**kwargs)

        return [
            {
                "id": run.id,
                "name": run.name,
                "status": run.status,
                "conclusion": run.conclusion,
                "url": run.html_url,
                "created_at": run.created_at.isoformat(),
            }
            for run in list(runs)[:limit]
        ]
