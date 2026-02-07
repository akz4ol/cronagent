"""
Deployment skill for application deployment operations.

Provides tools for:
- Docker operations
- SSH deployment
- Environment management
- Health checks
"""

from __future__ import annotations

import asyncio
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


class DeploySkill(DecoratorSkill):
    """
    Deployment operations skill.

    Provides tools for deploying applications via Docker,
    SSH, and other methods.

    Config options:
        docker_host: Docker daemon host
        ssh_key_path: Path to SSH key
        default_targets: Default deployment targets
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self._docker_host = self.config.get("docker_host", "unix:///var/run/docker.sock")
        self._ssh_key_path = self.config.get("ssh_key_path", "~/.ssh/id_rsa")
        self._targets = self.config.get("default_targets", {})

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="deploy",
            description="Application deployment operations",
            version="1.0.0",
            category=SkillCategory.DEVOPS,
            tags=["docker", "deploy", "ssh", "devops"],
            requires_auth=False,
            auth_env_vars=[],
        )

    @skill_tool(
        name="deploy_docker_build",
        description="Build a Docker image",
    )
    async def docker_build(
        self,
        path: str = ".",
        tag: str = "latest",
        dockerfile: str = "Dockerfile",
        build_args: dict[str, str] = {},
    ) -> dict[str, Any]:
        """Build a Docker image."""
        # Build command
        cmd_parts = ["docker", "build", "-t", tag, "-f", dockerfile]

        for key, value in build_args.items():
            cmd_parts.extend(["--build-arg", f"{key}={value}"])

        cmd_parts.append(path)

        # Execute
        process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        return {
            "success": process.returncode == 0,
            "tag": tag,
            "stdout": stdout.decode("utf-8"),
            "stderr": stderr.decode("utf-8"),
            "exit_code": process.returncode,
        }

    @skill_tool(
        name="deploy_docker_push",
        description="Push a Docker image to registry",
        requires_confirmation=True,
    )
    async def docker_push(
        self,
        tag: str,
    ) -> dict[str, Any]:
        """Push a Docker image to registry."""
        process = await asyncio.create_subprocess_exec(
            "docker", "push", tag,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        return {
            "success": process.returncode == 0,
            "tag": tag,
            "stdout": stdout.decode("utf-8"),
            "stderr": stderr.decode("utf-8"),
        }

    @skill_tool(
        name="deploy_docker_run",
        description="Run a Docker container",
    )
    async def docker_run(
        self,
        image: str,
        name: str = "",
        ports: dict[str, str] = {},
        env: dict[str, str] = {},
        volumes: dict[str, str] = {},
        detach: bool = True,
    ) -> dict[str, Any]:
        """Run a Docker container."""
        cmd_parts = ["docker", "run"]

        if detach:
            cmd_parts.append("-d")

        if name:
            cmd_parts.extend(["--name", name])

        for host_port, container_port in ports.items():
            cmd_parts.extend(["-p", f"{host_port}:{container_port}"])

        for key, value in env.items():
            cmd_parts.extend(["-e", f"{key}={value}"])

        for host_path, container_path in volumes.items():
            cmd_parts.extend(["-v", f"{host_path}:{container_path}"])

        cmd_parts.append(image)

        process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        return {
            "success": process.returncode == 0,
            "container_id": stdout.decode("utf-8").strip() if process.returncode == 0 else None,
            "stderr": stderr.decode("utf-8"),
        }

    @skill_tool(
        name="deploy_docker_stop",
        description="Stop a Docker container",
        requires_confirmation=True,
    )
    async def docker_stop(
        self,
        container: str,
        timeout: int = 10,
    ) -> dict[str, Any]:
        """Stop a Docker container."""
        process = await asyncio.create_subprocess_exec(
            "docker", "stop", "-t", str(timeout), container,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        return {
            "success": process.returncode == 0,
            "container": container,
            "stderr": stderr.decode("utf-8"),
        }

    @skill_tool(
        name="deploy_docker_ps",
        description="List Docker containers",
    )
    async def docker_ps(
        self,
        all_containers: bool = False,
    ) -> list[dict[str, Any]]:
        """List Docker containers."""
        cmd_parts = ["docker", "ps", "--format", "{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}"]

        if all_containers:
            cmd_parts.append("-a")

        process = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        containers = []
        for line in stdout.decode("utf-8").strip().split("\n"):
            if line:
                parts = line.split("\t")
                if len(parts) >= 4:
                    containers.append({
                        "id": parts[0],
                        "image": parts[1],
                        "status": parts[2],
                        "name": parts[3],
                    })

        return containers

    @skill_tool(
        name="deploy_ssh_command",
        description="Execute a command via SSH",
        requires_confirmation=True,
    )
    async def ssh_command(
        self,
        host: str,
        command: str,
        user: str = "root",
        port: int = 22,
        key_path: str = "",
    ) -> dict[str, Any]:
        """Execute a command via SSH."""
        key_path = key_path or os.path.expanduser(self._ssh_key_path)

        ssh_cmd = [
            "ssh",
            "-i", key_path,
            "-p", str(port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=yes",
            f"{user}@{host}",
            command,
        ]

        process = await asyncio.create_subprocess_exec(
            *ssh_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        return {
            "success": process.returncode == 0,
            "host": host,
            "stdout": stdout.decode("utf-8"),
            "stderr": stderr.decode("utf-8"),
            "exit_code": process.returncode,
        }

    @skill_tool(
        name="deploy_health_check",
        description="Check application health via HTTP",
    )
    async def health_check(
        self,
        url: str,
        expected_status: int = 200,
        timeout: int = 10,
        method: str = "GET",
    ) -> dict[str, Any]:
        """Check application health via HTTP."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method,
                    url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    body = await response.text()

                    return {
                        "healthy": response.status == expected_status,
                        "status_code": response.status,
                        "expected_status": expected_status,
                        "url": url,
                        "response_body": body[:500] if body else None,
                    }

        except asyncio.TimeoutError:
            return {
                "healthy": False,
                "url": url,
                "error": f"Timeout after {timeout}s",
            }
        except Exception as e:
            return {
                "healthy": False,
                "url": url,
                "error": str(e),
            }

    @skill_tool(
        name="deploy_to_target",
        description="Deploy to a configured target",
        requires_confirmation=True,
        is_destructive=True,
    )
    async def deploy_to_target(
        self,
        target: str,
        version: str = "latest",
    ) -> dict[str, Any]:
        """Deploy to a configured target."""
        if target not in self._targets:
            return {
                "success": False,
                "error": f"Unknown target: {target}. Available: {list(self._targets.keys())}",
            }

        target_config = self._targets[target]
        target_type = target_config.get("type", "docker")

        if target_type == "docker":
            # Docker deployment
            image = target_config.get("image", "")
            host = target_config.get("host", "")

            if not image or not host:
                return {
                    "success": False,
                    "error": "Docker target requires 'image' and 'host' config",
                }

            # Tag with version
            full_image = f"{image}:{version}"

            # Deploy via SSH
            deploy_cmd = target_config.get("deploy_command", f"docker pull {full_image} && docker-compose up -d")

            result = await self.ssh_command(
                host=host,
                command=deploy_cmd,
                user=target_config.get("user", "root"),
            )

            return {
                "success": result["success"],
                "target": target,
                "version": version,
                "output": result.get("stdout", ""),
                "error": result.get("stderr", ""),
            }

        return {
            "success": False,
            "error": f"Unknown target type: {target_type}",
        }

    @skill_tool(
        name="deploy_rollback",
        description="Rollback to a previous version",
        requires_confirmation=True,
        is_destructive=True,
    )
    async def rollback(
        self,
        target: str,
        version: str,
    ) -> dict[str, Any]:
        """Rollback to a previous version."""
        # Rollback is essentially a deploy to a specific version
        return await self.deploy_to_target(target, version)
