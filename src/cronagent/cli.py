"""
CronAgent CLI - Command line interface.

Usage:
    cronagent init           # Initialize configuration
    cronagent agent          # Start interactive agent
    cronagent run "prompt"   # Run a single task
    cronagent daemon         # Run scheduler daemon
    cronagent status         # Show system status
    cronagent cron list      # List scheduled jobs
    cronagent cron add       # Add a new job
    cronagent cron remove    # Remove a job
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from cronagent import __version__
from cronagent.config import CronAgentConfig

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="cronagent")
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=False),
    help="Path to config file",
)
@click.pass_context
def main(ctx: click.Context, config: str | None) -> None:
    """CronAgent - Autonomous agent system with Claude SDK."""
    ctx.ensure_object(dict)

    # Load configuration
    config_path = Path(config) if config else None
    ctx.obj["config"] = CronAgentConfig.load(config_path)


@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Initialize CronAgent configuration."""
    config_dir = Path.home() / ".cronagent"
    config_file = config_dir / "config.yaml"

    if config_file.exists():
        if not click.confirm(f"Config file exists at {config_file}. Overwrite?"):
            console.print("[yellow]Initialization cancelled.[/yellow]")
            return

    # Create directories
    config_dir.mkdir(parents=True, exist_ok=True)

    # Write default config
    default_config = """\
# CronAgent Configuration
# https://github.com/yourname/cronagent

agent:
  model: "claude-sonnet-4-20250514"
  max_turns: 50
  permission_mode: "acceptEdits"

scheduler:
  job_store_url: "sqlite:///~/.cronagent/jobs.db"
  timezone: "UTC"
  max_concurrent_jobs: 5

memory:
  storage_type: "sqlite"
  sqlite_path: "~/.cronagent/sessions.db"
  enable_knowledge_base: true
  knowledge_store: "chromadb"
  chromadb_path: "~/.cronagent/knowledge"

channels:
  cli:
    enabled: true
    prompt: "cronagent> "

  telegram:
    enabled: false
    token: "${TELEGRAM_BOT_TOKEN}"
    allowed_users: []

  slack:
    enabled: false
    bot_token: "${SLACK_BOT_TOKEN}"

  webhook:
    enabled: false
    port: 8080
    path: "/webhook"

notifications:
  default_channels: ["console"]
  on_job_start: false
  on_job_complete: true
  on_job_failure: true

log_level: "INFO"
skills_dir: "~/.cronagent/skills"

# Example scheduled jobs (uncomment to use):
# jobs:
#   - id: "daily-review"
#     name: "Daily Code Review"
#     cron: "0 9 * * *"
#     prompt: |
#       Review recent commits and provide a summary of changes.
"""

    with open(config_file, "w") as f:
        f.write(default_config)

    # Create skills directory
    skills_dir = config_dir / "skills"
    skills_dir.mkdir(exist_ok=True)

    console.print(f"[green]Created configuration at {config_file}[/green]")
    console.print("\nNext steps:")
    console.print("  1. Edit ~/.cronagent/config.yaml with your settings")
    console.print("  2. Set ANTHROPIC_API_KEY environment variable")
    console.print("  3. Run: cronagent agent")


@main.command()
@click.argument("prompt", required=False)
@click.option(
    "--working-dir",
    "-w",
    type=click.Path(exists=True),
    default=".",
    help="Working directory",
)
@click.option(
    "--model",
    "-m",
    default=None,
    help="Override model",
)
@click.pass_context
def run(
    ctx: click.Context,
    prompt: str | None,
    working_dir: str,
    model: str | None,
) -> None:
    """Run a single agent task."""
    config: CronAgentConfig = ctx.obj["config"]

    if not prompt:
        # Read from stdin if no prompt provided
        if sys.stdin.isatty():
            console.print("[red]Error: No prompt provided.[/red]")
            console.print("Usage: cronagent run 'your prompt here'")
            console.print("   or: echo 'prompt' | cronagent run")
            raise SystemExit(1)
        prompt = sys.stdin.read().strip()

    if not prompt:
        console.print("[red]Error: Empty prompt.[/red]")
        raise SystemExit(1)

    asyncio.run(_run_task(config, prompt, working_dir, model))


