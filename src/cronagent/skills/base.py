"""
Base skill interface for extensible agent capabilities.

Skills provide:
- Tool definitions for Claude
- MCP server integration
- Prompt/documentation injection
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


class SkillCategory(str, Enum):
    """Categories for organizing skills."""

    DEVELOPMENT = "development"
    DEVOPS = "devops"
    COMMUNICATION = "communication"
    DATA = "data"
    UTILITY = "utility"
    CUSTOM = "custom"


@dataclass
class SkillMetadata:
    """Metadata describing a skill."""

    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    category: SkillCategory = SkillCategory.CUSTOM
    tags: list[str] = field(default_factory=list)
    requires_auth: bool = False
    auth_env_vars: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "category": self.category.value,
            "tags": self.tags,
            "requires_auth": self.requires_auth,
            "auth_env_vars": self.auth_env_vars,
        }


@dataclass
class ToolParameter:
    """Parameter definition for a tool."""

    name: str
    description: str
    type: str = "string"  # string, number, boolean, array, object
    required: bool = True
    default: Any = None
    enum: list[Any] | None = None

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema format."""
        schema: dict[str, Any] = {
            "type": self.type,
            "description": self.description,
        }

        if self.enum:
            schema["enum"] = self.enum

        if self.default is not None:
            schema["default"] = self.default

        return schema


