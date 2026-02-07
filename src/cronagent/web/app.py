"""
FastAPI web application for CronAgent dashboard.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Store for active WebSocket connections
active_connections: list[WebSocket] = []

# Simple token-based auth (stored in memory, persisted to file)
AUTH_TOKEN: str | None = None
PERMISSIONS_GRANTED = False


class ChatMessage(BaseModel):
    message: str


class JobCreate(BaseModel):
    name: str
    cron: str | None = None
    interval_minutes: int | None = None
    prompt: str
    notify: list[str] = []


class PermissionGrant(BaseModel):
    permissions: list[str]


def load_api_config() -> None:
    """Load API configuration from ~/.cronagent/api.txt if it exists."""
    config_dir = Path.home() / ".cronagent"
    api_file = config_dir / "api.txt"

    if api_file.exists():
        logger.info(f"Loading API config from {api_file}")
        with open(api_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if key and value and key not in os.environ:
                        os.environ[key] = value
                        logger.debug(f"Loaded {key} from api.txt")


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    # Load API config from file
    load_api_config()

    app = FastAPI(
        title="CronAgent Dashboard",
        description="Web interface for CronAgent",
        version="0.1.0",
    )

    # Get the directory of this file for static/template paths
    web_dir = Path(__file__).parent
    static_dir = web_dir / "static"

    # Mount static files if directory exists
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ============================================================
    # Auth & Setup
    # ============================================================

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        """Serve the main dashboard."""
        return get_dashboard_html()

    @app.get("/api/status")
    async def get_status():
        """Get current system status."""
        import shutil
        global PERMISSIONS_GRANTED

        # Check if API key is set
        api_key_set = bool(os.environ.get("ANTHROPIC_API_KEY"))

        # Check if Claude CLI is available (for OAuth mode)
        cli_available = shutil.which("claude") is not None

        # Check permissions file
        config_dir = Path.home() / ".cronagent"
        perm_file = config_dir / "permissions.json"
        if perm_file.exists():
            PERMISSIONS_GRANTED = True

        # Ready if: CLI available (OAuth) OR API key set
        ready = cli_available or api_key_set

        return {
            "status": "running",
            "api_key_configured": api_key_set,
            "cli_available": cli_available,
            "mode": "cli" if (cli_available and not api_key_set) else "sdk",
            "ready": ready,
            "permissions_granted": PERMISSIONS_GRANTED,
            "timestamp": datetime.now().isoformat(),
        }

    @app.post("/api/setup")
    async def setup_api_key(request: Request):
        """Save API key to config."""
        data = await request.json()
        api_key = data.get("api_key", "").strip()

        if not api_key:
            raise HTTPException(400, "API key required")

        # Save to api.txt
        config_dir = Path.home() / ".cronagent"
        config_dir.mkdir(exist_ok=True)

        api_file = config_dir / "api.txt"

        # Read existing content
        existing = {}
        if api_file.exists():
            with open(api_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        existing[k.strip()] = v.strip()

        # Update API key
        existing["ANTHROPIC_API_KEY"] = api_key

        # Write back
        with open(api_file, "w") as f:
            f.write("# CronAgent API Configuration\n\n")
            for k, v in existing.items():
                f.write(f"{k}={v}\n")

        # Set in environment
        os.environ["ANTHROPIC_API_KEY"] = api_key

        return {"success": True, "message": "API key saved"}

    @app.post("/api/permissions")
    async def grant_permissions(grant: PermissionGrant):
        """Grant permissions (one-time setup)."""
        global PERMISSIONS_GRANTED

        config_dir = Path.home() / ".cronagent"
        config_dir.mkdir(exist_ok=True)

        perm_file = config_dir / "permissions.json"

        permissions = {
            "granted": True,
            "permissions": grant.permissions,
            "granted_at": datetime.now().isoformat(),
            "auto_mode": True,
        }

        with open(perm_file, "w") as f:
            json.dump(permissions, f, indent=2)

        PERMISSIONS_GRANTED = True

        return {"success": True, "message": "Permissions granted"}

    # ============================================================
    # Chat / Agent Interaction
    # ============================================================

    def detect_schedule_intent(message: str) -> dict[str, Any] | None:
        """Detect if message is asking to schedule a task. Returns schedule info if detected."""
        import re
        message_lower = message.lower()

        # Common scheduling keywords
        schedule_patterns = [
            r"schedule\s+(?:a\s+)?(.+?)(?:\s+(?:every|at|daily|weekly|hourly|monthly))",
            r"(?:run|execute)\s+(?:a\s+)?(.+?)(?:\s+every\s+)",
            r"(?:every|at)\s+(day|hour|week|morning|night|monday|tuesday|wednesday|thursday|friday|saturday|sunday)",
            r"(?:daily|weekly|hourly|monthly)\s+(.+)",
            r"create\s+(?:a\s+)?(?:scheduled\s+)?(?:job|task)\s+(?:to\s+)?(.+)",
        ]

        for pattern in schedule_patterns:
            if re.search(pattern, message_lower):
                return {"detected": True, "message": message}
        return None

    @app.post("/api/chat")
    async def chat(msg: ChatMessage):
        """Send a message to the agent. Automatically detects and creates scheduled jobs."""
        logger.info(f"Chat request received: {msg.message[:50]}...")

        if not os.environ.get("ANTHROPIC_API_KEY"):
            logger.error("API key not configured")
            raise HTTPException(400, "API key not configured")

        # Check if this is a scheduling request
        schedule_intent = detect_schedule_intent(msg.message)
        job_created = None

        if schedule_intent:
            # Try to create a job from the request
            job_created = await try_create_job_from_chat(msg.message)

        try:
            from cronagent.agent import AgentLoop, AgentLoopConfig
            from cronagent.bus.events import EventBus

            # Enhance prompt with job context if job was created
            prompt = msg.message
            if job_created:
                prompt = f"{msg.message}\n\n[System: A scheduled job '{job_created['name']}' was just created with ID '{job_created['id']}'. Acknowledge this to the user and explain what will happen.]"

            event_bus = EventBus()
            config = AgentLoopConfig()
            agent = AgentLoop(config, event_bus=event_bus)

            response_parts = []
            tool_uses = []
            event_count = 0

            logger.info("Starting agent execution...")
            async for event in agent.execute(prompt):
                event_count += 1
                logger.debug(f"Event #{event_count}: type={event.type}")

                if event.type == "text":
                    response_parts.append(event.content)
                elif event.type == "tool_use":
                    tool_uses.append({
                        "tool": event.metadata.get("tool"),
                        "input": event.metadata.get("input"),
                    })

                # Broadcast to WebSocket clients
                await broadcast({
                    "type": "agent_event",
                    "event": event.type,
                    "content": event.content if hasattr(event, 'content') else None,
                })

            logger.info(f"Agent execution complete. Events: {event_count}, Response parts: {len(response_parts)}")

            response = {
                "response": "".join(response_parts),
                "tool_uses": tool_uses,
                "timestamp": datetime.now().isoformat(),
            }

            if job_created:
                response["job_created"] = job_created

            return response

        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            raise HTTPException(500, str(e))

    async def try_create_job_from_chat(message: str) -> dict[str, Any] | None:
        """Try to extract and create a job from a chat message."""
        import re

        message_lower = message.lower()

        # Extract schedule pattern
        cron = None
        interval_minutes = None
        hour = 9  # Default to 9 AM
        minute = 0

        # First, check for specific time
        time_match = re.search(r"(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)", message_lower)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2)) if time_match.group(2) else 0
            if time_match.group(3) == "pm" and hour < 12:
                hour += 12
            elif time_match.group(3) == "am" and hour == 12:
                hour = 0

        # Now check frequency patterns
        if re.search(r"\b(daily|every\s*day)\b", message_lower):
            cron = f"{minute} {hour} * * *"
        elif re.search(r"\b(hourly|every\s*hour)\b", message_lower):
            interval_minutes = 60
        elif re.search(r"\b(weekly|every\s*week)\b", message_lower):
            cron = f"{minute} {hour} * * MON"
        elif match := re.search(r"every\s*(\d+)\s*minutes?", message_lower):
            interval_minutes = int(match.group(1))
        elif match := re.search(r"every\s*(\d+)\s*hours?", message_lower):
            interval_minutes = int(match.group(1)) * 60
        elif time_match:
            # Just a time specified, assume daily
            cron = f"{minute} {hour} * * *"

        if not cron and not interval_minutes:
            return None

        # Extract task description (remove scheduling keywords)
        task = re.sub(
            r"\b(schedule|run|execute|create|daily|weekly|hourly|monthly|every\s*\w+|at\s*\d+[:\d]*\s*(?:am|pm)?)\b",
            "",
            message,
            flags=re.IGNORECASE,
        ).strip()
        task = re.sub(r"\s+", " ", task).strip(" .,;:")

        if len(task) < 5:
            task = message  # Use original if extraction failed

        # Create job name
        words = task.split()[:5]
        name = " ".join(words).title()
        if len(name) > 50:
            name = name[:47] + "..."

        try:
            from cronagent.config import CronAgentConfig
            from cronagent.cron.job import (
                ClaudePromptExecution,
                CronSchedule,
                ExecutionType,
                IntervalSchedule,
                JobDefinition,
                ScheduleType,
            )
            from cronagent.cron.store import JobStore
            from cronagent.storage.database import Database

            config = CronAgentConfig.load()
            db = Database.from_config(config.memory)
            await db.initialize()
            store = JobStore(db)

            # Create job definition
            if cron:
                schedule_type = ScheduleType.CRON
                schedule = CronSchedule(expression=cron)
            else:
                schedule_type = ScheduleType.INTERVAL
                schedule = IntervalSchedule(minutes=interval_minutes)

            job_def = JobDefinition(
                name=name,
                description=f"Created from chat: {message[:200]}",
                schedule_type=schedule_type,
                schedule=schedule,
                execution_type=ExecutionType.CLAUDE_PROMPT,
                execution=ClaudePromptExecution(prompt=task),
            )

            await store.add_job(job_def)
            await db.close()

            # Broadcast job creation
            await broadcast({"type": "job_created", "job_id": job_def.id, "name": name})

            return {"id": job_def.id, "name": name, "schedule": cron or f"every {interval_minutes} minutes"}

        except Exception as e:
            logger.error(f"Failed to create job from chat: {e}", exc_info=True)
            return None

    # ============================================================
    # Jobs Management
    # ============================================================

    @app.get("/api/jobs")
    async def list_jobs():
        """List all scheduled jobs."""
        try:
            from cronagent.config import CronAgentConfig
            from cronagent.cron.store import JobStore
            from cronagent.storage.database import Database

            config = CronAgentConfig.load()
            db = Database.from_config(config.memory)
            await db.initialize()
            store = JobStore(db)

            jobs = await store.list_jobs()

            # Get run stats for each job
            job_list = []
            for j in jobs:
                # Get run stats from store
                stats = await store.get_job_stats(j.id)
                job_list.append({
                    "id": j.id,
                    "name": j.name,
                    "description": j.description,
                    "schedule_type": j.schedule_type.value,
                    "enabled": j.enabled,
                    "paused": j.paused,
                    "created_at": j.created_at.isoformat() if j.created_at else None,
                    "last_run": stats.get("last_run_at"),
                    "last_status": stats.get("last_status"),
                    "run_count": stats.get("run_count", 0),
                    "success_count": stats.get("success_count", 0),
                    "failure_count": stats.get("failure_count", 0),
                })

            await db.close()
            return {"jobs": job_list}

        except Exception as e:
            logger.error(f"List jobs error: {e}", exc_info=True)
            return {"jobs": [], "error": str(e)}

    @app.post("/api/jobs")
    async def create_job(job: JobCreate):
        """Create a new job."""
        try:
            from cronagent.config import CronAgentConfig
            from cronagent.cron.job import (
                ClaudePromptExecution,
                CronSchedule,
                ExecutionType,
                IntervalSchedule,
                JobDefinition,
                ScheduleType,
            )
            from cronagent.cron.store import JobStore
            from cronagent.storage.database import Database

            config = CronAgentConfig.load()
            db = Database.from_config(config.memory)
            await db.initialize()
            store = JobStore(db)

            # Determine schedule type
            if job.cron:
                schedule_type = ScheduleType.CRON
                schedule = CronSchedule(job.cron)
            elif job.interval_minutes:
                schedule_type = ScheduleType.INTERVAL
                schedule = IntervalSchedule(minutes=job.interval_minutes)
            else:
                raise HTTPException(400, "Either cron or interval_minutes required")

            job_def = JobDefinition(
                name=job.name,
                schedule_type=schedule_type,
                schedule=schedule,
                execution_type=ExecutionType.CLAUDE_PROMPT,
                execution=ClaudePromptExecution(prompt=job.prompt),
            )

            await store.add_job(job_def)
            await db.close()

            # Broadcast update
            await broadcast({"type": "job_created", "job_id": job_def.id})

            return {"success": True, "job_id": job_def.id}

        except Exception as e:
            logger.error(f"Create job error: {e}", exc_info=True)
            raise HTTPException(500, str(e))

    @app.post("/api/jobs/{job_id}/trigger")
    async def trigger_job(job_id: str):
        """Manually trigger a job and execute it."""
        try:
            from cronagent.agent import AgentLoop, AgentLoopConfig
            from cronagent.bus.events import EventBus
            from cronagent.config import CronAgentConfig
            from cronagent.cron.job import ExecutionType, JobStatus
            from cronagent.cron.store import JobStore
            from cronagent.storage.database import Database

            config = CronAgentConfig.load()
            db = Database.from_config(config.memory)
            await db.initialize()
            store = JobStore(db)

            # Get job
            job = await store.get_job(job_id)
            if not job:
                await db.close()
                raise HTTPException(404, "Job not found")

            # Create run record
            run_id = await store.create_run(job_id, triggered_by="web")
            await store.start_run(run_id)

            # Broadcast start
            await broadcast({"type": "job_started", "job_id": job_id, "run_id": run_id})

            try:
                # Execute based on type
                if job.execution_type == ExecutionType.CLAUDE_PROMPT:
                    event_bus = EventBus()
                    agent_config = AgentLoopConfig(
                        working_directory=job.execution.project_path or ".",
                        model=getattr(job.execution, 'model', 'claude-sonnet-4-20250514'),
                    )
                    agent = AgentLoop(agent_config, event_bus=event_bus)

                    # Execute and collect output
                    output_parts = []
                    cost_usd = 0.0
                    async for event in agent.execute(job.execution.prompt):
                        if event.type == "text":
                            output_parts.append(event.content)
                            await broadcast({
                                "type": "job_output",
                                "job_id": job_id,
                                "run_id": run_id,
                                "content": event.content,
                            })
                        elif event.type == "result":
                            cost_usd = event.metadata.get("cost_usd", 0)

                    output = "".join(output_parts)
                    await store.complete_run(run_id, JobStatus.SUCCESS, output=output, cost_usd=cost_usd)

                    await broadcast({"type": "job_completed", "job_id": job_id, "run_id": run_id, "status": "success"})
                    await db.close()
                    return {"success": True, "run_id": run_id, "output": output, "status": "success"}

                else:
                    await store.complete_run(run_id, JobStatus.FAILURE, error="Execution type not supported in web trigger")
                    await db.close()
                    raise HTTPException(400, "Only Claude prompt jobs can be triggered from web")

            except Exception as exec_error:
                logger.error(f"Job execution error: {exec_error}", exc_info=True)
                await store.complete_run(run_id, JobStatus.FAILURE, error=str(exec_error))
                await broadcast({"type": "job_completed", "job_id": job_id, "run_id": run_id, "status": "failure"})
                await db.close()
                return {"success": False, "run_id": run_id, "error": str(exec_error), "status": "failure"}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Trigger job error: {e}", exc_info=True)
            raise HTTPException(500, str(e))

    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: str):
        """Delete a job."""
        try:
            from cronagent.config import CronAgentConfig
            from cronagent.cron.store import JobStore
            from cronagent.storage.database import Database

            config = CronAgentConfig.load()
            db = Database.from_config(config.memory)
            await db.initialize()
            store = JobStore(db)

            success = await store.delete_job(job_id)
            await db.close()

            if success:
                await broadcast({"type": "job_deleted", "job_id": job_id})
                return {"success": True}
            else:
                raise HTTPException(404, "Job not found")

        except Exception as e:
            raise HTTPException(500, str(e))

    # ============================================================
    # Audit Logs / History
    # ============================================================

    @app.get("/api/runs")
    async def list_runs(job_id: str | None = None, limit: int = 50):
        """List job runs (audit log)."""
        try:
            from cronagent.config import CronAgentConfig
            from cronagent.cron.store import JobStore
            from cronagent.storage.database import Database

            config = CronAgentConfig.load()
            db = Database.from_config(config.memory)
            await db.initialize()
            store = JobStore(db)

            runs = await store.get_runs(job_id=job_id, limit=limit)
            await db.close()

            return {
                "runs": [
                    {
                        "id": r.run_id,
                        "job_id": r.job_id,
                        "status": r.status.value,
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                        "duration_ms": r.duration_ms,
                        "attempt": r.attempt,
                        "triggered_by": r.triggered_by,
                        "output": r.output[:500] if r.output else None,
                        "error": r.error,
                    }
                    for r in runs
                ]
            }
        except Exception as e:
            logger.error(f"List runs error: {e}", exc_info=True)
            return {"runs": [], "error": str(e)}

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        """Get detailed run information."""
        try:
            from cronagent.config import CronAgentConfig
            from cronagent.cron.store import JobStore
            from cronagent.storage.database import Database

            config = CronAgentConfig.load()
            db = Database.from_config(config.memory)
            await db.initialize()
            store = JobStore(db)

            run = await store.get_run(run_id)
            await db.close()

            if not run:
                raise HTTPException(404, "Run not found")

            return {
                "id": run.run_id,
                "job_id": run.job_id,
                "status": run.status.value,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "duration_ms": run.duration_ms,
                "attempt": run.attempt,
                "max_attempts": run.max_attempts,
                "triggered_by": run.triggered_by,
                "triggered_by_user": run.triggered_by_user,
                "output": run.output,
                "error": run.error,
                "cost_usd": run.cost_usd,
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, str(e))

    # ============================================================
    # WebSocket for Real-time Updates
    # ============================================================

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket for real-time updates."""
        await websocket.accept()
        active_connections.append(websocket)

        try:
            while True:
                # Keep connection alive, receive any messages
                data = await websocket.receive_text()
                # Echo back for ping/pong
                if data == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            active_connections.remove(websocket)

    return app


