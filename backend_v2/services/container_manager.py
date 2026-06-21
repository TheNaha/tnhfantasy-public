"""
Container Lifecycle Manager
Manages Docker containers for provider workers with isolated credentials.
"""
import docker
import os
import time
import asyncio
import threading
from typing import Dict, Optional, List, Iterable, Tuple
from pathlib import Path

from config import get_worker_backend_url
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from infrastructure.providers.provider_registry import ProviderRegistry

logger = get_logger("container_manager")
_container_manager_singleton = None
_container_manager_lock = threading.Lock()
_CONTAINER_MANAGER_INIT_FAILED = False
_CONTAINER_MANAGER_INIT_RETRIES = 0
_CONTAINER_MANAGER_MAX_RETRIES = 3
try:
    DEFAULT_HEALTH_TIMEOUT_SECONDS = max(10, int(os.getenv("COMFY_CONTAINER_HEALTH_TIMEOUT_SECONDS", "180")))
except ValueError:
    DEFAULT_HEALTH_TIMEOUT_SECONDS = 180


class ContainerManager:
    """Manages provider worker containers (Docker or Podman)."""
    # Dynamically derived from ProviderRegistry at runtime
    DEFAULT_PROVIDER_TYPES = None  # Falls back to registry lookup
    
    def __init__(self, containers_dir: str = None):
        """
        Initialize container manager.
        Supports both Docker and Podman.
        
        Args:
            containers_dir: Path to provider_containers directory
        """
        if containers_dir is None:
            service_dir = Path(__file__).resolve().parent
            project_root = service_dir.parent.parent
            repo_containers_dir = project_root / "provider_containers"
            backend_local_dir = service_dir.parent / "provider_containers"
            containers_dir = repo_containers_dir if repo_containers_dir.exists() else backend_local_dir
        
        self.containers_dir = Path(containers_dir)
        
        # Try to connect to Podman first, fall back to Docker
        self.client = self._get_container_client()
        self.runtime = self._detect_runtime()
        self.running_containers: Dict[str, docker.models.containers.Container] = {}
        
        logger.info("container_runtime_detected", runtime=self.runtime)
    
    def _get_container_client(self):
        """Get Docker/Podman client with automatic detection."""
        
        last_error = None
        mounted_socket = "/run/podman/podman.sock"
        if os.path.exists(mounted_socket):
            try:
                client = docker.DockerClient(base_url=f"unix://{mounted_socket}")
                client.ping()
                logger.info("container_client_connected", method="podman_mounted")
                return client
            except Exception as e:
                last_error = e

        podman_socket = os.path.expanduser(f"unix://{os.getenv('XDG_RUNTIME_DIR', '/run/user/1000')}/podman/podman.sock")
        try:
            client = docker.DockerClient(base_url=podman_socket)
            client.ping()
            logger.info("container_client_connected", method="podman_rootless")
            return client
        except Exception as e:
            last_error = e

        try:
            client = docker.DockerClient(base_url="unix:///run/podman/podman.sock")
            client.ping()
            logger.info("container_client_connected", method="podman_rootful")
            return client
        except Exception as e:
            last_error = e

        try:
            client = docker.from_env()
            client.ping()
            logger.info("container_client_connected", method="docker")
            return client
        except Exception as e:
            last_error = e

        raise RuntimeError(
            "Could not connect to Docker or Podman. "
            "For containerized setups, mount Podman socket to /run/podman/podman.sock"
        ) from last_error
    
    def _detect_runtime(self) -> str:
        """Detect whether we're using Docker or Podman."""
        try:
            info = self.client.info()
            # Podman includes "Podman" in the server version
            if "podman" in str(info).lower():
                return "podman"
            return "docker"
        except Exception:
            return "unknown"
    
    def build_worker_image(self, provider_type: str) -> str:
        """
        Build Docker image for provider worker.
        
        Args:
            provider_type: Type of provider (modal, beam, runpod)
            
        Returns:
            Image tag
        """
        worker_dir = self.containers_dir / f"{provider_type}_worker"
        dockerfile_path = f"{provider_type}_worker/Dockerfile"
        
        if not worker_dir.exists():
            raise ValueError(f"Worker directory not found: {worker_dir}")
        
        logger.info("image_build_start", provider_type=provider_type)
        image_tag = ProviderRegistry.get_worker_image(provider_type)
        
        try:
            # Use provider_containers as build context to access shared provider_core
            # dockerfile parameter specifies the path to the Dockerfile relative to context
            image, build_logs = self.client.images.build(
                path=str(self.containers_dir),  # Build context is provider_containers/
                dockerfile=dockerfile_path,      # Path to Dockerfile within context
                tag=image_tag,
                rm=True,
                pull=True
            )
            
            # Log build progress
            for log in build_logs:
                if 'stream' in log:
                    logger.debug("image_build_progress", message=log['stream'].strip())
            
            logger.info("image_build_complete", image_tag=image_tag)
            return image_tag
        
        except docker.errors.BuildError as e:
            logger.error("image_build_failed", provider_type=provider_type, error=str(e))
            raise

    def build_worker_images(self, provider_types: Optional[Iterable[str]] = None) -> Dict[str, str]:
        """Build provider worker images and continue past individual failures."""
        image_tags: Dict[str, str] = {}
        if provider_types:
            provider_list = list(provider_types)
        else:
            provider_list = list(ProviderRegistry.get_all().keys())

        for provider_type in dict.fromkeys(provider_list):
            try:
                image_tags[provider_type] = self.build_worker_image(provider_type)
            except Exception as exc:
                logger.warning("image_build_skipped", provider_type=provider_type, error=str(exc))

        return image_tags
    
    async def start_container(
        self,
        provider_id: str,
        provider_type: str,
        port: int,
        env_vars: Optional[Dict[str, str]] = None,
        env_file: Optional[str] = None,
        rebuild: bool = False
    ):
        """Start a provider worker container."""
        logger.info("container_start_request", provider_id=provider_id, port=port)
        
        image_tag = ProviderRegistry.get_worker_image(provider_type)
        
        # Check if image exists
        image_exists = False
        try:
            self.client.images.get(image_tag)
            image_exists = True
        except docker.errors.ImageNotFound:
            pass
            
        # Build if requested or missing
        if rebuild or not image_exists:
            logger.info("image_building", image_tag=image_tag, reason="rebuild" if rebuild else "missing")
            self.build_worker_image(provider_type)
        else:
            logger.debug("image_exists", image_tag=image_tag)
        
        # Prepare environment
        environment = {
            "PROVIDER_ID": provider_id,
            "PORT": "8000",
            "BACKEND_URL": get_worker_backend_url(),
        }
        
        # Pass through download tokens from backend to worker
        import os as env_os
        if env_os.getenv("HF_TOKEN"):
            environment["HF_TOKEN"] = env_os.getenv("HF_TOKEN")
            logger.debug("token_passed", token_type="HF_TOKEN")
        
        if env_os.getenv("CIVITAI_TOKEN"):
            environment["CIVITAI_TOKEN"] = env_os.getenv("CIVITAI_TOKEN")
            logger.debug("token_passed", token_type="CIVITAI_TOKEN")
        
        if env_vars:
            environment.update(env_vars)
        
        # Container configuration
        container_name = f"comfy-provider-{provider_id}"
        
        # Check if container already exists
        try:
            old_container = self.client.containers.get(container_name)
            logger.info("container_removing_old", container_name=container_name)
            old_container.stop()
            old_container.remove()
        except docker.errors.NotFound:
            pass
        
        logger.info("container_starting", container_name=container_name, port=port)
        
        # Get host backend directory path from environment
        backend_host_path = os.getenv("HOST_BACKEND_PATH")
        if not backend_host_path:
            raise ValueError(
                f"HOST_BACKEND_PATH environment variable is not set. "
                f"Worker container for provider '{provider_id}' requires access to "
                f"backend code and models. Set HOST_BACKEND_PATH to the host path "
                f"where the backend directory is mounted."
            )
        volumes = {
            backend_host_path: {"bind": "/backend", "mode": "ro"}
        }
        
        # Use the compose-defined network name for container-to-container communication
        target_network = os.getenv("COMFY_DOCKER_NETWORK", "tnhcomfy")
        logger.debug("container_network", network=target_network)
        
        try:
            container_config = {
                "image": image_tag,
                "name": container_name,
                "ports": {"8000/tcp": port},
                "environment": environment,
                "volumes": volumes,
                "detach": True,
                "remove": False,
                "labels": {"comfy-provider": "true", "provider-id": provider_id},
                "network": target_network  # Directly join comfy-network
            }
            
            container = self.client.containers.run(**container_config)
            logger.debug("container_network_joined", network=target_network)
            
            # Wait for container to be healthy
            await self._wait_for_health(container, timeout=DEFAULT_HEALTH_TIMEOUT_SECONDS)
            
            self.running_containers[provider_id] = container
            logger.info("container_started", container_name=container_name, provider_id=provider_id)
            
            return container
        
        except Exception as e:
            logger.error("container_start_failed", provider_id=provider_id, error=str(e))
            raise
    
    def _health_probe_targets(self, container: docker.models.containers.Container) -> List[Tuple[str, str]]:
        """Build health probe targets in order of reliability for current runtime."""
        targets: List[Tuple[str, str]] = []
        seen_urls = set()

        def add_target(name: str, url: Optional[str]):
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            targets.append((name, url))

        container_name = getattr(container, "name", None)
        if container_name:
            # Primary path when backend and worker are on the same container network.
            add_target("container_dns", f"http://{container_name}:8000/health")

        container_attrs = getattr(container, "attrs", None) or {}
        if isinstance(container_attrs, dict):
            network_settings = container_attrs.get("NetworkSettings", {})
            if isinstance(network_settings, dict):
                networks = network_settings.get("Networks", {})
                if isinstance(networks, dict):
                    for net_data in networks.values():
                        if not isinstance(net_data, dict):
                            continue
                        ip_address = net_data.get("IPAddress")
                        if ip_address:
                            add_target("container_ip", f"http://{ip_address}:8000/health")

        ports = container.ports.get("8000/tcp") if isinstance(container.ports, dict) else None
        if ports and len(ports) > 0:
            host_port = ports[0].get("HostPort")
            if host_port:
                add_target("localhost", f"http://localhost:{host_port}/health")
                add_target("host_internal", f"http://host.containers.internal:{host_port}/health")

        return targets

    async def _wait_for_health(self, container: docker.models.containers.Container, timeout: int = 30):
        """Wait for container to become healthy."""
        logger.debug("container_health_check_start", container=container.name, timeout=timeout)
        start_time = time.time()
        last_error = None
        
        while time.time() - start_time < timeout:
            await asyncio.to_thread(container.reload)
            
            # Check if container is running
            if container.status != 'running':
                raise RuntimeError(f"Container {container.name} is not running: {container.status}")
            
            probe_targets = self._health_probe_targets(container)
            if not probe_targets:
                last_error = "no health probe targets available"
            else:
                for method, url in probe_targets:
                    try:
                        client = get_http_client()
                        response = await client.get(url, timeout=2.0)
                        if response.status_code == 200:
                            logger.info("container_healthy", container=container.name, method=method)
                            return
                        last_error = f"{method} health returned {response.status_code}"
                    except Exception as exc:
                        last_error = f"{method} health probe failed ({exc.__class__.__name__})"
            
            await asyncio.sleep(1)
        
        # We need to run reload in an executor to avoid blocking the event loop if it's slow
        await asyncio.to_thread(container.reload)
        timeout_message = f"Container {container.name} did not become healthy within {timeout}s"
        if last_error:
            timeout_message = f"{timeout_message}: {last_error}"
        logger.warning("container_health_timeout", container=container.name, status=container.status, error=last_error)
        raise TimeoutError(timeout_message)
    
    def stop_container(self, provider_id: str):
        """Stop a provider worker container."""
        container = self.running_containers.get(provider_id)
        if not container:
            container_name = f"comfy-provider-{provider_id}"
            try:
                container = self.client.containers.get(container_name)
            except docker.errors.NotFound:
                logger.warning("container_not_found", provider_id=provider_id)
                return
        
        logger.info("container_stopping", container=container.name, provider_id=provider_id)
        
        try:
            container.stop(timeout=10)
            container.remove()
            self.running_containers.pop(provider_id, None)
            logger.info("container_stopped", container=container.name, provider_id=provider_id)
        except Exception as e:
            logger.error("container_stop_failed", provider_id=provider_id, error=str(e))
    
    def get_container_logs(self, provider_id: str, tail: int = 100) -> str:
        """Get logs from a provider container."""
        container = self.running_containers.get(provider_id)
        if not container:
            container_name = f"comfy-provider-{provider_id}"
            try:
                container = self.client.containers.get(container_name)
            except docker.errors.NotFound:
                return f"Container for provider {provider_id} not found"
        
        try:
            return container.logs(tail=tail).decode('utf-8')
        except Exception as e:
            return f"Error getting logs: {e}"
    
    def list_containers(self) -> List[Dict]:
        """List all running provider containers."""
        containers = self.client.containers.list(
            filters={"label": "comfy-provider=true"}
        )
        
        return [
            {
                "id": c.short_id,
                "name": c.name,
                "provider_id": c.labels.get("provider-id"),
                "status": c.status,
                "ports": c.ports
            }
            for c in containers
        ]
    
    def cleanup_all(self):
        """Stop and remove all provider containers."""
        logger.info("container_cleanup_all_start", count=len(self.running_containers))
        
        for provider_id in list(self.running_containers.keys()):
            self.stop_container(provider_id)
        
        logger.info("container_cleanup_all_complete")


