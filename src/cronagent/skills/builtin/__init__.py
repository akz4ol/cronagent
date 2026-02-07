"""Built-in skills for CronAgent."""

from cronagent.skills.builtin.deploy import DeploySkill
from cronagent.skills.builtin.github import GitHubSkill
from cronagent.skills.builtin.notify import NotifySkill

__all__ = [
    "DeploySkill",
    "GitHubSkill",
    "NotifySkill",
]