@dataclass
class SkillTool:
    """
    Tool definition for a skill.

    Each tool represents a capability that Claude can invoke.
    """

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    handler: Callable[..., Awaitable[Any]] | None = None

    # Tool behavior hints
    requires_confirmation: bool = False
    is_destructive: bool = False
    timeout: int = 60  # seconds

    def to_claude_format(self) -> dict[str, Any]:
        """
        Convert to Claude tool format.

        Returns a dict compatible with Claude's tool use API.
        """
        properties = {}
        required = []

        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool with given parameters."""
        if not self.handler:
            raise NotImplementedError(f"No handler for tool: {self.name}")

        return await self.handler(**kwargs)


class Skill(ABC):
    """
    Abstract base class for skills.

    Skills extend CronAgent's capabilities by providing:
    - Tools that Claude can use
    - Documentation for prompts
    - Optional MCP server integration

    Example usage:
        class GitHubSkill(Skill):
            @property
            def metadata(self) -> SkillMetadata:
                return SkillMetadata(
                    name="github",
                    description="GitHub repository operations",
                    category=SkillCategory.DEVELOPMENT,
                )

            def get_tools(self) -> list[SkillTool]:
                return [
                    SkillTool(
                        name="github_create_pr",
                        description="Create a pull request",
                        parameters=[...],
                        handler=self._create_pr,
                    ),
                ]

            async def _create_pr(self, title: str, body: str) -> dict:
                # Implementation
                pass
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialize the skill.

        Args:
            config: Skill-specific configuration
        """
        self.config = config or {}
        self._initialized = False

    @property
    @abstractmethod
    def metadata(self) -> SkillMetadata:
        """Return skill metadata."""
        pass

    @abstractmethod
    def get_tools(self) -> list[SkillTool]:
        """
        Return list of tools provided by this skill.

        Each tool should have a name, description, parameters,
        and optionally a handler function.
        """
        pass

    async def initialize(self) -> None:
        """
        Initialize the skill.

        Override to perform async initialization (e.g., API client setup).
        Called once when the skill is registered.
        """
        self._initialized = True

    async def shutdown(self) -> None:
        """
        Shutdown the skill.

        Override to perform cleanup (e.g., close connections).
        """
        self._initialized = False

    def get_documentation(self) -> str:
        """
        Return documentation to inject into system prompts.

        Override to provide context about skill usage.
        """
        meta = self.metadata
        tools = self.get_tools()

        doc_parts = [
            f"## {meta.name} Skill",
            f"{meta.description}",
            "",
            "### Available Tools:",
        ]

        for tool in tools:
            params_str = ", ".join(
                f"{p.name}: {p.type}" for p in tool.parameters
            )
            doc_parts.append(f"- **{tool.name}**({params_str}): {tool.description}")

        return "\n".join(doc_parts)

    def get_tool_names(self) -> list[str]:
        """Return list of tool names."""
        return [tool.name for tool in self.get_tools()]

    def get_tool(self, name: str) -> SkillTool | None:
        """Get a tool by name."""
        for tool in self.get_tools():
            if tool.name == name:
                return tool
        return None

    async def execute_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute
            **kwargs: Tool parameters

        Returns:
            Tool execution result

        Raises:
            ValueError: If tool not found
            Exception: If tool execution fails
        """
        tool = self.get_tool(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")

        return await tool.execute(**kwargs)

    def check_auth(self) -> bool:
        """
        Check if required authentication is available.

        Returns True if all required auth is present.
        """
        import os

        meta = self.metadata
        if not meta.requires_auth:
            return True

        for env_var in meta.auth_env_vars:
            if not os.environ.get(env_var):
                logger.warning(f"Missing auth env var: {env_var}")
                return False

        return True

    def to_mcp_server(self) -> dict[str, Any]:
        """
        Convert skill to MCP server configuration.

        Returns config dict for Claude SDK's mcp_servers parameter.
        """
        tools = [tool.to_claude_format() for tool in self.get_tools()]

        return {
            "name": self.metadata.name,
            "description": self.metadata.description,
            "tools": tools,
        }

    @property
    def is_initialized(self) -> bool:
        """Check if skill is initialized."""
        return self._initialized


def skill_tool(
    name: str | None = None,
    description: str = "",
    requires_confirmation: bool = False,
    is_destructive: bool = False,
    timeout: int = 60,
) -> Callable:
    """
    Decorator to mark a method as a skill tool.

    Usage:
        class MySkill(Skill):
            @skill_tool(
                name="my_tool",
                description="Does something useful",
            )
            async def my_tool(self, param1: str, param2: int = 10) -> str:
                return f"Result: {param1} {param2}"
    """
    def decorator(func: Callable) -> Callable:
        # Store tool metadata on the function
        func._skill_tool = {
            "name": name or func.__name__,
            "description": description or func.__doc__ or "",
            "requires_confirmation": requires_confirmation,
            "is_destructive": is_destructive,
            "timeout": timeout,
        }
        return func

    return decorator


def extract_tool_parameters(func: Callable) -> list[ToolParameter]:
    """
    Extract tool parameters from function signature.

    Uses type hints and defaults to build parameter definitions.
    """
    import inspect

    params = []
    sig = inspect.signature(func)

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        # Determine type from annotation
        param_type = "string"
        if param.annotation != inspect.Parameter.empty:
            ann = param.annotation
            if ann == int:
                param_type = "number"
            elif ann == bool:
                param_type = "boolean"
            elif ann == list:
                param_type = "array"
            elif ann == dict:
                param_type = "object"

        # Check if required
        required = param.default == inspect.Parameter.empty
        default = None if required else param.default

        params.append(ToolParameter(
            name=param_name,
            description=f"Parameter: {param_name}",
            type=param_type,
            required=required,
            default=default,
        ))

    return params


class DecoratorSkill(Skill):
    """
    Base class for skills using decorator-based tool definitions.

    Automatically discovers methods decorated with @skill_tool.
    """

    def get_tools(self) -> list[SkillTool]:
        """Discover tools from decorated methods."""
        tools = []

        for name in dir(self):
            if name.startswith("_"):
                continue

            method = getattr(self, name)
            if not callable(method):
                continue

            if hasattr(method, "_skill_tool"):
                meta = method._skill_tool
                params = extract_tool_parameters(method)

                tools.append(SkillTool(
                    name=meta["name"],
                    description=meta["description"],
                    parameters=params,
                    handler=method,
                    requires_confirmation=meta["requires_confirmation"],
                    is_destructive=meta["is_destructive"],
                    timeout=meta["timeout"],
                ))

        return tools
