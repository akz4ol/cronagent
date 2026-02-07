"""
Webhook channel for HTTP-based communication.

Provides:
- HTTP server for incoming webhooks
- Outgoing webhook delivery
- Request validation
- Async request handling
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any, AsyncIterator
from uuid import uuid4

import aiohttp
from aiohttp import web

from cronagent.channels.base import (
    AuthorizationManager,
    BaseChannel,
    ChannelType,
    MessageContent,
    MessageMetadata,
    MessageType,
    OutgoingMessage,
    UnifiedMessage,
)

logger = logging.getLogger(__name__)


class WebhookChannel(BaseChannel):
    """
    HTTP webhook channel.

    Provides both:
    - Incoming webhook server (receive HTTP requests)
    - Outgoing webhook delivery (send HTTP requests)

    Config options:
        host: Server host (default: "0.0.0.0")
        port: Server port (default: 8080)
        path: Webhook path (default: "/webhook")
        secret: Shared secret for HMAC validation
        outgoing_url: URL for outgoing webhooks
        outgoing_headers: Headers for outgoing requests

    Usage:
        channel = WebhookChannel({
            "port": 8080,
            "secret": "my-secret",
            "outgoing_url": "https://example.com/callback",
        })
        await channel.connect()
    """

    def __init__(
        self,
        config: dict[str, Any],
        auth_manager: AuthorizationManager | None = None,
    ) -> None:
        super().__init__(ChannelType.WEBHOOK, config, auth_manager)

        self._host = config.get("host", "0.0.0.0")
        self._port = config.get("port", 8080)
        self._path = config.get("path", "/webhook")
        self._secret = config.get("secret", "")
        self._outgoing_url = config.get("outgoing_url", "")
        self._outgoing_headers = config.get("outgoing_headers", {})

        # Server components
        self._app: web.Application | None = None
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

        # Message queue
        self._message_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()

    async def connect(self) -> None:
        """Start the webhook server."""
        if self._connected:
            return

        # Create aiohttp app
        self._app = web.Application()
        self._app.router.add_post(self._path, self._handle_webhook)
        self._app.router.add_get("/health", self._handle_health)

        # Start server
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()

        self._connected = True
        logger.info(f"Webhook server started on {self._host}:{self._port}{self._path}")

    async def disconnect(self) -> None:
        """Stop the webhook server."""
        if not self._connected:
            return

        if self._site:
            await self._site.stop()

        if self._runner:
            await self._runner.cleanup()

        self._connected = False
        logger.info("Webhook server stopped")

    async def send(self, message: OutgoingMessage) -> str | None:
        """Send an outgoing webhook."""
        if not self._outgoing_url:
            logger.warning("No outgoing URL configured for webhook")
            return None

        try:
            # Build payload
            payload = {
                "id": str(uuid4()),
                "channel_id": message.channel_id,
                "text": message.content.text,
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": {
                    "reply_to": message.metadata.reply_to_id,
                    "thread_id": message.metadata.thread_id,
                },
            }

            # Add HMAC signature if secret configured
            headers = dict(self._outgoing_headers)
            headers["Content-Type"] = "application/json"
            headers["X-CronAgent-Event"] = "message"

            if self._secret:
                signature = self._sign_payload(json.dumps(payload))
                headers["X-CronAgent-Signature"] = signature

            # Send request
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._outgoing_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status >= 200 and response.status < 300:
                        return payload["id"]
                    else:
                        logger.error(
                            f"Webhook delivery failed: {response.status}"
                        )
                        return None

        except Exception as e:
            logger.error(f"Webhook send error: {e}")
            return None

    async def receive(self) -> AsyncIterator[UnifiedMessage]:
        """Receive messages from incoming webhooks."""
        while self._connected:
            try:
                message = await asyncio.wait_for(
                    self._message_queue.get(),
                    timeout=1.0,
                )
                yield message
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _handle_webhook(self, request: web.Request) -> web.Response:
        """Handle incoming webhook requests."""
        try:
            # Read body
            body = await request.read()

            # Validate signature if secret configured
            if self._secret:
                signature = request.headers.get("X-CronAgent-Signature", "")
                if not self._verify_signature(body, signature):
                    logger.warning("Invalid webhook signature")
                    return web.Response(status=401, text="Invalid signature")

            # Parse JSON
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return web.Response(status=400, text="Invalid JSON")

            # Extract message fields
            text = data.get("text", data.get("message", ""))
            user_id = data.get("user_id", data.get("sender", "webhook"))
            channel_id = data.get("channel_id", "webhook")
            message_id = data.get("id", str(uuid4())[:8])

            # Determine message type
            msg_type = MessageType.TEXT
            if text.startswith("/"):
                msg_type = MessageType.COMMAND

            # Create unified message
            message = UnifiedMessage(
                id=message_id,
                channel_type=ChannelType.WEBHOOK,
                channel_id=channel_id,
                user_id=user_id,
                username=data.get("username"),
                content=MessageContent(
                    text=text,
                    type=msg_type,
                ),
                metadata=MessageMetadata(
                    thread_id=data.get("thread_id"),
                    platform_data={
                        "headers": dict(request.headers),
                        "source_ip": request.remote,
                        "raw_data": data,
                    },
                ),
            )

            # Queue for processing
            await self._message_queue.put(message)

            return web.json_response({
                "status": "accepted",
                "message_id": message_id,
            })

        except Exception as e:
            logger.error(f"Webhook handler error: {e}")
            return web.Response(status=500, text="Internal error")

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response({
            "status": "healthy",
            "channel": "webhook",
            "timestamp": datetime.utcnow().isoformat(),
        })

    def _sign_payload(self, payload: str) -> str:
        """Create HMAC signature for payload."""
        signature = hmac.new(
            self._secret.encode(),
            payload.encode(),
            hashlib.sha256,
        )
        return f"sha256={signature.hexdigest()}"

    def _verify_signature(self, body: bytes, signature: str) -> bool:
        """Verify HMAC signature."""
        if not signature.startswith("sha256="):
            return False

        expected = hmac.new(
            self._secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()

        provided = signature[7:]  # Remove "sha256=" prefix

        return hmac.compare_digest(expected, provided)

    def format_for_platform(self, content: MessageContent) -> str:
        """Format content for webhook payload."""
        text = content.text

        # Add code blocks
        for block in content.code_blocks:
            lang = block.get("language", "")
            code = block.get("code", "")
            text += f"\n```{lang}\n{code}\n```"

        return text


async def send_webhook(
    url: str,
    text: str,
    secret: str | None = None,
    headers: dict[str, str] | None = None,
    **extra_data: Any,
) -> bool:
    """
    Convenience function to send a webhook.

    Args:
        url: Webhook URL
        text: Message text
        secret: Optional HMAC secret
        headers: Optional additional headers
        **extra_data: Additional payload fields

    Returns:
        True if successful
    """
    try:
        payload = {
            "id": str(uuid4()),
            "text": text,
            "timestamp": datetime.utcnow().isoformat(),
            **extra_data,
        }

        req_headers = headers or {}
        req_headers["Content-Type"] = "application/json"
        req_headers["X-CronAgent-Event"] = "notification"

        if secret:
            signature = hmac.new(
                secret.encode(),
                json.dumps(payload).encode(),
                hashlib.sha256,
            )
            req_headers["X-CronAgent-Signature"] = f"sha256={signature.hexdigest()}"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=req_headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                return response.status >= 200 and response.status < 300

    except Exception as e:
        logger.error(f"Webhook send error: {e}")
        return False
