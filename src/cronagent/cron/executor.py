"""
Task executor for running scheduled jobs.

Handles:
- Claude prompt execution
- Shell script execution
- Webhook calls
- Python function execution
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import aiohttp

from cronagent.bus.events import EventBus, Events
from cronagent.cron.job import (
    ClaudePromptExecution,
    ExecutionType,
    JobDefinition,
    JobRun,
    JobStatus,
    PythonExecution,
    ScriptExecution,
    WebhookExecution,
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result from task execution."""

    status: JobStatus
    output: str | None = None
    error: str | None = None
    cost_usd: float | None = None
    metadata: dict[str, Any] | None = None


class BaseExecutor(ABC):
    """Base class for task executors."""

    @abstractmethod
    async def execute(
        self,
        job: JobDefinition,
        run: JobRun,
    ) -> ExecutionResult:
        """Execute the job and return result."""
        pass


class ClaudeExecutor(BaseExecutor):
    """
    Execute jobs via Claude agent.

    Uses the AgentLoop to execute prompts with full tool access.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus

    async def execute(
        self,
        job: JobDefinition,
        run: JobRun,
    ) -> ExecutionResult:
        """Execute Claude prompt job."""
        if not isinstance(job.execution, ClaudePromptExecution):
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error="Invalid execution config for Claude job",
            )

        config = job.execution

        try:
            # Import here to avoid circular imports
            from cronagent.agent import AgentLoop, AgentLoopConfig

            # Build agent config
            agent_config = AgentLoopConfig(
                system_prompt=config.system_prompt or "",
                max_turns=config.max_turns,
                working_directory=config.project_path or ".",
                model=config.model,
                env=config.environment,
            )

            if config.allowed_tools:
                agent_config.allowed_tools = config.allowed_tools

            # Create and execute agent
            loop = AgentLoop(agent_config, event_bus=self.event_bus)

            output_parts = []
            cost_usd = 0.0
            is_error = False

            async for event in loop.execute(config.prompt):
                if event.type == "text":
                    output_parts.append(event.content)
                elif event.type == "result":
                    cost_usd = event.metadata.get("cost_usd", 0)
                    is_error = event.metadata.get("is_error", False)
                elif event.type == "error":
                    return ExecutionResult(
                        status=JobStatus.FAILURE,
                        error=event.content,
                        cost_usd=cost_usd,
                    )

            output = "".join(output_parts)

            if is_error:
                return ExecutionResult(
                    status=JobStatus.FAILURE,
                    output=output,
                    error="Agent execution failed",
                    cost_usd=cost_usd,
                )

            return ExecutionResult(
                status=JobStatus.SUCCESS,
                output=output,
                cost_usd=cost_usd,
            )

        except Exception as e:
            logger.error(f"Claude execution error: {e}", exc_info=True)
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error=str(e),
            )


class ScriptExecutor(BaseExecutor):
    """Execute shell scripts."""

    async def execute(
        self,
        job: JobDefinition,
        run: JobRun,
    ) -> ExecutionResult:
        """Execute script job."""
        if not isinstance(job.execution, ScriptExecution):
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error="Invalid execution config for script job",
            )

        config = job.execution

        try:
            # Prepare environment
            env = os.environ.copy()
            env.update(config.environment)

            # Add job context to environment
            env["CRONAGENT_JOB_ID"] = job.id
            env["CRONAGENT_RUN_ID"] = run.run_id
            env["CRONAGENT_JOB_NAME"] = job.name

            # Execute command
            process = await asyncio.create_subprocess_shell(
                config.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=config.working_directory,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=config.timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ExecutionResult(
                    status=JobStatus.TIMEOUT,
                    error=f"Script timed out after {config.timeout}s",
                )

            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            if process.returncode == 0:
                return ExecutionResult(
                    status=JobStatus.SUCCESS,
                    output=stdout_str,
                    metadata={"stderr": stderr_str} if stderr_str else None,
                )
            else:
                return ExecutionResult(
                    status=JobStatus.FAILURE,
                    output=stdout_str,
                    error=stderr_str or f"Exit code: {process.returncode}",
                )

        except Exception as e:
            logger.error(f"Script execution error: {e}", exc_info=True)
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error=str(e),
            )


class WebhookExecutor(BaseExecutor):
    """Execute HTTP webhook calls."""

    async def execute(
        self,
        job: JobDefinition,
        run: JobRun,
    ) -> ExecutionResult:
        """Execute webhook job."""
        if not isinstance(job.execution, WebhookExecution):
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error="Invalid execution config for webhook job",
            )

        config = job.execution

        try:
            # Prepare headers
            headers = dict(config.headers)
            headers.setdefault("User-Agent", "CronAgent/1.0")
            headers.setdefault("X-CronAgent-Job-ID", job.id)
            headers.setdefault("X-CronAgent-Run-ID", run.run_id)

            # Prepare body
            body = config.body
            if isinstance(body, dict):
                body = json.dumps(body)
                headers.setdefault("Content-Type", "application/json")

            # Make request
            timeout = aiohttp.ClientTimeout(total=config.timeout)
            connector = aiohttp.TCPConnector(ssl=config.verify_ssl)

            async with aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
            ) as session:
                async with session.request(
                    method=config.method,
                    url=config.url,
                    headers=headers,
                    data=body,
                ) as response:
                    response_text = await response.text()

                    if response.status >= 200 and response.status < 300:
                        return ExecutionResult(
                            status=JobStatus.SUCCESS,
                            output=response_text,
                            metadata={
                                "status_code": response.status,
                                "headers": dict(response.headers),
                            },
                        )
                    else:
                        return ExecutionResult(
                            status=JobStatus.FAILURE,
                            output=response_text,
                            error=f"HTTP {response.status}",
                            metadata={"status_code": response.status},
                        )

        except asyncio.TimeoutError:
            return ExecutionResult(
                status=JobStatus.TIMEOUT,
                error=f"Webhook timed out after {config.timeout}s",
            )
        except aiohttp.ClientError as e:
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error=f"HTTP error: {e}",
            )
        except Exception as e:
            logger.error(f"Webhook execution error: {e}", exc_info=True)
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error=str(e),
            )


class PythonExecutor(BaseExecutor):
    """Execute Python functions."""

    async def execute(
        self,
        job: JobDefinition,
        run: JobRun,
    ) -> ExecutionResult:
        """Execute Python function job."""
        if not isinstance(job.execution, PythonExecution):
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error="Invalid execution config for Python job",
            )

        config = job.execution

        try:
            # Import module
            module = importlib.import_module(config.module)

            # Get function
            func = getattr(module, config.function)
            if not callable(func):
                return ExecutionResult(
                    status=JobStatus.FAILURE,
                    error=f"{config.module}.{config.function} is not callable",
                )

            # Execute function
            # Add job context to kwargs
            kwargs = dict(config.kwargs)
            kwargs["_job_context"] = {
                "job_id": job.id,
                "run_id": run.run_id,
                "job_name": job.name,
                "attempt": run.attempt,
            }

            # Handle async functions
            if asyncio.iscoroutinefunction(func):
                result = await func(*config.args, **kwargs)
            else:
                # Run sync function in thread pool
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: func(*config.args, **kwargs),
                )

            # Convert result to string
            if isinstance(result, str):
                output = result
            elif result is None:
                output = "Function completed successfully"
            else:
                output = json.dumps(result, default=str)

            return ExecutionResult(
                status=JobStatus.SUCCESS,
                output=output,
            )

        except ImportError as e:
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error=f"Failed to import {config.module}: {e}",
            )
        except AttributeError as e:
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error=f"Function {config.function} not found in {config.module}: {e}",
            )
        except Exception as e:
            logger.error(f"Python execution error: {e}", exc_info=True)
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error=str(e),
            )


class TaskExecutor:
    """
    Main task executor that delegates to specific executors.

    Usage:
        executor = TaskExecutor(event_bus=bus)

        result = await executor.execute(job, run)
        if result.status == JobStatus.SUCCESS:
            print(f"Output: {result.output}")
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus

        # Initialize executors
        self._executors: dict[ExecutionType, BaseExecutor] = {
            ExecutionType.CLAUDE_PROMPT: ClaudeExecutor(event_bus),
            ExecutionType.SCRIPT: ScriptExecutor(),
            ExecutionType.WEBHOOK: WebhookExecutor(),
            ExecutionType.PYTHON: PythonExecutor(),
        }

    def register_executor(
        self,
        execution_type: ExecutionType,
        executor: BaseExecutor,
    ) -> None:
        """Register a custom executor for an execution type."""
        self._executors[execution_type] = executor

    async def execute(
        self,
        job: JobDefinition,
        run: JobRun,
    ) -> ExecutionResult:
        """
        Execute a job.

        Args:
            job: Job definition
            run: Job run record

        Returns:
            Execution result
        """
        executor = self._executors.get(job.execution_type)

        if not executor:
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error=f"No executor for type: {job.execution_type}",
            )

        logger.info(f"Executing job {job.id} ({job.name}), run {run.run_id}")

        # Emit start event
        if self.event_bus:
            await self.event_bus.emit(
                Events.JOB_EXECUTING,
                {
                    "job_id": job.id,
                    "run_id": run.run_id,
                    "execution_type": job.execution_type.value,
                },
            )

        try:
            result = await executor.execute(job, run)

            logger.info(
                f"Job {job.id} run {run.run_id} completed: {result.status.value}"
            )

            return result

        except Exception as e:
            logger.error(f"Executor error for job {job.id}: {e}", exc_info=True)
            return ExecutionResult(
                status=JobStatus.FAILURE,
                error=f"Executor error: {e}",
            )


async def execute_with_retry(
    executor: TaskExecutor,
    job: JobDefinition,
    run: JobRun,
    on_retry: callable | None = None,
) -> ExecutionResult:
    """
    Execute a job with retry logic.

    Args:
        executor: Task executor
        job: Job definition
        run: Job run record
        on_retry: Callback for retry attempts

    Returns:
        Final execution result
    """
    result = await executor.execute(job, run)

    # Check if should retry
    while (
        result.status in job.retry.retry_on
        and run.attempt < job.retry.max_attempts
    ):
        # Calculate delay
        delay = job.retry.get_delay(run.attempt)

        logger.info(
            f"Job {job.id} failed (attempt {run.attempt}/{job.retry.max_attempts}), "
            f"retrying in {delay}s"
        )

        # Notify retry
        if on_retry:
            await on_retry(run.attempt, delay, result)

        # Wait before retry
        await asyncio.sleep(delay)

        # Increment attempt
        run.attempt += 1

        # Retry execution
        result = await executor.execute(job, run)

    return result
