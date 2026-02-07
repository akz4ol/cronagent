"""
Skill registry for discovery and management.

Provides:
- Skill registration and discovery
- Built-in and user-defined skill loading
- Tool execution routing
- MCP server generation
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from cronagent.bus.events import EventBus, Events
from cronagent.skills.base import Skill, SkillCategory, SkillMetadata, SkillTool

logger = logging.getLogger(__name__)


class SkillRegistry:
    """
    Central registry for skill management.

    Handles:
    - Skill registration and lookup
    - Built-in skill loading
    - User-defined skill discovery
    - Tool execution routing

    Usage:
        registry = SkillRegistry(event_bus)

        # Load built-in skills
        await registry.load_builtin_skills()

        # Load user skills from directory
        await registry.load_from_directory("~/.cronagent/skills")

        # Register a skill manually
        registry.register(my_skill)

        # Get all tool definitions
        tools = registry.get_all_tools()

        # Execute a tool
        result = await registry.execute_tool("github_create_pr", title="Fix bug")
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.config = config or {}

        self._skills: dict[str, Skill] = {}
        self._tool_map: dict[str, tuple[str, SkillTool]] = {}  # tool_name -> (skill_name, tool)

    def register(self, skill: Skill) -> None:
        """
        Register a skill.

        Args:
            skill: Skill instance to register
        """
        meta = skill.metadata
        name = meta.name

        if name in self._skills:
            logger.warning(f"Skill already registered, replacing: {name}")

        self._skills[name] = skill

        # Index tools
        for tool in skill.get_tools():
            if tool.name in self._tool_map:
                existing_skill, _ = self._tool_map[tool.name]
                logger.warning(
                    f"Tool name conflict: {tool.name} "
                    f"(from {existing_skill}, overwriting with {name})"
                )

            self._tool_map[tool.name] = (name, tool)

        logger.info(f"Registered skill: {name} with {len(skill.get_tools())} tools")

    def unregister(self, name: str) -> bool:
        """Unregister a skill by name."""
        if name not in self._skills:
            return False

        skill = self._skills[name]

        # Remove tool mappings
        for tool in skill.get_tools():
            if tool.name in self._tool_map:
                del self._tool_map[tool.name]

        del self._skills[name]
        logger.info(f"Unregistered skill: {name}")

        return True

    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def list_skills(
        self,
        category: SkillCategory | None = None,
    ) -> list[SkillMetadata]:
        """
        List registered skills.

        Args:
            category: Filter by category

        Returns:
            List of skill metadata
        """
        result = []
        for skill in self._skills.values():
            meta = skill.metadata
            if category and meta.category != category:
                continue
            result.append(meta)
        return result

    def get_tool(self, name: str) -> SkillTool | None:
        """Get a tool by name."""
        if name in self._tool_map:
            _, tool = self._tool_map[name]
            return tool
        return None

    def get_all_tools(self) -> list[SkillTool]:
        """Get all registered tools."""
        return [tool for _, tool in self._tool_map.values()]

    def get_tool_names(self) -> list[str]:
        """Get names of all registered tools."""
        return list(self._tool_map.keys())

    async def execute_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool
            **kwargs: Tool parameters

        Returns:
            Tool execution result

        Raises:
            ValueError: If tool not found
        """
        if tool_name not in self._tool_map:
            raise ValueError(f"Tool not found: {tool_name}")

        skill_name, tool = self._tool_map[tool_name]

        logger.debug(f"Executing tool {tool_name} from skill {skill_name}")

        # Emit event
        if self.event_bus:
            await self.event_bus.emit(
                "skill.tool_executing",
                {
                    "skill": skill_name,
                    "tool": tool_name,
                    "params": list(kwargs.keys()),
                },
            )

        try:
            result = await tool.execute(**kwargs)

            if self.event_bus:
                await self.event_bus.emit(
                    "skill.tool_completed",
                    {
                        "skill": skill_name,
                        "tool": tool_name,
                        "success": True,
                    },
                )

            return result

        except Exception as e:
            if self.event_bus:
                await self.event_bus.emit(
                    "skill.tool_failed",
                    {
                        "skill": skill_name,
                        "tool": tool_name,
                        "error": str(e),
                    },
                )
            raise

    def get_documentation(self) -> str:
        """
        Get combined documentation for all skills.

        Returns formatted string for system prompt injection.
        """
        if not self._skills:
            return ""

        parts = ["# Available Skills\n"]

        for skill in self._skills.values():
            parts.append(skill.get_documentation())
            parts.append("")

        return "\n".join(parts)

    def as_mcp_servers(self) -> dict[str, Any]:
        """
        Convert all skills to MCP server configurations.

        Returns dict for Claude SDK's mcp_servers parameter.
        """
        servers = {}

        for name, skill in self._skills.items():
            servers[name] = skill.to_mcp_server()

        return servers

    def get_claude_tools(self) -> list[dict[str, Any]]:
        """
        Get all tools in Claude API format.

        Returns list of tool definitions for Claude's tools parameter.
        """
        return [tool.to_claude_format() for tool in self.get_all_tools()]

    async def initialize_all(self) -> None:
        """Initialize all registered skills."""
        for name, skill in self._skills.items():
            if not skill.is_initialized:
                try:
                    await skill.initialize()
                    logger.debug(f"Initialized skill: {name}")
                except Exception as e:
                    logger.error(f"Failed to initialize skill {name}: {e}")

    async def shutdown_all(self) -> None:
        """Shutdown all registered skills."""
        for name, skill in self._skills.items():
            if skill.is_initialized:
                try:
                    await skill.shutdown()
                    logger.debug(f"Shutdown skill: {name}")
                except Exception as e:
                    logger.error(f"Failed to shutdown skill {name}: {e}")

    async def load_builtin_skills(self) -> int:
        """
        Load built-in skills.

        Returns number of skills loaded.
        """
        loaded = 0

        # List of built-in skill modules
        builtin_skills = [
            "cronagent.skills.builtin.github",
            "cronagent.skills.builtin.deploy",
            "cronagent.skills.builtin.notify",
        ]

        for module_name in builtin_skills:
            try:
                module = importlib.import_module(module_name)

                # Look for skill class
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, Skill)
                        and attr is not Skill
                        and not attr_name.startswith("_")
                    ):
                        # Get skill config from registry config
                        skill_config = self.config.get(attr_name.lower(), {})

                        # Instantiate and register
                        skill = attr(skill_config)
                        self.register(skill)
                        await skill.initialize()
                        loaded += 1

            except ImportError as e:
                logger.debug(f"Could not load builtin skill {module_name}: {e}")
            except Exception as e:
                logger.error(f"Error loading builtin skill {module_name}: {e}")

        logger.info(f"Loaded {loaded} built-in skills")
        return loaded

    async def load_from_directory(self, directory: str | Path) -> int:
        """
        Load skills from a directory.

        Looks for Python files with skill classes.

        Args:
            directory: Path to skills directory

        Returns:
            Number of skills loaded
        """
        directory = Path(directory).expanduser()

        if not directory.exists():
            logger.debug(f"Skills directory does not exist: {directory}")
            return 0

        loaded = 0

        for py_file in directory.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            try:
                # Load module from file
                spec = importlib.util.spec_from_file_location(
                    py_file.stem,
                    py_file,
                )
                if not spec or not spec.loader:
                    continue

                module = importlib.util.module_from_spec(spec)
                sys.modules[py_file.stem] = module
                spec.loader.exec_module(module)

                # Look for skill classes
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, Skill)
                        and attr is not Skill
                        and not attr_name.startswith("_")
                    ):
                        skill = attr()
                        self.register(skill)
                        await skill.initialize()
                        loaded += 1
                        logger.info(f"Loaded user skill from {py_file.name}: {attr_name}")

            except Exception as e:
                logger.error(f"Error loading skill from {py_file}: {e}")

        return loaded

    def check_all_auth(self) -> dict[str, bool]:
        """
        Check authentication status for all skills.

        Returns dict of skill_name -> auth_status.
        """
        return {
            name: skill.check_auth()
            for name, skill in self._skills.items()
        }


async def create_skill_registry(
    event_bus: EventBus | None = None,
    config: dict[str, Any] | None = None,
    load_builtin: bool = True,
    user_skills_dir: str | Path | None = None,
) -> SkillRegistry:
    """
    Create and initialize a skill registry.

    Args:
        event_bus: Optional event bus
        config: Skill configurations
        load_builtin: Load built-in skills
        user_skills_dir: Directory for user-defined skills

    Returns:
        Initialized SkillRegistry
    """
    registry = SkillRegistry(event_bus, config)

    if load_builtin:
        await registry.load_builtin_skills()

    if user_skills_dir:
        await registry.load_from_directory(user_skills_dir)

    return registry
