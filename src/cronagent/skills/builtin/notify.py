"""
Notification skill for sending alerts and messages.

Provides tools for:
- Webhook notifications
- Email sending
- Slack/Discord direct messaging
- SMS notifications (via Twilio)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import aiohttp

from cronagent.skills.base import (
    DecoratorSkill,
    SkillCategory,
    SkillMetadata,
    skill_tool,
)

logger = logging.getLogger(__name__)


class NotifySkill(DecoratorSkill):
    """
    Notification skill for sending alerts.

    Provides various notification methods including webhooks,
    email, and third-party services.

    Config options:
        slack_webhook_url: Slack incoming webhook URL
        discord_webhook_url: Discord webhook URL
        email_smtp_host: SMTP server host
        email_smtp_port: SMTP server port
        email_from: Default from address
        twilio_account_sid: Twilio account SID
        twilio_auth_token: Twilio auth token
        twilio_from_number: Twilio phone number
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)

        # Load from config or environment
        self._slack_webhook = self.config.get(
            "slack_webhook_url",
            os.environ.get("SLACK_WEBHOOK_URL", ""),
        )
        self._discord_webhook = self.config.get(
            "discord_webhook_url",
            os.environ.get("DISCORD_WEBHOOK_URL", ""),
        )
        self._email_config = {
            "smtp_host": self.config.get("email_smtp_host", os.environ.get("SMTP_HOST", "")),
            "smtp_port": self.config.get("email_smtp_port", int(os.environ.get("SMTP_PORT", "587"))),
            "smtp_user": self.config.get("email_smtp_user", os.environ.get("SMTP_USER", "")),
            "smtp_password": self.config.get("email_smtp_password", os.environ.get("SMTP_PASSWORD", "")),
            "from_address": self.config.get("email_from", os.environ.get("EMAIL_FROM", "")),
        }

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="notify",
            description="Send notifications and alerts",
            version="1.0.0",
            category=SkillCategory.COMMUNICATION,
            tags=["notification", "alert", "webhook", "email", "slack"],
            requires_auth=False,
            auth_env_vars=[],
        )

    @skill_tool(
        name="notify_webhook",
        description="Send a webhook notification",
    )
    async def send_webhook(
        self,
        url: str,
        message: str,
        title: str = "",
        level: str = "info",
        extra_data: dict[str, Any] = {},
    ) -> dict[str, Any]:
        """Send a generic webhook notification."""
        payload = {
            "message": message,
            "title": title,
            "level": level,
            **extra_data,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    return {
                        "success": response.status < 400,
                        "status_code": response.status,
                        "url": url,
                    }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "url": url,
            }

    @skill_tool(
        name="notify_slack",
        description="Send a Slack notification",
    )
    async def send_slack(
        self,
        message: str,
        channel: str = "",
        webhook_url: str = "",
        username: str = "CronAgent",
        icon_emoji: str = ":robot_face:",
        blocks: list[dict] = [],
    ) -> dict[str, Any]:
        """Send a Slack notification via webhook."""
        url = webhook_url or self._slack_webhook

        if not url:
            return {
                "success": False,
                "error": "Slack webhook URL not configured",
            }

        payload: dict[str, Any] = {
            "text": message,
            "username": username,
            "icon_emoji": icon_emoji,
        }

        if channel:
            payload["channel"] = channel

        if blocks:
            payload["blocks"] = blocks

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    return {
                        "success": response.status == 200,
                        "status_code": response.status,
                    }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    @skill_tool(
        name="notify_discord",
        description="Send a Discord notification",
    )
    async def send_discord(
        self,
        message: str,
        webhook_url: str = "",
        username: str = "CronAgent",
        embed: dict[str, Any] = {},
    ) -> dict[str, Any]:
        """Send a Discord notification via webhook."""
        url = webhook_url or self._discord_webhook

        if not url:
            return {
                "success": False,
                "error": "Discord webhook URL not configured",
            }

        payload: dict[str, Any] = {
            "content": message,
            "username": username,
        }

        if embed:
            payload["embeds"] = [embed]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    return {
                        "success": response.status in (200, 204),
                        "status_code": response.status,
                    }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    @skill_tool(
        name="notify_email",
        description="Send an email notification",
    )
    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
        cc: str = "",
        bcc: str = "",
    ) -> dict[str, Any]:
        """Send an email notification."""
        import asyncio

        config = self._email_config

        if not config["smtp_host"]:
            return {
                "success": False,
                "error": "SMTP not configured",
            }

        try:
            import smtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            # Build message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = config["from_address"]
            msg["To"] = to

            if cc:
                msg["Cc"] = cc
            if bcc:
                msg["Bcc"] = bcc

            # Add body
            content_type = "html" if html else "plain"
            msg.attach(MIMEText(body, content_type))

            # Send in thread pool (smtplib is blocking)
            def send_sync():
                with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as server:
                    server.starttls()
                    if config["smtp_user"] and config["smtp_password"]:
                        server.login(config["smtp_user"], config["smtp_password"])

                    recipients = [to]
                    if cc:
                        recipients.extend(cc.split(","))
                    if bcc:
                        recipients.extend(bcc.split(","))

                    server.sendmail(config["from_address"], recipients, msg.as_string())

            await asyncio.get_event_loop().run_in_executor(None, send_sync)

            return {
                "success": True,
                "to": to,
                "subject": subject,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    @skill_tool(
        name="notify_formatted",
        description="Send a formatted notification to multiple channels",
    )
    async def send_formatted(
        self,
        title: str,
        message: str,
        level: str = "info",
        channels: list[str] = [],
        details: dict[str, Any] = {},
    ) -> dict[str, Any]:
        """
        Send a formatted notification to multiple channels.

        Channels can be:
        - "slack" - Send to configured Slack webhook
        - "discord" - Send to configured Discord webhook
        - "slack:webhook_url" - Send to specific Slack webhook
        - "discord:webhook_url" - Send to specific Discord webhook
        - "webhook:url" - Send to generic webhook
        """
        results = {}
        level_emoji = {
            "info": "ℹ️",
            "success": "✅",
            "warning": "⚠️",
            "error": "❌",
            "critical": "🚨",
        }

        emoji = level_emoji.get(level, "ℹ️")
        formatted_title = f"{emoji} {title}"

        for channel in channels:
            if channel.startswith("slack:"):
                url = channel[6:]
                result = await self.send_slack(
                    message=f"*{formatted_title}*\n{message}",
                    webhook_url=url,
                )
                results[channel] = result

            elif channel == "slack":
                result = await self.send_slack(
                    message=f"*{formatted_title}*\n{message}",
                )
                results[channel] = result

            elif channel.startswith("discord:"):
                url = channel[8:]
                result = await self.send_discord(
                    message="",
                    webhook_url=url,
                    embed={
                        "title": formatted_title,
                        "description": message,
                        "color": self._get_discord_color(level),
                        "fields": [
                            {"name": k, "value": str(v), "inline": True}
                            for k, v in details.items()
                        ],
                    },
                )
                results[channel] = result

            elif channel == "discord":
                result = await self.send_discord(
                    message="",
                    embed={
                        "title": formatted_title,
                        "description": message,
                        "color": self._get_discord_color(level),
                    },
                )
                results[channel] = result

            elif channel.startswith("webhook:"):
                url = channel[8:]
                result = await self.send_webhook(
                    url=url,
                    message=message,
                    title=title,
                    level=level,
                    extra_data=details,
                )
                results[channel] = result

        return {
            "channels_notified": len(results),
            "results": results,
        }

    def _get_discord_color(self, level: str) -> int:
        """Get Discord embed color for notification level."""
        colors = {
            "info": 0x3498db,  # Blue
            "success": 0x2ecc71,  # Green
            "warning": 0xf39c12,  # Orange
            "error": 0xe74c3c,  # Red
            "critical": 0x9b59b6,  # Purple
        }
        return colors.get(level, 0x95a5a6)  # Default gray
