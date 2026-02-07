"""Extensible skills system."""

from cronagent.skills.base import (
    DecoratorSkill,
    Skill,
    SkillCategory,
    SkillMetadata,
    SkillTool,
    ToolParameter,
    extract_tool_parameters,
    skill_tool,
)
from cronagent.skills.registry import SkillRegistry, create_skill_registry

__all__ = [
    # Base classes
    "DecoratorSkill",
    "Skill",
    "SkillCategory",
    "SkillMetadata",
    "SkillTool",
    "ToolParameter",
    # Decorators and utilities
    "extract_tool_parameters",
    "skill_tool",
    # Registry
    "SkillRegistry",
    "create_skill_registry",
]

# Optional: Export builtin skills
try:
    from cronagent.skills.builtin import DeploySkill, GitHubSkill, NotifySkill

    __all__.extend(["DeploySkill", "GitHubSkill", "NotifySkill"])
except ImportError:
    pass
