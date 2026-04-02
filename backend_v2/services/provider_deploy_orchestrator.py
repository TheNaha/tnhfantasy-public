from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from infrastructure.logging import provider_logger

logger = provider_logger()


class ProviderDeployOrchestrator:
    """Run provider deploy commands in a dedicated ephemeral container."""

    def __init__(self, container_manager: Any):
        self.container_manager = container_manager

    def start_attempt_container(
        self,
        *,
        provider_id: str,
        provider_type: str,
        attempt_id: str,
        env_vars: Dict[str, str],
    ) -> Any:
        image_tag = f"comfy-provider-{provider_type}:latest"
        self._ensure_image(provider_type, image_tag)

        container_name = f"comfy-provider-deploy-{provider_id}-{attempt_id[:8]}"
        volumes = self._build_volumes()

        logger.info(
            "provider_deploy_container_start",
            provider_id=provider_id,
            provider_type=provider_type,
            container_name=container_name,
        )

        return self.container_manager.client.containers.run(
            image=image_tag,
            name=container_name,
            command=["sleep", "1800"],
            environment=env_vars,
            volumes=volumes,
            detach=True,
            remove=False,
            labels={
                "comfy-provider-deploy": "true",
                "provider-id": provider_id,
                "provider-type": provider_type,
                "deploy-attempt-id": attempt_id,
            },
            network="comfy-network",
        )

    def run_step(self, container: Any, command: List[str]) -> Any:
        logger.info(
            "provider_deploy_step_exec",
            container_name=getattr(container, "name", None),
            command=" ".join(command),
        )
        return container.exec_run(cmd=command, stream=False, demux=True)

    def cleanup_container(self, container: Optional[Any]) -> None:
        if container is None:
            return

        try:
            container.stop(timeout=2)
        except Exception:
            pass

        try:
            container.remove(force=True)
        except Exception as exc:
            logger.warning(
                "provider_deploy_container_cleanup_failed",
                container_name=getattr(container, "name", None),
                error=str(exc),
            )

    def _ensure_image(self, provider_type: str, image_tag: str) -> None:
        images_client = getattr(self.container_manager.client, "images", None)
        if images_client is None:
            return

        try:
            images_client.get(image_tag)
        except Exception:
            self.container_manager.build_worker_image(provider_type)

    def _build_volumes(self) -> Dict[str, Dict[str, str]]:
        volumes: Dict[str, Dict[str, str]] = {}

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