async def _run_task(
    config: CronAgentConfig,
    prompt: str,
    working_dir: str,
    model: str | None,
) -> None:
    """Execute a single task."""
    from cronagent.agent.loop import AgentLoop, AgentLoopConfig
    from cronagent.bus.events import EventBus

    # Setup
    event_bus = EventBus()
    loop_config = AgentLoopConfig(
        working_directory=working_dir,
        model=model or config.agent.model,
        max_turns=config.agent.max_turns,
        permission_mode=config.agent.permission_mode,
    )
    agent = AgentLoop(loop_config, event_bus=event_bus)

    console.print(Panel(f"[bold]Task:[/bold] {prompt[:100]}...", title="CronAgent"))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running agent...", total=None)

        result_parts = []
        try:
            async for event in agent.execute(prompt):
                if event.type == "text":
                    result_parts.append(event.content)
                elif event.type == "tool_use":
                    tool_name = event.content.get("tool", "unknown")
                    progress.update(task, description=f"Using tool: {tool_name}")
                elif event.type == "result":
                    cost = event.metadata.get("cost_usd", 0)
                    progress.update(task, description=f"Complete (${cost:.4f})")
                elif event.type == "error":
                    console.print(f"[red]Error: {event.content}[/red]")
                    raise SystemExit(1)

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise SystemExit(1)

    # Display result
    result = "".join(result_parts)
    if result:
        console.print("\n[bold]Result:[/bold]")
        console.print(Markdown(result))


@main.command()
@click.pass_context
def agent(ctx: click.Context) -> None:
    """Start interactive agent mode."""
    config: CronAgentConfig = ctx.obj["config"]

    console.print(
        Panel(
            "[bold]CronAgent Interactive Mode[/bold]\n"
            "Type your prompts and press Enter.\n"
            "Commands: /quit, /clear, /status",
            title="Welcome",
        )
    )

    asyncio.run(_interactive_loop(config))


async def _interactive_loop(config: CronAgentConfig) -> None:
    """Run interactive agent loop."""
    from cronagent.agent.loop import AgentLoop, AgentLoopConfig
    from cronagent.bus.events import EventBus

    event_bus = EventBus()
    loop_config = AgentLoopConfig(
        working_directory=".",
        model=config.agent.model,
        max_turns=config.agent.max_turns,
        permission_mode=config.agent.permission_mode,
    )
    agent = AgentLoop(loop_config, event_bus=event_bus)

    prompt_str = config.channels.cli.prompt

    while True:
        try:
            # Get input
            user_input = console.input(f"[bold cyan]{prompt_str}[/bold cyan]").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.startswith("/"):
                cmd = user_input[1:].lower()
                if cmd in ("quit", "exit", "q"):
                    console.print("[yellow]Goodbye![/yellow]")
                    break
                elif cmd == "clear":
                    console.clear()
                    continue
                elif cmd == "status":
                    console.print(f"Model: {config.agent.model}")
                    console.print(f"Session: {agent.session_id or 'None'}")
                    continue
                elif cmd == "help":
                    console.print("Commands: /quit, /clear, /status, /help")
                    continue
                else:
                    console.print(f"[yellow]Unknown command: {cmd}[/yellow]")
                    continue

            # Execute prompt
            console.print()
            result_parts = []

            async for event in agent.execute(user_input):
                if event.type == "text":
                    result_parts.append(event.content)
                    # Stream output
                    console.print(event.content, end="")
                elif event.type == "tool_use":
                    tool = event.content.get("tool", "unknown")
                    console.print(f"\n[dim]Using tool: {tool}[/dim]")
                elif event.type == "result":
                    cost = event.metadata.get("cost_usd", 0)
                    console.print(f"\n[dim]Cost: ${cost:.4f}[/dim]")
                elif event.type == "error":
                    console.print(f"\n[red]Error: {event.content}[/red]")

            console.print("\n")

        except KeyboardInterrupt:
            console.print("\n[yellow]Use /quit to exit[/yellow]")
        except EOFError:
            break