def get_container_manager() -> Optional[ContainerManager]:
    """Return the shared container manager singleton.
    
    Retries initialization on failure up to max retries.
    After exhausting retries, subsequent calls periodically retry.
    """
    global _container_manager_singleton, _CONTAINER_MANAGER_INIT_FAILED, _CONTAINER_MANAGER_INIT_RETRIES
    with _container_manager_lock:
        if _CONTAINER_MANAGER_INIT_FAILED:
            if _CONTAINER_MANAGER_INIT_RETRIES >= _CONTAINER_MANAGER_MAX_RETRIES:
                return None
            _CONTAINER_MANAGER_INIT_RETRIES += 1
            logger.info("container_manager_init_retry", attempt=_CONTAINER_MANAGER_INIT_RETRIES)
            _container_manager_singleton = None
            _CONTAINER_MANAGER_INIT_FAILED = False
        if _container_manager_singleton is None:
            try:
                _container_manager_singleton = ContainerManager()
                _CONTAINER_MANAGER_INIT_FAILED = False
                _CONTAINER_MANAGER_INIT_RETRIES = 0
            except Exception as exc:
                _CONTAINER_MANAGER_INIT_FAILED = True
                _CONTAINER_MANAGER_INIT_RETRIES += 1
                logger.warning(
                    "container_manager_init_failed",
                    error=str(exc),
                    retries=_CONTAINER_MANAGER_INIT_RETRIES,
                )
                return None
    return _container_manager_singleton
