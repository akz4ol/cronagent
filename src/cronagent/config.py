"""
Configuration management for CronAgent.

Supports loading from:
- Environment variables (CRONAGENT_*)
- YAML config file (~/.cronagent/config.yaml)
- Programmatic override
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseModel):
    """Agent configuration."""

    model: str = Field(
        default="claude-sonnet-4-20250514",
        description="Claude model to use",
    )
    max_turns: int = Field(
        default=50,
        description="Maximum conversation turns",
    )
    max_tokens: int = Field(
        default=8192,
        description="Maximum tokens per response",
    )
    permission_mode: Literal["default", "acceptEdits", "bypassPermissions"] = Field(
        default="acceptEdits",
        description="Tool permission mode",
    )
    system_prompt: str = Field(
        default="",
        description="Additional system prompt to prepend",
    )
    working_directory: str = Field(
        default=".",
        description="Default working directory for tasks",
    )


class SchedulerConfig(BaseModel):
    """Scheduler configuration."""

    job_store_url: str = Field(
        default="sqlite:///~/.cronagent/jobs.db",
        description="Database URL for job persistence",
    )
    timezone: str = Field(
        default="UTC",
        description="Default timezone for cron expressions",
    )
    misfire_grace_time: int = Field(
        default=3600,
        description="Grace time in seconds for missed jobs",
    )
    max_workers: int = Field(
        default=5,
        description="Maximum concurrent task workers",
    )
    max_concurrent_jobs: int = Field(
        default=3,
        description="Maximum concurrent job executions",
    )


class MemoryConfig(BaseModel):
    """Memory and storage configuration."""

    storage_type: Literal["sqlite", "postgresql"] = Field(
        default="sqlite",
        description="Database backend for sessions",
    )
    sqlite_path: str = Field(
        default="~/.cronagent/sessions.db",
        description="SQLite database path",
    )
    postgres_url: str | None = Field(
        default=None,
        description="PostgreSQL connection URL",
    )
    max_session_age_days: int = Field(
        default=30,
        description="Maximum session age before cleanup",
    )
    enable_knowledge_base: bool = Field(
        default=True,
        description="Enable vector knowledge base",
    )
    knowledge_store: Literal["chromadb", "pgvector"] = Field(
        default="chromadb",
        description="Vector store backend",
    )
    chromadb_path: str = Field(
        default="~/.cronagent/knowledge",
        description="ChromaDB storage path",
    )


class TelegramChannelConfig(BaseModel):
    """Telegram channel configuration."""

    enabled: bool = False
    token: str = Field(default="", description="Bot token from @BotFather")
    allowed_users: list[str] = Field(
        default_factory=list,
        description="Allowed user IDs (empty = allow all)",
    )
    allowed_groups: list[str] = Field(
        default_factory=list,
        description="Allowed group IDs",
    )


class SlackChannelConfig(BaseModel):
    """Slack channel configuration."""

    enabled: bool = False
    bot_token: str = Field(default="", description="Slack bot token")
    signing_secret: str = Field(default="", description="Slack signing secret")
    app_token: str = Field(default="", description="Slack app token for socket mode")
    socket_mode: bool = Field(default=True, description="Use socket mode")
    allowed_users: list[str] = Field(default_factory=list)
    allowed_channels: list[str] = Field(default_factory=list)


class DiscordChannelConfig(BaseModel):
    """Discord channel configuration."""

    enabled: bool = False
    bot_token: str = Field(default="", description="Discord bot token")
    application_id: str = Field(default="", description="Discord application ID")
    allowed_guilds: list[str] = Field(default_factory=list)
    allowed_roles: list[str] = Field(default_factory=list)


class WebhookChannelConfig(BaseModel):
    """Webhook channel configuration."""

    enabled: bool = False
    port: int = Field(default=8080, description="HTTP server port")
    path: str = Field(default="/webhook", description="Webhook endpoint path")
    secret: str = Field(default="", description="HMAC secret for verification")
    require_signature: bool = Field(default=True)


class CLIChannelConfig(BaseModel):
    """CLI channel configuration."""

    enabled: bool = True
    prompt: str = Field(default="cronagent> ", description="CLI prompt string")


class ChannelsConfig(BaseModel):
    """All channel configurations."""

    telegram: TelegramChannelConfig = Field(default_factory=TelegramChannelConfig)
    slack: SlackChannelConfig = Field(default_factory=SlackChannelConfig)
    discord: DiscordChannelConfig = Field(default_factory=DiscordChannelConfig)
    webhook: WebhookChannelConfig = Field(default_factory=WebhookChannelConfig)
    cli: CLIChannelConfig = Field(default_factory=CLIChannelConfig)


class NotificationConfig(BaseModel):
    """Notification configuration."""

    default_channels: list[str] = Field(
        default_factory=lambda: ["console"],
        description="Default channels for notifications",
    )
    on_job_start: bool = Field(
        default=False,
        description="Send notification when job starts",
    )
    on_job_complete: bool = Field(
        default=True,
        description="Send notification when job completes",
    )
    on_job_failure: bool = Field(
        default=True,
        description="Send notification when job fails",
    )
    slack_webhook_url: str = Field(
        default="",
        description="Slack webhook URL for notifications",
    )
    discord_webhook_url: str = Field(
        default="",
        description="Discord webhook URL for notifications",
    )
    dedupe_window_minutes: int = Field(
        default=5,
        description="Window in minutes for deduplicating notifications",
    )
    rate_limit_per_minute: int = Field(
        default=10,
        description="Maximum notifications per minute per channel",
    )


# Alias for backward compatibility
NotificationsConfig = NotificationConfig


class CronAgentConfig(BaseSettings):
    """
    Main configuration for CronAgent.

    Configuration is loaded in this order (later overrides earlier):
    1. Default values
    2. YAML config file
    3. Environment variables (CRONAGENT_*)
    """

    model_config = SettingsConfigDict(
        env_prefix="CRONAGENT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Sub-configurations
    agent: AgentConfig = Field(default_factory=AgentConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)

    # Global settings
    skills_dir: str = Field(
        default="~/.cronagent/skills",
        description="Directory for user-defined skills",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )

    @classmethod
    def load(cls, config_path: Path | str | None = None) -> CronAgentConfig:
        """
        Load configuration with precedence:
        1. Environment variables (highest)
        2. Config file
        3. Defaults (lowest)
        """
        config_dict: dict[str, Any] = {}

        # Determine config file path
        if config_path is None:
            config_path = Path.home() / ".cronagent" / "config.yaml"
        else:
            config_path = Path(config_path)

        # Load from file if exists
        if config_path.exists():
            with open(config_path) as f:
                file_config = yaml.safe_load(f) or {}
                config_dict = cls._expand_env_vars(file_config)

        # Create config (env vars are loaded automatically by pydantic-settings)
        return cls(**config_dict)

    @classmethod
    def _expand_env_vars(cls, config: dict[str, Any]) -> dict[str, Any]:
        """Recursively expand ${VAR} environment variable references."""
        if isinstance(config, dict):
            return {k: cls._expand_env_vars(v) for k, v in config.items()}
        elif isinstance(config, list):
            return [cls._expand_env_vars(item) for item in config]
        elif isinstance(config, str):
            # Expand ${VAR} or ${VAR:-default} patterns
            if config.startswith("${") and config.endswith("}"):
                var_expr = config[2:-1]
                if ":-" in var_expr:
                    var_name, default = var_expr.split(":-", 1)
                    return os.environ.get(var_name, default)
                else:
                    return os.environ.get(var_expr, "")
            return config
        return config

    @classmethod
    def for_local_development(cls) -> CronAgentConfig:
        """Preset for local development."""
        return cls(
            memory=MemoryConfig(
                storage_type="sqlite",
                knowledge_store="chromadb",
            ),
            channels=ChannelsConfig(
                cli=CLIChannelConfig(enabled=True),
            ),
        )

    @classmethod
    def for_testing(cls) -> CronAgentConfig:
        """Preset for testing (in-memory, no persistence)."""
        return cls(
            memory=MemoryConfig(
                storage_type="sqlite",
                sqlite_path=":memory:",
                enable_knowledge_base=False,
            ),
            scheduler=SchedulerConfig(
                job_store_url="sqlite:///:memory:",
            ),
        )

    def get_expanded_path(self, path: str) -> Path:
        """Expand ~ and environment variables in a path."""
        return Path(os.path.expandvars(os.path.expanduser(path)))

    def ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        dirs_to_create = [
            self.get_expanded_path("~/.cronagent"),
            self.get_expanded_path(self.skills_dir),
        ]

        if self.memory.storage_type == "sqlite":
            db_path = self.get_expanded_path(self.memory.sqlite_path)
            dirs_to_create.append(db_path.parent)

        if self.memory.enable_knowledge_base and self.memory.knowledge_store == "chromadb":
            dirs_to_create.append(self.get_expanded_path(self.memory.chromadb_path))

        for dir_path in dirs_to_create:
            dir_path.mkdir(parents=True, exist_ok=True)