@main.command()
@click.option(
    "--foreground",
    "-f",
    is_flag=True,
    help="Run in foreground (don't daemonize)",
)
@click.pass_context
def daemon(ctx: click.Context, foreground: bool) -> None:
    """Run scheduler daemon (background service)."""
    config: CronAgentConfig = ctx.obj["config"]

    console.print(
        Panel(
            "[bold]CronAgent Scheduler Daemon[/bold]\n"
            "Press Ctrl+C to stop.",
            title="Daemon Mode",
        )
    )

    asyncio.run(_run_daemon(config))


async def _run_daemon(config: CronAgentConfig) -> None:
    """Run the scheduler daemon."""
    from cronagent.bus.events import EventBus
    from cronagent.cron.scheduler import create_scheduler
    from cronagent.notifications import create_notification_service

    # Setup components
    event_bus = EventBus()

    # Create notification service (subscribes to event bus for job notifications)
    notification_service = create_notification_service(
        config=config.notifications,
        event_bus=event_bus,
        slack_webhook=os.environ.get("SLACK_WEBHOOK_URL"),
        discord_webhook=os.environ.get("DISCORD_WEBHOOK_URL"),
    )

    # Create scheduler (passes full config, uses config.memory and config.scheduler internally)
    scheduler = await create_scheduler(
        config=config,
        event_bus=event_bus,
    )

    # Start scheduler
    await scheduler.start()
    console.print("[green]Scheduler started[/green]")

    # Show loaded jobs
    jobs = await scheduler.list_jobs()
    console.print(f"[dim]Loaded {len(jobs)} jobs[/dim]")

    # Setup shutdown handling
    shutdown_event = asyncio.Event()

    def handle_shutdown(signum, frame):
        console.print("\n[yellow]Shutdown signal received...[/yellow]")
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    # Subscribe to job events for logging
    async def log_job_event(event_type: str, data: dict) -> None:
        job_id = data.get("job_id", "unknown")
        status = data.get("status", event_type)
        console.print(f"[dim]{datetime.now().strftime('%H:%M:%S')} Job {job_id}: {status}[/dim]")

    event_bus.subscribe("job:*", log_job_event)

    console.print("[bold green]Daemon running. Press Ctrl+C to stop.[/bold green]")

    # Wait for shutdown
    await shutdown_event.wait()

    # Graceful shutdown
    console.print("[yellow]Shutting down scheduler...[/yellow]")
    await scheduler.shutdown()
    console.print("[green]Scheduler stopped[/green]")


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show system status."""
    config: CronAgentConfig = ctx.obj["config"]

    console.print(Panel("[bold]CronAgent Status[/bold]", title="Status"))

    # Config info
    console.print(f"\n[bold]Configuration:[/bold]")
    console.print(f"  Model: {config.agent.model}")
    console.print(f"  Working Dir: {config.agent.working_directory}")
    console.print(f"  Permission Mode: {config.agent.permission_mode}")

    # Storage info
    console.print(f"\n[bold]Storage:[/bold]")
    console.print(f"  Type: {config.memory.storage_type}")
    console.print(f"  Knowledge Base: {config.memory.enable_knowledge_base}")

    # Channels info
    console.print(f"\n[bold]Channels:[/bold]")
    console.print(f"  CLI: {config.channels.cli.enabled}")
    console.print(f"  Telegram: {config.channels.telegram.enabled}")
    console.print(f"  Slack: {config.channels.slack.enabled}")
    console.print(f"  Discord: {config.channels.discord.enabled}")
    console.print(f"  Webhook: {config.channels.webhook.enabled}")

    # Check ANTHROPIC_API_KEY
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        console.print(f"\n[green]ANTHROPIC_API_KEY: Set ({len(api_key)} chars)[/green]")
    else:
        console.print("\n[red]ANTHROPIC_API_KEY: Not set![/red]")
        console.print("  Set with: export ANTHROPIC_API_KEY=your-key-here")

    # Show job count if scheduler is accessible
    asyncio.run(_show_job_status(config))


async def _show_job_status(config: CronAgentConfig) -> None:
    """Show job status if available."""
    try:
        from cronagent.cron.store import JobStore
        from cronagent.storage.database import Database

        db = Database.from_config(config.memory)
        await db.initialize()
        store = JobStore(db)

        jobs = await store.list_jobs()
        stats = await store.get_summary_stats()

        console.print(f"\n[bold]Scheduler:[/bold]")
        console.print(f"  Jobs: {len(jobs)}")
        console.print(f"  Total Runs: {stats.get('total_runs', 0)}")
        console.print(f"  Success Rate: {stats.get('success_rate', 0):.1%}")

        await db.close()
    except Exception:
        # Scheduler not initialized
        pass


@main.command()
@click.pass_context
def reload(ctx: click.Context) -> None:
    """Reload configuration from api.txt and config files."""
    config_dir = Path.home() / ".cronagent"
    api_file = config_dir / "api.txt"

    if api_file.exists():
        # Load environment variables from api.txt
        with open(api_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()
                    console.print(f"  [green]Loaded[/green] {key.strip()}")

        console.print("\n[green]Configuration reloaded![/green]")
        console.print("Note: Running daemons need to be restarted to pick up changes.")
    else:
        console.print(f"[yellow]No api.txt found at {api_file}[/yellow]")
        console.print("Run 'cronagent init' to create one.")


# ============================================================
# Cron command group
# ============================================================

@main.group()
@click.pass_context
def cron(ctx: click.Context) -> None:
    """Manage scheduled jobs."""
    pass


@cron.command("list")
@click.option("--status", "-s", help="Filter by status (active/paused)")
@click.option("--verbose", "-v", is_flag=True, help="Show more details")
@click.pass_context
def cron_list(ctx: click.Context, status: str | None, verbose: bool) -> None:
    """List all scheduled jobs."""
    config: CronAgentConfig = ctx.obj["config"]
    asyncio.run(_list_jobs(config, status, verbose))


async def _list_jobs(config: CronAgentConfig, status_filter: str | None, verbose: bool) -> None:
    """List jobs from the store."""
    from cronagent.cron.store import JobStore
    from cronagent.storage.database import Database

    try:
        db = Database.from_config(config.memory)
        await db.initialize()
        store = JobStore(db)

        jobs = await store.list_jobs()

        if not jobs:
            console.print("[yellow]No scheduled jobs found.[/yellow]")
            console.print("Use 'cronagent cron add' to create a job.")
            return

        # Filter by status
        if status_filter:
            jobs = [j for j in jobs if j.status == status_filter]

        # Create table
        table = Table(title="Scheduled Jobs")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="bold")
        table.add_column("Schedule")
        table.add_column("Status")
        table.add_column("Last Run")
        table.add_column("Next Run")

        if verbose:
            table.add_column("Type")
            table.add_column("Runs")

        for job in jobs:
            # Format schedule
            schedule = job.schedule
            if hasattr(schedule, "expression"):
                schedule_str = schedule.expression
            elif hasattr(schedule, "seconds"):
                schedule_str = f"every {schedule.seconds}s"
            elif hasattr(schedule, "run_at"):
                schedule_str = schedule.run_at.strftime("%Y-%m-%d %H:%M")
            else:
                schedule_str = str(schedule)

            # Format status with color
            status_str = job.status
            if job.status == "active":
                status_str = "[green]active[/green]"
            elif job.status == "paused":
                status_str = "[yellow]paused[/yellow]"

            # Format timestamps
            last_run = job.last_run.strftime("%m/%d %H:%M") if job.last_run else "-"
            next_run = job.next_run.strftime("%m/%d %H:%M") if job.next_run else "-"

            row = [job.id, job.name, schedule_str, status_str, last_run, next_run]

            if verbose:
                exec_type = job.execution.type if hasattr(job.execution, "type") else "unknown"
                stats = await store.get_job_stats(job.id)
                runs = f"{stats.get('success', 0)}/{stats.get('total', 0)}"
                row.extend([exec_type, runs])

            table.add_row(*row)

        console.print(table)

        await db.close()

    except Exception as e:
        console.print(f"[red]Error listing jobs: {e}[/red]")


@cron.command("add")
@click.option("--id", "job_id", required=True, help="Unique job ID")
@click.option("--name", "-n", required=True, help="Job name")
@click.option("--cron", "cron_expr", help="Cron expression (e.g., '0 9 * * *')")
@click.option("--interval", help="Interval in seconds")
@click.option("--at", "run_at", help="One-time run at (ISO format)")
@click.option("--prompt", "-p", help="Claude prompt to execute")
@click.option("--script", "-s", help="Script command to execute")
@click.option("--webhook", "-w", help="Webhook URL to call")
@click.option("--notify", multiple=True, help="Notification channels (can be repeated)")
@click.pass_context
def cron_add(
    ctx: click.Context,
    job_id: str,
    name: str,
    cron_expr: str | None,
    interval: str | None,
    run_at: str | None,
    prompt: str | None,
    script: str | None,
    webhook: str | None,
    notify: tuple,
) -> None:
    """Add a new scheduled job."""
    config: CronAgentConfig = ctx.obj["config"]

    # Validate schedule
    schedule_count = sum(bool(x) for x in [cron_expr, interval, run_at])
    if schedule_count == 0:
        console.print("[red]Error: Must specify one of --cron, --interval, or --at[/red]")
        raise SystemExit(1)
    if schedule_count > 1:
        console.print("[red]Error: Specify only one schedule type[/red]")
        raise SystemExit(1)

    # Validate execution
    exec_count = sum(bool(x) for x in [prompt, script, webhook])
    if exec_count == 0:
        console.print("[red]Error: Must specify one of --prompt, --script, or --webhook[/red]")
        raise SystemExit(1)
    if exec_count > 1:
        console.print("[red]Error: Specify only one execution type[/red]")
        raise SystemExit(1)

    asyncio.run(_add_job(
        config, job_id, name,
        cron_expr, interval, run_at,
        prompt, script, webhook,
        list(notify),
    ))


async def _add_job(
    config: CronAgentConfig,
    job_id: str,
    name: str,
    cron_expr: str | None,
    interval: str | None,
    run_at: str | None,
    prompt: str | None,
    script: str | None,
    webhook: str | None,
    notify: list[str],
) -> None:
    """Add a job to the store."""
    from cronagent.cron.job import (
        ClaudePromptExecution,
        CronSchedule,
        IntervalSchedule,
        JobDefinition,
        NotificationConfig,
        OneTimeSchedule,
        RetryConfig,
        ScriptExecution,
        WebhookExecution,
    )
    from cronagent.cron.store import JobStore
    from cronagent.storage.database import Database

    try:
        db = Database.from_config(config.memory)
        await db.initialize()
        store = JobStore(db)

        # Build schedule
        if cron_expr:
            schedule = CronSchedule(expression=cron_expr)
        elif interval:
            schedule = IntervalSchedule(seconds=int(interval))
        else:
            schedule = OneTimeSchedule(run_at=datetime.fromisoformat(run_at))

        # Build execution
        if prompt:
            execution = ClaudePromptExecution(prompt=prompt)
        elif script:
            execution = ScriptExecution(command=script)
        else:
            execution = WebhookExecution(url=webhook)

        # Build notification config
        notification_config = NotificationConfig(
            on_failure=True,
            on_success=False,
            channels=notify if notify else None,
        )

        # Create job definition
        job = JobDefinition(
            id=job_id,
            name=name,
            schedule=schedule,
            execution=execution,
            retry=RetryConfig(),
            notifications=notification_config,
        )

        # Save to store
        await store.create_job(job)

        console.print(f"[green]Job '{name}' ({job_id}) created successfully![/green]")

        # Show schedule info
        if cron_expr:
            console.print(f"  Schedule: {cron_expr}")
        elif interval:
            console.print(f"  Interval: every {interval} seconds")
        else:
            console.print(f"  Runs at: {run_at}")

        await db.close()

    except Exception as e:
        console.print(f"[red]Error creating job: {e}[/red]")
        raise SystemExit(1)


@cron.command("remove")
@click.argument("job_id")
@click.option("--force", "-f", is_flag=True, help="Skip confirmation")
@click.pass_context
def cron_remove(ctx: click.Context, job_id: str, force: bool) -> None:
    """Remove a scheduled job."""
    config: CronAgentConfig = ctx.obj["config"]

    if not force:
        if not click.confirm(f"Remove job '{job_id}'?"):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    asyncio.run(_remove_job(config, job_id))


async def _remove_job(config: CronAgentConfig, job_id: str) -> None:
    """Remove a job from the store."""
    from cronagent.cron.store import JobStore
    from cronagent.storage.database import Database

    try:
        db = Database.from_config(config.memory)
        await db.initialize()
        store = JobStore(db)

        job = await store.get_job(job_id)
        if not job:
            console.print(f"[red]Job '{job_id}' not found.[/red]")
            raise SystemExit(1)

        await store.delete_job(job_id)
        console.print(f"[green]Job '{job_id}' removed.[/green]")

        await db.close()

    except Exception as e:
        console.print(f"[red]Error removing job: {e}[/red]")
        raise SystemExit(1)


@cron.command("trigger")
@click.argument("job_id")
@click.pass_context
def cron_trigger(ctx: click.Context, job_id: str) -> None:
    """Manually trigger a job to run now."""
    config: CronAgentConfig = ctx.obj["config"]
    asyncio.run(_trigger_job(config, job_id))


async def _trigger_job(config: CronAgentConfig, job_id: str) -> None:
    """Trigger a job immediately."""
    from cronagent.bus.events import EventBus
    from cronagent.cron.scheduler import create_scheduler

    try:
        event_bus = EventBus()

        # Create minimal scheduler to trigger job
        scheduler = await create_scheduler(
            config=config.scheduler,
            event_bus=event_bus,
        )
        await scheduler.start()

        await scheduler.trigger_job(job_id)
        console.print(f"[green]Job '{job_id}' triggered.[/green]")

        await scheduler.shutdown()

    except Exception as e:
        console.print(f"[red]Error triggering job: {e}[/red]")
        raise SystemExit(1)


@cron.command("pause")
@click.argument("job_id")
@click.pass_context
def cron_pause(ctx: click.Context, job_id: str) -> None:
    """Pause a scheduled job."""
    config: CronAgentConfig = ctx.obj["config"]
    asyncio.run(_pause_job(config, job_id, pause=True))


@cron.command("resume")
@click.argument("job_id")
@click.pass_context
def cron_resume(ctx: click.Context, job_id: str) -> None:
    """Resume a paused job."""
    config: CronAgentConfig = ctx.obj["config"]
    asyncio.run(_pause_job(config, job_id, pause=False))


async def _pause_job(config: CronAgentConfig, job_id: str, pause: bool) -> None:
    """Pause or resume a job."""
    from cronagent.cron.store import JobStore
    from cronagent.storage.database import Database

    try:
        db = Database.from_config(config.memory)
        await db.initialize()
        store = JobStore(db)

        job = await store.get_job(job_id)
        if not job:
            console.print(f"[red]Job '{job_id}' not found.[/red]")
            raise SystemExit(1)

        new_status = "paused" if pause else "active"
        job.status = new_status
        await store.update_job(job)

        action = "paused" if pause else "resumed"
        console.print(f"[green]Job '{job_id}' {action}.[/green]")

        await db.close()

    except Exception as e:
        action = "pausing" if pause else "resuming"
        console.print(f"[red]Error {action} job: {e}[/red]")
        raise SystemExit(1)


@cron.command("show")
@click.argument("job_id")
@click.pass_context
def cron_show(ctx: click.Context, job_id: str) -> None:
    """Show details of a specific job."""
    config: CronAgentConfig = ctx.obj["config"]
    asyncio.run(_show_job(config, job_id))


async def _show_job(config: CronAgentConfig, job_id: str) -> None:
    """Show job details."""
    from cronagent.cron.store import JobStore
    from cronagent.storage.database import Database

    try:
        db = Database.from_config(config.memory)
        await db.initialize()
        store = JobStore(db)

        job = await store.get_job(job_id)
        if not job:
            console.print(f"[red]Job '{job_id}' not found.[/red]")
            raise SystemExit(1)

        # Display job details
        console.print(Panel(f"[bold]{job.name}[/bold]", title=f"Job: {job.id}"))

        console.print(f"\n[bold]Status:[/bold] {job.status}")

        # Schedule
        console.print(f"\n[bold]Schedule:[/bold]")
        schedule = job.schedule
        if hasattr(schedule, "expression"):
            console.print(f"  Type: Cron")
            console.print(f"  Expression: {schedule.expression}")
        elif hasattr(schedule, "seconds"):
            console.print(f"  Type: Interval")
            console.print(f"  Every: {schedule.seconds} seconds")
        elif hasattr(schedule, "run_at"):
            console.print(f"  Type: One-time")
            console.print(f"  Run at: {schedule.run_at}")

        # Execution
        console.print(f"\n[bold]Execution:[/bold]")
        execution = job.execution
        if hasattr(execution, "prompt"):
            console.print(f"  Type: Claude Prompt")
            console.print(f"  Prompt: {execution.prompt[:100]}...")
        elif hasattr(execution, "command"):
            console.print(f"  Type: Script")
            console.print(f"  Command: {execution.command}")
        elif hasattr(execution, "url"):
            console.print(f"  Type: Webhook")
            console.print(f"  URL: {execution.url}")

        # Retry config
        console.print(f"\n[bold]Retry:[/bold]")
        console.print(f"  Max Attempts: {job.retry.max_attempts}")
        console.print(f"  Strategy: {job.retry.strategy}")

        # Run history
        stats = await store.get_job_stats(job_id)
        recent_runs = await store.get_run_history(job_id, limit=5)

        console.print(f"\n[bold]Statistics:[/bold]")
        console.print(f"  Total Runs: {stats.get('total', 0)}")
        console.print(f"  Successful: {stats.get('success', 0)}")
        console.print(f"  Failed: {stats.get('failed', 0)}")

        if recent_runs:
            console.print(f"\n[bold]Recent Runs:[/bold]")
            for run in recent_runs:
                status_icon = "[green]OK[/green]" if run.status == "success" else "[red]FAIL[/red]"
                started = run.started_at.strftime("%m/%d %H:%M") if run.started_at else "-"
                duration = f"{run.duration_ms / 1000:.1f}s" if run.duration_ms else "-"
                console.print(f"  {status_icon} {started} ({duration})")

        await db.close()

    except Exception as e:
        console.print(f"[red]Error showing job: {e}[/red]")
        raise SystemExit(1)


@cron.command("history")
@click.argument("job_id")
@click.option("--limit", "-l", default=20, help="Number of runs to show")
@click.pass_context
def cron_history(ctx: click.Context, job_id: str, limit: int) -> None:
    """Show run history for a job."""
    config: CronAgentConfig = ctx.obj["config"]
    asyncio.run(_show_history(config, job_id, limit))


async def _show_history(config: CronAgentConfig, job_id: str, limit: int) -> None:
    """Show job run history."""
    from cronagent.cron.store import JobStore
    from cronagent.storage.database import Database

    try:
        db = Database.from_config(config.memory)
        await db.initialize()
        store = JobStore(db)

        runs = await store.get_run_history(job_id, limit=limit)

        if not runs:
            console.print(f"[yellow]No runs found for job '{job_id}'.[/yellow]")
            return

        table = Table(title=f"Run History: {job_id}")
        table.add_column("Run ID", style="dim")
        table.add_column("Started")
        table.add_column("Status")
        table.add_column("Duration")
        table.add_column("Attempt")
        table.add_column("Error")

        for run in runs:
            status_str = run.status
            if run.status == "success":
                status_str = "[green]success[/green]"
            elif run.status == "failed":
                status_str = "[red]failed[/red]"
            elif run.status == "running":
                status_str = "[yellow]running[/yellow]"

            started = run.started_at.strftime("%Y-%m-%d %H:%M:%S") if run.started_at else "-"
            duration = f"{run.duration_ms / 1000:.2f}s" if run.duration_ms else "-"
            error = (run.error or "")[:40] + "..." if run.error and len(run.error) > 40 else (run.error or "-")

            table.add_row(
                run.id[:8],
                started,
                status_str,
                duration,
                str(run.attempt),
                error,
            )

        console.print(table)

        await db.close()

    except Exception as e:
        console.print(f"[red]Error showing history: {e}[/red]")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