async def broadcast(message: dict):
    """Broadcast message to all WebSocket clients."""
    for connection in active_connections:
        try:
            await connection.send_json(message)
        except Exception:
            pass


def get_dashboard_html() -> str:
    """Return the dashboard HTML."""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CronAgent Dashboard</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <style>
        [x-cloak] { display: none !important; }
        .chat-container { height: calc(100vh - 200px); }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .animate-pulse-slow { animation: pulse 2s ease-in-out infinite; }
    </style>
</head>
<body class="bg-gray-900 text-white min-h-screen" x-data="dashboard()">

    <!-- Setup Modal -->
    <div x-show="showSetup" x-cloak class="fixed inset-0 bg-black/80 flex items-center justify-center z-50">
        <div class="bg-gray-800 rounded-2xl p-8 max-w-md w-full mx-4 shadow-2xl">
            <div class="text-center mb-6">
                <div class="w-16 h-16 bg-indigo-500 rounded-2xl flex items-center justify-center mx-auto mb-4">
                    <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>
                    </svg>
                </div>
                <h2 class="text-2xl font-bold">Welcome to CronAgent</h2>
                <p class="text-gray-400 mt-2">Let's get you set up in 30 seconds</p>
            </div>

            <!-- Step 1: API Key or CLI Mode -->
            <div x-show="setupStep === 1">
                <!-- CLI Mode Available -->
                <div x-show="status.cli_available" class="mb-6 p-4 bg-green-900/30 border border-green-700 rounded-lg">
                    <div class="flex items-center gap-2 text-green-400 font-medium mb-2">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                        </svg>
                        Claude Code CLI detected!
                    </div>
                    <p class="text-sm text-gray-300 mb-3">Use your existing Claude subscription - no API costs.</p>
                    <button @click="skipApiKey()"
                        class="w-full bg-green-600 hover:bg-green-700 rounded-lg py-3 font-medium transition">
                        Use CLI Mode (Recommended)
                    </button>
                </div>

                <div x-show="status.cli_available" class="text-center text-gray-500 text-sm mb-4">— or enter API key for SDK mode —</div>

                <label class="block text-sm font-medium mb-2">Anthropic API Key <span x-show="status.cli_available" class="text-gray-500">(optional)</span></label>
                <input type="password" x-model="apiKey"
                    class="w-full bg-gray-700 rounded-lg px-4 py-3 focus:ring-2 focus:ring-indigo-500 outline-none"
                    placeholder="sk-ant-...">
                <p class="text-xs text-gray-500 mt-2">
                    Get your key from <a href="https://console.anthropic.com" target="_blank" class="text-indigo-400 hover:underline">console.anthropic.com</a>
                    <span x-show="!status.cli_available" class="text-yellow-400"> (required - CLI not detected)</span>
                </p>
                <button @click="saveApiKey()" :disabled="!apiKey"
                    class="w-full mt-4 bg-indigo-500 hover:bg-indigo-600 disabled:opacity-50 rounded-lg py-3 font-medium transition">
                    Use API Key
                </button>
            </div>

            <!-- Step 2: Permissions -->
            <div x-show="setupStep === 2">
                <p class="text-gray-300 mb-4">Grant these permissions once, then CronAgent runs in auto mode:</p>
                <div class="space-y-3">
                    <label class="flex items-center gap-3 p-3 bg-gray-700 rounded-lg cursor-pointer hover:bg-gray-600">
                        <input type="checkbox" x-model="permissions.files" class="w-5 h-5 rounded text-indigo-500">
                        <div>
                            <div class="font-medium">Read & Write Files</div>
                            <div class="text-sm text-gray-400">Edit code, create files</div>
                        </div>
                    </label>
                    <label class="flex items-center gap-3 p-3 bg-gray-700 rounded-lg cursor-pointer hover:bg-gray-600">
                        <input type="checkbox" x-model="permissions.shell" class="w-5 h-5 rounded text-indigo-500">
                        <div>
                            <div class="font-medium">Run Commands</div>
                            <div class="text-sm text-gray-400">Execute shell commands</div>
                        </div>
                    </label>
                    <label class="flex items-center gap-3 p-3 bg-gray-700 rounded-lg cursor-pointer hover:bg-gray-600">
                        <input type="checkbox" x-model="permissions.network" class="w-5 h-5 rounded text-indigo-500">
                        <div>
                            <div class="font-medium">Network Access</div>
                            <div class="text-sm text-gray-400">Make API calls, fetch data</div>
                        </div>
                    </label>
                </div>
                <button @click="grantPermissions()"
                    class="w-full mt-4 bg-indigo-500 hover:bg-indigo-600 rounded-lg py-3 font-medium transition">
                    Grant & Start Using
                </button>
            </div>
        </div>
    </div>

    <!-- Main Dashboard -->
    <div x-show="!showSetup" class="flex h-screen">

        <!-- Sidebar -->
        <div class="w-64 bg-gray-800 border-r border-gray-700 flex flex-col">
            <div class="p-4 border-b border-gray-700">
                <h1 class="text-xl font-bold flex items-center gap-2">
                    <span class="w-8 h-8 bg-indigo-500 rounded-lg flex items-center justify-center">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                    </span>
                    CronAgent
                </h1>
            </div>

            <nav class="flex-1 p-4 space-y-2">
                <button @click="view = 'chat'" :class="view === 'chat' ? 'bg-gray-700' : 'hover:bg-gray-700'"
                    class="w-full flex items-center gap-3 px-4 py-2 rounded-lg transition">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
                    </svg>
                    Chat
                </button>
                <button @click="view = 'jobs'" :class="view === 'jobs' ? 'bg-gray-700' : 'hover:bg-gray-700'"
                    class="w-full flex items-center gap-3 px-4 py-2 rounded-lg transition">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                    </svg>
                    Jobs
                    <span x-show="jobs.length" class="ml-auto bg-gray-600 text-xs px-2 py-0.5 rounded-full" x-text="jobs.length"></span>
                </button>
                <button @click="view = 'history'" :class="view === 'history' ? 'bg-gray-700' : 'hover:bg-gray-700'"
                    class="w-full flex items-center gap-3 px-4 py-2 rounded-lg transition">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                    </svg>
                    History
                </button>
            </nav>

            <!-- Status -->
            <div class="p-4 border-t border-gray-700">
                <div class="flex items-center gap-2 text-sm">
                    <span class="w-2 h-2 rounded-full" :class="status.ready ? 'bg-green-500' : 'bg-red-500'"></span>
                    <span x-text="status.ready ? (status.mode === 'cli' ? 'CLI Mode (Free)' : 'API Mode') : 'Not configured'"></span>
                </div>
                <div x-show="status.mode === 'cli'" class="text-xs text-gray-500 mt-1">Using your subscription</div>
            </div>
        </div>

        <!-- Main Content -->
        <div class="flex-1 flex flex-col">

            <!-- Chat View -->
            <div x-show="view === 'chat'" class="flex-1 flex flex-col">
                <div class="p-4 border-b border-gray-700">
                    <h2 class="text-lg font-semibold">Chat with Agent</h2>
                </div>

                <div class="flex-1 overflow-y-auto p-4 space-y-4" id="chat-messages">
                    <template x-for="msg in messages" :key="msg.id">
                        <div :class="msg.role === 'user' ? 'ml-auto bg-indigo-500' : 'bg-gray-700'"
                            class="max-w-2xl rounded-2xl px-4 py-3">
                            <div class="text-sm opacity-60 mb-1" x-text="msg.role === 'user' ? 'You' : 'Agent'"></div>
                            <div class="whitespace-pre-wrap" x-text="msg.content"></div>
                            <div x-show="msg.tool_uses?.length" class="mt-2 text-xs opacity-60">
                                <template x-for="tool in msg.tool_uses">
                                    <span class="inline-block bg-gray-600 rounded px-2 py-1 mr-1" x-text="tool.tool"></span>
                                </template>
                            </div>
                        </div>
                    </template>
                    <div x-show="loading" class="flex items-center gap-2 text-gray-400">
                        <div class="animate-pulse-slow">Thinking...</div>
                    </div>
                </div>

                <div class="p-4 border-t border-gray-700">
                    <form @submit.prevent="sendMessage()" class="flex gap-2">
                        <input type="text" x-model="chatInput" :disabled="loading"
                            class="flex-1 bg-gray-700 rounded-lg px-4 py-3 focus:ring-2 focus:ring-indigo-500 outline-none"
                            placeholder="Ask the agent anything...">
                        <button type="submit" :disabled="loading || !chatInput"
                            class="bg-indigo-500 hover:bg-indigo-600 disabled:opacity-50 rounded-lg px-6 py-3 font-medium transition">
                            Send
                        </button>
                    </form>
                </div>
            </div>

            <!-- Jobs View -->
            <div x-show="view === 'jobs'" class="flex-1 flex flex-col">
                <div class="p-4 border-b border-gray-700 flex items-center justify-between">
                    <h2 class="text-lg font-semibold">Scheduled Jobs</h2>
                    <button @click="showNewJob = true" class="bg-indigo-500 hover:bg-indigo-600 rounded-lg px-4 py-2 text-sm font-medium transition">
                        + New Job
                    </button>
                </div>

                <div class="flex-1 overflow-y-auto p-4">
                    <div x-show="jobs.length === 0" class="text-center text-gray-400 py-12">
                        <svg class="w-12 h-12 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                        <p>No jobs scheduled yet</p>
                        <button @click="showNewJob = true" class="mt-4 text-indigo-400 hover:underline">Create your first job</button>
                    </div>

                    <div class="space-y-3">
                        <template x-for="job in jobs" :key="job.id">
                            <div class="bg-gray-800 rounded-xl p-4 border border-gray-700">
                                <div class="flex items-start justify-between">
                                    <div>
                                        <h3 class="font-semibold" x-text="job.name"></h3>
                                        <p class="text-sm text-gray-400 mt-1">
                                            <span x-text="job.schedule_type"></span> &bull;
                                            <span x-text="job.run_count + ' runs'"></span> &bull;
                                            <span :class="job.last_status === 'success' ? 'text-green-400' : job.last_status === 'failure' ? 'text-red-400' : ''"
                                                x-text="job.last_status || 'Never run'"></span>
                                        </p>
                                    </div>
                                    <div class="flex items-center gap-2">
                                        <button @click="triggerJob(job.id)" :disabled="runningJobs && runningJobs[job.id]" class="p-2 hover:bg-gray-700 rounded-lg transition disabled:opacity-50" title="Run now">
                                            <!-- Spinner when running -->
                                            <svg x-show="runningJobs && runningJobs[job.id]" class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                                                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                                            </svg>
                                            <!-- Play icon when not running -->
                                            <svg x-show="!runningJobs || !runningJobs[job.id]" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/>
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                            </svg>
                                        </button>
                                        <button @click="deleteJob(job.id)" class="p-2 hover:bg-gray-700 rounded-lg transition text-red-400" title="Delete">
                                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                            </svg>
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </template>
                    </div>
                </div>
            </div>

            <!-- History/Audit View -->
            <div x-show="view === 'history'" class="flex-1 flex flex-col">
                <div class="p-4 border-b border-gray-700">
                    <h2 class="text-lg font-semibold">Run History & Audit Log</h2>
                </div>

                <div class="flex-1 overflow-y-auto">
                    <table class="w-full">
                        <thead class="bg-gray-800 sticky top-0">
                            <tr class="text-left text-sm text-gray-400">
                                <th class="p-4">Status</th>
                                <th class="p-4">Job</th>
                                <th class="p-4">Started</th>
                                <th class="p-4">Duration</th>
                                <th class="p-4">Trigger</th>
                                <th class="p-4">Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            <template x-for="run in runs" :key="run.id">
                                <tr class="border-t border-gray-700 hover:bg-gray-800/50">
                                    <td class="p-4">
                                        <span :class="{
                                            'bg-green-500/20 text-green-400': run.status === 'success',
                                            'bg-red-500/20 text-red-400': run.status === 'failure',
                                            'bg-yellow-500/20 text-yellow-400': run.status === 'running',
                                            'bg-gray-500/20 text-gray-400': run.status === 'pending'
                                        }" class="px-2 py-1 rounded text-xs font-medium" x-text="run.status"></span>
                                    </td>
                                    <td class="p-4 font-medium" x-text="run.job_id"></td>
                                    <td class="p-4 text-sm text-gray-400" x-text="run.started_at ? new Date(run.started_at).toLocaleString() : '-'"></td>
                                    <td class="p-4 text-sm" x-text="run.duration_ms ? (run.duration_ms / 1000).toFixed(1) + 's' : '-'"></td>
                                    <td class="p-4 text-sm text-gray-400" x-text="run.triggered_by"></td>
                                    <td class="p-4">
                                        <button @click="viewRun(run.id)" class="text-indigo-400 hover:underline text-sm">View</button>
                                    </td>
                                </tr>
                            </template>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <!-- New Job Modal -->
    <div x-show="showNewJob" x-cloak class="fixed inset-0 bg-black/80 flex items-center justify-center z-50">
        <div class="bg-gray-800 rounded-2xl p-6 max-w-lg w-full mx-4 shadow-2xl">
            <h3 class="text-xl font-bold mb-4">Create New Job</h3>
            <form @submit.prevent="createJob()">
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium mb-1">Job Name</label>
                        <input type="text" x-model="newJob.name" required
                            class="w-full bg-gray-700 rounded-lg px-4 py-2 focus:ring-2 focus:ring-indigo-500 outline-none"
                            placeholder="Daily Security Scan">
                    </div>
                    <div>
                        <label class="block text-sm font-medium mb-1">Cron Schedule</label>
                        <input type="text" x-model="newJob.cron"
                            class="w-full bg-gray-700 rounded-lg px-4 py-2 focus:ring-2 focus:ring-indigo-500 outline-none"
                            placeholder="0 9 * * * (every day at 9am)">
                    </div>
                    <div>
                        <label class="block text-sm font-medium mb-1">Prompt</label>
                        <textarea x-model="newJob.prompt" rows="4" required
                            class="w-full bg-gray-700 rounded-lg px-4 py-2 focus:ring-2 focus:ring-indigo-500 outline-none"
                            placeholder="What should the agent do?"></textarea>
                    </div>
                </div>
                <div class="flex gap-3 mt-6">
                    <button type="button" @click="showNewJob = false"
                        class="flex-1 bg-gray-700 hover:bg-gray-600 rounded-lg py-2 font-medium transition">Cancel</button>
                    <button type="submit"
                        class="flex-1 bg-indigo-500 hover:bg-indigo-600 rounded-lg py-2 font-medium transition">Create Job</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Job Result Modal - Shows immediately after job execution -->
    <div x-show="jobResult" x-cloak class="fixed inset-0 bg-black/80 flex items-center justify-center z-50" @keydown.escape.window="jobResult = null">
        <div class="bg-gray-800 rounded-2xl p-6 max-w-3xl w-full mx-4 shadow-2xl max-h-[85vh] overflow-y-auto">
            <div class="flex items-center justify-between mb-4">
                <div class="flex items-center gap-3">
                    <!-- Status Icon -->
                    <div :class="jobResult?.success ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'" class="p-2 rounded-full">
                        <svg x-show="jobResult?.success" class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/>
                        </svg>
                        <svg x-show="!jobResult?.success" class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                        </svg>
                    </div>
                    <div>
                        <h3 class="text-xl font-bold" x-text="jobResult?.success ? 'Job Completed' : 'Job Failed'"></h3>
                        <p class="text-sm text-gray-400" x-text="jobResult?.jobName"></p>
                    </div>
                </div>
                <button @click="jobResult = null" class="p-2 hover:bg-gray-700 rounded-lg">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>

            <template x-if="jobResult">
                <div class="space-y-4">
                    <!-- Meta info -->
                    <div class="flex flex-wrap gap-4 text-sm text-gray-400">
                        <span>Run ID: <span class="text-white" x-text="jobResult.runId"></span></span>
                        <span>Time: <span class="text-white" x-text="jobResult.timestamp"></span></span>
                        <span x-show="jobResult.duration">Duration: <span class="text-white" x-text="jobResult.duration"></span></span>
                        <span x-show="jobResult.cost">Cost: <span class="text-white" x-text="jobResult.cost"></span></span>
                    </div>

                    <!-- Output Section -->
                    <div x-show="jobResult.output" class="space-y-2">
                        <div class="flex items-center justify-between">
                            <span class="text-sm font-medium text-gray-300">Agent Response</span>
                            <button @click="navigator.clipboard.writeText(jobResult.output); showNotification('Copied!', 'success')"
                                class="text-xs text-indigo-400 hover:text-indigo-300">Copy</button>
                        </div>
                        <div class="bg-gray-900 rounded-lg p-4 max-h-96 overflow-y-auto">
                            <div class="prose prose-invert prose-sm max-w-none" x-html="formatMarkdown(jobResult.output)"></div>
                        </div>
                    </div>

                    <!-- Error Section -->
                    <div x-show="jobResult.error" class="space-y-2">
                        <span class="text-sm font-medium text-red-400">Error</span>
                        <pre class="bg-red-900/30 rounded-lg p-4 text-sm text-red-300 overflow-x-auto" x-text="jobResult.error"></pre>
                    </div>

                    <!-- Actions -->
                    <div class="flex gap-3 pt-4 border-t border-gray-700">
                        <button @click="jobResult = null"
                            class="flex-1 bg-gray-700 hover:bg-gray-600 rounded-lg py-2 font-medium transition">Close</button>
                        <button @click="viewFullRun(jobResult.runId)"
                            class="flex-1 bg-indigo-500 hover:bg-indigo-600 rounded-lg py-2 font-medium transition">View Full Details</button>
                    </div>
                </div>
            </template>
        </div>
    </div>

    <!-- Run Detail Modal -->
    <div x-show="selectedRun" x-cloak class="fixed inset-0 bg-black/80 flex items-center justify-center z-50">
        <div class="bg-gray-800 rounded-2xl p-6 max-w-2xl w-full mx-4 shadow-2xl max-h-[80vh] overflow-y-auto">
            <div class="flex items-center justify-between mb-4">
                <h3 class="text-xl font-bold">Run Details</h3>
                <button @click="selectedRun = null" class="p-2 hover:bg-gray-700 rounded-lg">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
            <template x-if="selectedRun">
                <div class="space-y-4">
                    <div class="grid grid-cols-2 gap-4 text-sm">
                        <div><span class="text-gray-400">Status:</span> <span x-text="selectedRun.status"></span></div>
                        <div><span class="text-gray-400">Job ID:</span> <span x-text="selectedRun.job_id"></span></div>
                        <div><span class="text-gray-400">Started:</span> <span x-text="selectedRun.started_at"></span></div>
                        <div><span class="text-gray-400">Duration:</span> <span x-text="selectedRun.duration_ms ? (selectedRun.duration_ms/1000) + 's' : '-'"></span></div>
                        <div><span class="text-gray-400">Triggered by:</span> <span x-text="selectedRun.triggered_by"></span></div>
                        <div><span class="text-gray-400">Cost:</span> <span x-text="selectedRun.cost_usd ? '$' + selectedRun.cost_usd.toFixed(4) : '-'"></span></div>
                    </div>
                    <div x-show="selectedRun.output">
                        <div class="text-sm text-gray-400 mb-2">Output:</div>
                        <pre class="bg-gray-900 rounded-lg p-4 text-sm overflow-x-auto whitespace-pre-wrap" x-text="selectedRun.output"></pre>
                    </div>
                    <div x-show="selectedRun.error">
                        <div class="text-sm text-red-400 mb-2">Error:</div>
                        <pre class="bg-red-900/30 rounded-lg p-4 text-sm text-red-300" x-text="selectedRun.error"></pre>
                    </div>
                </div>
            </template>
        </div>
    </div>

