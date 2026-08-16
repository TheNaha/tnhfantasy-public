from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from infrastructure.logging import provider_logger
from infrastructure.providers.provider_registry import ProviderRegistry

logger = provider_logger()

# Modal image builds can legitimately exceed 5 minutes on cold dependency paths.
DEFAULT_STEP_TIMEOUT_SECONDS = 3600.0
DEFAULT_FORCE_REBUILD_IMAGE = True


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_step_timeout_seconds(raw_timeout: float | None) -> float:
    raw_value: Any = raw_timeout
    if raw_value is None:
        raw_value = os.getenv("COMFY_PROVIDER_DEPLOY_STEP_TIMEOUT_SECONDS", str(DEFAULT_STEP_TIMEOUT_SECONDS))

    try:
        parsed = float(raw_value)
    except (TypeError, ValueError):
        parsed = DEFAULT_STEP_TIMEOUT_SECONDS

    return max(parsed, 1.0)


class ProviderDeployStepTimeoutError(TimeoutError):
    """Raised when a deploy step does not finish within configured timeout."""


class ProviderDeployStepExecutionError(RuntimeError):
    """Raised when a deploy step crashes before producing an exec result."""


class ProviderDeployOrchestrator:
    """Run provider deploy commands in a dedicated ephemeral container."""

    def __init__(self, container_manager: Any, *, step_timeout_seconds: float | None = None):
        self.container_manager = container_manager
        self.step_timeout_seconds = _resolve_step_timeout_seconds(step_timeout_seconds)
        self.force_rebuild_image = _env_bool(
            "COMFY_PROVIDER_DEPLOY_REBUILD_IMAGE",
            DEFAULT_FORCE_REBUILD_IMAGE,
        )

    def start_attempt_container(
        self,
        *,
        provider_id: str,
        provider_type: str,
        attempt_id: str,
        env_vars: dict[str, str],
    ) -> Any:
        image_tag = ProviderRegistry.get_worker_image(provider_type)
        self._ensure_image(provider_type)

        container_name = f"tnhcomfy-deploy-{provider_id}-{attempt_id[:8]}"
        volumes = self._build_volumes()

        logger.info(
            "provider_deploy_container_start",
            provider_id=provider_id,
            provider_type=provider_type,
            container_name=container_name,
        )

        container_sleep_seconds = max(int(self.step_timeout_seconds) + 300, 3600)
        return self.container_manager.client.containers.run(
            image=image_tag,
            name=container_name,
            command=["sleep", str(container_sleep_seconds)],
            environment=env_vars,
            volumes=volumes,
            detach=True,
            remove=False,
            labels={
                "tnhcomfy-deploy": "true",
                "provider-id": provider_id,
                "provider-type": provider_type,
                "deploy-attempt-id": attempt_id,
            },
            network="tnhcomfy",
        )

    async def run_step(self, container: Any, command: list[str], *, timeout_seconds: float | None = None) -> Any:
        step_timeout = self.step_timeout_seconds if timeout_seconds is None else max(float(timeout_seconds), 1.0)
        logger.info(
            "provider_deploy_step_exec",
            container_name=getattr(container, "name", None),
            command=" ".join(command),
            timeout_seconds=step_timeout,
        )

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    container.exec_run,
                    cmd=command,
                    stream=False,
                    demux=True,
                ),
                timeout=step_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise ProviderDeployStepTimeoutError(
                f"Deploy step timed out after {step_timeout:.0f}s"
            ) from exc
        except Exception as exc:
            raise ProviderDeployStepExecutionError("Deploy step execution crashed") from exc

    def cleanup_container(self, container: Any | None) -> None:
        if container is None:
            return

        try:
            container.stop(timeout=2)
        except Exception as exc:
            logger.debug("deploy_container_stop_failed", error=str(exc))

        try:
            container.remove(force=True)
        except Exception as exc:
            logger.warning(
                "provider_deploy_container_cleanup_failed",
                container_name=getattr(container, "name", None),
                error=str(exc),
            )

    def _ensure_image(self, provider_type: str) -> None:
        if self.force_rebuild_image:
            self.container_manager.build_worker_image(provider_type)
            return

        images_client = getattr(self.container_manager.client, "images", None)
        if images_client is None:
            return

        image_tag = ProviderRegistry.get_worker_image(provider_type)
        try:
            images_client.get(image_tag)
        except Exception:
            self.container_manager.build_worker_image(provider_type)

    def _build_volumes(self) -> dict[str, dict[str, str]]:
        volumes: dict[str, dict[str, str]] = {}

        backend_host_path = os.getenv("HOST_BACKEND_PATH")
        if backend_host_path:
            volumes[backend_host_path] = {"bind": "/backend", "mode": "ro"}

            repo_root = Path(backend_host_path).resolve().parent
            provider_containers_path = repo_root / "provider_containers"
            if provider_containers_path.exists():
                volumes[str(provider_containers_path)] = {
                    "bind": "/deploy-src/provider_containers",
                    "mode": "ro",
                }

        explicit_provider_path = os.getenv("HOST_PROVIDER_CONTAINERS_PATH")
        if explicit_provider_path:
            volumes[explicit_provider_path] = {
                "bind": "/deploy-src/provider_containers",
                "mode": "ro",
            }

        return volumes
