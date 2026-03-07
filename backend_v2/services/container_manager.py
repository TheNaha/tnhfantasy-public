"""
Container Lifecycle Manager
Manages Docker containers for provider workers with isolated credentials.
"""
import docker
import os
import requests
import time
from typing import Dict, Optional, List
from pathlib import Path

from config import get_worker_backend_url
from infrastructure.logging import get_logger

logger = get_logger("container_manager")


class ContainerManager:
    """Manages provider worker containers (Docker or Podman)."""
    
    def __init__(self, containers_dir: str = None):
        """
        Initialize container manager.
        Supports both Docker and Podman.
        
        Args:
            containers_dir: Path to provider_containers directory
        """
        if containers_dir is None:
            containers_dir = os.path.join(
                os.path.dirname(__file__),
                "..",
                "provider_containers"
            )
        
        self.containers_dir = Path(containers_dir)
        
        # Try to connect to Podman first, fall back to Docker
        self.client = self._get_container_client()
        self.runtime = self._detect_runtime()
        self.running_containers: Dict[str, docker.models.containers.Container] = {}
        
        logger.info("container_runtime_detected", runtime=self.runtime)
    
    def _get_container_client(self):
        """Get Docker/Podman client with automatic detection."""
        
        # Try mounted Podman socket first (for containerized backend)
        mounted_socket = "/run/podman/podman.sock"
        if os.path.exists(mounted_socket):
            try:
                logger.debug("container_client_trying", socket=mounted_socket)
                client = docker.DockerClient(base_url=f"unix://{mounted_socket}")
                client.ping()
                logger.info("container_client_connected", method="podman_mounted")
                return client
            except Exception as e:
                logger.debug("container_client_failed", method="podman_mounted", error=str(e))
        
        # Try Podman socket (rootless)
        podman_socket = os.path.expanduser(f"unix://{os.getenv('XDG_RUNTIME_DIR', '/run/user/1000')}/podman/podman.sock")
        
        try:
            logger.debug("container_client_trying", method="podman_rootless", socket=podman_socket)
            client = docker.DockerClient(base_url=podman_socket)
            client.ping()
            logger.info("container_client_connected", method="podman_rootless")
            return client
        except Exception as e:
            logger.debug("container_client_failed", method="podman_rootless", error=str(e))
        
        # Try Podman socket (rootful)
        try:
            logger.debug("container_client_trying", method="podman_rootful")
            client = docker.DockerClient(base_url="unix:///run/podman/podman.sock")
            client.ping()
            logger.info("container_client_connected", method="podman_rootful")
            return client
        except Exception as e:
            logger.debug("container_client_failed", method="podman_rootful", error=str(e))
        
        # Fall back to Docker
        try:
            logger.debug("container_client_trying", method="docker")
            client = docker.from_env()
            logger.info("container_client_connected", method="docker")
            return client
        except Exception as e:
            logger.error("container_client_failed_all", error=str(e))
            raise RuntimeError(
                f"Could not connect to Docker or Podman. \n"
                f"For Podman, run: systemctl --user enable --now podman.socket\n"
                f"For containerized setups, ensure Podman socket is mounted to /run/podman/podman.sock\n"
                f"Error: {e}"
            )
    
    def _detect_runtime(self) -> str:
        """Detect whether we're using Docker or Podman."""
        try:
            info = self.client.info()
            # Podman includes "Podman" in the server version
            if "podman" in str(info).lower():
                return "podman"
            return "docker"
        except:
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
        image_tag = f"comfy-provider-{provider_type}:latest"
        
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
    
    def start_container(
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
        
        image_tag = f"comfy-provider-{provider_type}:latest"
        
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
            logger.warning("backend_path_missing", provider_id=provider_id)
            volumes = {}
        else:
            volumes = {
                backend_host_path: {"bind": "/backend", "mode": "ro"}
            }
        
        # Always use comfy-network for container-to-container communication
        target_network = "comfy-network"
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
            self._wait_for_health(container, timeout=30)
            
            self.running_containers[provider_id] = container
            logger.info("container_started", container_name=container_name, provider_id=provider_id)
            
            return container
        
        except Exception as e:
            logger.error("container_start_failed", provider_id=provider_id, error=str(e))
            raise
    
    def _wait_for_health(self, container: docker.models.containers.Container, timeout: int = 30):
        """Wait for container to become healthy."""
        logger.debug("container_health_check_start", container=container.name, timeout=timeout)
        start_time = time.time()
        last_error = None
        
        while time.time() - start_time < timeout:
            container.reload()
            
            # Check if container is running
            if container.status != 'running':
                raise RuntimeError(f"Container {container.name} is not running: {container.status}")
            
            # Try health check endpoint
            # Note: This may fail if backend is containerized since port is on host
            try:
                # Get the host port
                ports = container.ports.get('8000/tcp')
                if ports and len(ports) > 0:
                    host_port = ports[0]['HostPort']
                    
                    # Try localhost first (works if backend is on host)
                    try:
                        response = requests.get(f"http://localhost:{host_port}/health", timeout=2)
                        if response.status_code == 200:
                            logger.info("container_healthy", container=container.name, method="localhost")
                            return
                        last_error = f"localhost health returned {response.status_code}"
                    except:
                        last_error = "localhost health probe failed"
                    
                    # Try host.containers.internal (Podman/Docker from container)
                    try:
                        response = requests.get(f"http://host.containers.internal:{host_port}/health", timeout=2)
                        if response.status_code == 200:
                            logger.info("container_healthy", container=container.name, method="host_internal")
                            return
                        last_error = f"host_internal health returned {response.status_code}"
                    except:
                        last_error = "host_internal health probe failed"
            except Exception as e:
                last_error = str(e)
            
            time.sleep(1)
        
        container.reload()
        timeout_message = f"Container {container.name} did not become healthy within {timeout}s"
        if last_error:
            timeout_message = f"{timeout_message}: {last_error}"
        logger.warning("container_health_timeout", container=container.name, status=container.status, error=last_error)
        raise TimeoutError(timeout_message)
    
    def stop_container(self, provider_id: str):
        """Stop a provider worker container."""
        container = self.running_containers.get(provider_id)
        
        if not container:
            logger.warning("container_not_found", provider_id=provider_id)
            return
        
        logger.info("container_stopping", container=container.name, provider_id=provider_id)
        
        try:
            container.stop(timeout=10)
            container.remove()
            del self.running_containers[provider_id]
            logger.info("container_stopped", container=container.name, provider_id=provider_id)
        except Exception as e:
            logger.error("container_stop_failed", provider_id=provider_id, error=str(e))
    
    def get_container_logs(self, provider_id: str, tail: int = 100) -> str:
        """Get logs from a provider container."""
        container = self.running_containers.get(provider_id)
        
        if not container:
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