<script>
function dashboard() {
    return {
        // State
        showSetup: false,
        setupStep: 1,
        apiKey: '',
        permissions: { files: true, shell: true, network: true },

        view: 'chat',
        status: { api_key_configured: false, permissions_granted: false },

        // Chat
        messages: [],
        chatInput: '',
        loading: false,

        // Jobs
        jobs: [],
        showNewJob: false,
        newJob: { name: '', cron: '', prompt: '' },

        // History
        runs: [],
        selectedRun: null,
        runningJobs: {},
        jobResult: null,  // For showing job output after execution

        // WebSocket
        ws: null,

        async init() {
            await this.checkStatus();
            this.connectWebSocket();
            this.loadJobs();
            this.loadRuns();
        },

        async checkStatus() {
            const res = await fetch('/api/status');
            this.status = await res.json();

            // If CLI is available OR API key is set, we're ready
            if (!this.status.ready) {
                // Need API key (CLI not available)
                this.showSetup = true;
                this.setupStep = 1;
            } else if (!this.status.permissions_granted) {
                this.showSetup = true;
                this.setupStep = 2;
            }
        },

        async saveApiKey() {
            await fetch('/api/setup', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: this.apiKey })
            });
            this.setupStep = 2;
        },

        skipApiKey() {
            // Skip API key setup when CLI is available
            this.setupStep = 2;
        },

        async grantPermissions() {
            const perms = Object.entries(this.permissions)
                .filter(([k, v]) => v)
                .map(([k]) => k);

            await fetch('/api/permissions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ permissions: perms })
            });

            this.showSetup = false;
        },

        connectWebSocket() {
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            this.ws = new WebSocket(`${protocol}//${location.host}/ws`);

            this.ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'job_created' || data.type === 'job_deleted') {
                    this.loadJobs();
                } else if (data.type === 'job_triggered') {
                    this.loadRuns();
                }
            };

            this.ws.onclose = () => {
                setTimeout(() => this.connectWebSocket(), 3000);
            };
        },

        async sendMessage() {
            if (!this.chatInput.trim() || this.loading) return;

            const msg = this.chatInput;
            this.chatInput = '';
            this.messages.push({ id: Date.now(), role: 'user', content: msg });
            this.loading = true;

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: msg })
                });
                const data = await res.json();

                this.messages.push({
                    id: Date.now(),
                    role: 'assistant',
                    content: data.response,
                    tool_uses: data.tool_uses
                });
            } catch (e) {
                this.messages.push({
                    id: Date.now(),
                    role: 'assistant',
                    content: 'Error: ' + e.message
                });
            }

            this.loading = false;
            this.$nextTick(() => {
                document.getElementById('chat-messages').scrollTop = 999999;
            });
        },

        async loadJobs() {
            const res = await fetch('/api/jobs');
            const data = await res.json();
            this.jobs = data.jobs || [];
        },

        async loadRuns() {
            const res = await fetch('/api/runs');
            const data = await res.json();
            this.runs = data.runs || [];
        },

        async createJob() {
            await fetch('/api/jobs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.newJob)
            });
            this.showNewJob = false;
            this.newJob = { name: '', cron: '', prompt: '' };
            this.loadJobs();
        },

        async triggerJob(id) {
            // Find job name
            const job = this.jobs.find(j => j.id === id);
            const jobName = job ? job.name : id;

            // Mark job as running
            this.runningJobs[id] = true;

            // Show notification
            this.showNotification(`Running: ${jobName}...`, 'info');

            try {
                const res = await fetch(`/api/jobs/${id}/trigger`, { method: 'POST' });
                const result = await res.json();

                // Show result in modal
                this.jobResult = {
                    jobName: jobName,
                    jobId: id,
                    success: result.success,
                    status: result.status,
                    output: result.output,
                    error: result.error,
                    runId: result.run_id,
                    timestamp: new Date().toLocaleString()
                };

                if (result.success) {
                    this.showNotification('Job completed! Click to view results.', 'success');
                } else {
                    this.showNotification('Job failed - see details', 'error');
                }
            } catch (e) {
                this.jobResult = {
                    jobName: jobName,
                    jobId: id,
                    success: false,
                    error: e.message || 'Connection error',
                    timestamp: new Date().toLocaleString()
                };
                this.showNotification('Job execution error', 'error');
            } finally {
                this.runningJobs[id] = false;
                this.loadRuns();
                this.loadJobs();
            }
        },

        showNotification(message, type = 'info') {
            // Create and show a toast notification
            const toast = document.createElement('div');
            toast.className = `fixed top-4 right-4 px-6 py-3 rounded-lg shadow-lg z-50 transition-all transform ${
                type === 'success' ? 'bg-green-600' :
                type === 'error' ? 'bg-red-600' : 'bg-indigo-600'
            } text-white`;
            toast.textContent = message;
            document.body.appendChild(toast);
            setTimeout(() => {
                toast.style.opacity = '0';
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        },

        async deleteJob(id) {
            if (!confirm('Delete this job?')) return;
            await fetch(`/api/jobs/${id}`, { method: 'DELETE' });
            this.loadJobs();
        },

        async viewRun(id) {
            const res = await fetch(`/api/runs/${id}`);
            const run = await res.json();

            // Find job name
            const job = this.jobs.find(j => j.id === run.job_id);
            const jobName = job ? job.name : run.job_id;

            // Show in the nice result modal
            this.jobResult = {
                jobName: jobName,
                jobId: run.job_id,
                success: run.status === 'success',
                status: run.status,
                output: run.output,
                error: run.error,
                runId: id,
                timestamp: run.started_at ? new Date(run.started_at).toLocaleString() : '-',
                duration: run.duration_ms ? (run.duration_ms / 1000).toFixed(1) + 's' : null,
                cost: run.cost_usd ? '$' + run.cost_usd.toFixed(4) : null
            };
        },

        async viewFullRun(id) {
            // Already showing the nice modal, just keep it open
            // This is called from the job result modal to view full details
            const res = await fetch(`/api/runs/${id}`);
            this.selectedRun = await res.json();
            this.jobResult = null;  // Switch to detailed view
        },

        formatMarkdown(text) {
            if (!text) return '';
            // Simple markdown formatting
            return text
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.+?)\*/g, '<em>$1</em>')
                .replace(/`(.+?)`/g, '<code class="bg-gray-800 px-1 rounded">$1</code>')
                .replace(/^### (.+)$/gm, '<h3 class="text-lg font-bold mt-4 mb-2">$1</h3>')
                .replace(/^## (.+)$/gm, '<h2 class="text-xl font-bold mt-4 mb-2">$1</h2>')
                .replace(/^# (.+)$/gm, '<h1 class="text-2xl font-bold mt-4 mb-2">$1</h1>')
                .replace(/^- (.+)$/gm, '<li class="ml-4">$1</li>')
                .replace(/\\n\\n/g, '</p><p class="mb-2">')
                .replace(/\\n/g, '<br>');
        }
    };
}
</script>
</body>
</html>'''


def run_dashboard(host: str = "0.0.0.0", port: int = 8080):
    """Run the dashboard server."""
    import uvicorn
    app = create_app()
    uvicorn.run(app, host=host, port=port)
