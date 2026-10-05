"""
Container Lifecycle Manager
Manages Docker containers for provider workers with isolated credentials.
"""
import asyncio
import os
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import docker

from config import get_worker_backend_url
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from infrastructure.providers.provider_registry import ProviderRegistry
from infrastructure.providers.runtime import provider_container_name

logger = get_logger("container_manager")
_CONTAINER_MANAGER_MAX_RETRIES = 3
try:
    DEFAULT_HEALTH_TIMEOUT_SECONDS = max(10, int(os.getenv("COMFY_CONTAINER_HEALTH_TIMEOUT_SECONDS", "180")))
except ValueError:
    DEFAULT_HEALTH_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class ContainerSnapshot:
    """A container's state at a point in time.

    Deliberately small and immutable: it is cached and handed to callers on other
    threads, and nothing should be able to reach through it to a live Docker
    object.
    """

    name: str
    status: str
    health: str | None = None

    @property
    def running(self) -> bool:
        return self.status == "running"

    @property
    def healthy(self) -> bool | None:
        """True/False from the image HEALTHCHECK, or None when it declares none."""
        if self.health is None:
            return None
        return self.health == "healthy"


# Short enough that the providers dashboard does not hammer the Docker socket,
# long enough that one page load (which resolves every provider) pays for a
# single probe per container.
_SNAPSHOT_TTL_SECONDS = 2.0


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
        self.running_containers: dict[str, docker.models.containers.Container] = {}
        # container name -> (monotonic deadline, snapshot). `running_containers`
        # cannot serve this: it is only populated for containers this process
        # started, and a status read must not depend on that.
        self._snapshot_cache: dict[str, tuple[float, ContainerSnapshot | None]] = {}
        self._snapshot_lock = threading.Lock()
        
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
    
    def build_worker_image(self, provider_type: str, worker_type: str | None = None) -> str:
        """
        Build Docker image for provider worker.

        Args:
            provider_type: Type of provider (modal, beam, direct_url, openai_compat, anthropic, google)
            worker_type: Which worker the image is for ("image", "llm", "tts").
                Derived from the provider's image tag when omitted. A TTS
                provider is `type="modal"`, so without this it built
                `image_worker/Dockerfile`, which does not contain `tts_worker/`
                at all — the deploy would have succeeded and produced an image
                whose entrypoint did not exist.

        Returns:
            Image tag
        """
        worker_image = ProviderRegistry.get_worker_image(provider_type)
        if not worker_type:
            worker_kind = "tts" if "tts" in worker_image else ("llm" if "llm" in worker_image else "image")
        else:
            worker_kind = worker_type
        worker_dir = self.containers_dir / f"{worker_kind}_worker"
        dockerfile_path = f"{worker_kind}_worker/Dockerfile"
        
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

    def build_worker_images(self, provider_types: Iterable[str] | None = None) -> dict[str, str]:
        """Build provider worker images and continue past individual failures."""
        image_tags: dict[str, str] = {}
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
    
    def _start_container_sync(
        self,
        provider_id: str,
        provider_type: str,
        port: int,
        env_vars: dict[str, str] | None,
        container_name: str,
        rebuild: bool = False,
    ) -> docker.models.containers.Container:
        """Every blocking Docker SDK call in the start path, in one worker thread.

        Split out of `start_container` because the whole body is synchronous
        socket I/O against the Docker daemon — `images.get`, a possibly
        multi-minute `images.build` with its log stream, `containers.get`,
        `stop`, `remove`, `containers.run` — and it was running on the event
        loop. `_wait_for_health` one function below already used `to_thread`, so
        the awareness existed; it just stopped at the boundary. Reached from
        `provider_lifecycle_service.start_container` and from
        `load_balancer._warm_provider_in_background`, i.e. while other requests
        are being served.

        Raises before starting anything if the host path the worker mount depends
        on is unset, so a misconfigured host does not get as far as replacing a
        running container.
        """
        image_tag = ProviderRegistry.get_worker_image(provider_type)

        # Check if image exists
        image_exists = False
        try:
            self.client.images.get(image_tag)
            image_exists = True
        except docker.errors.ImageNotFound:
            pass

        # Build if requested or missing
        if not image_exists:
            logger.info(
                "image_building",
                image_tag=image_tag,
                reason="rebuild" if rebuild else "missing",
            )
            self.build_worker_image(provider_type)
        else:
            logger.debug("image_exists", image_tag=image_tag)

        # Prepare environment
        environment = {
            "PROVIDER_ID": provider_id,
            "PORT": str(port),
            "BACKEND_URL": get_worker_backend_url(),
        }
        if env_vars:
            environment.update(env_vars)

        # Check if container already exists. Note this happens AFTER the
        # HOST_BACKEND_PATH check below, deliberately: stopping a running
        # provider and then failing to start it again is the worst outcome.
        backend_host_path = os.getenv("HOST_BACKEND_PATH")
        if not backend_host_path:
            raise ValueError(
                f"HOST_BACKEND_PATH environment variable is not set. "
                f"Worker container for provider '{provider_id}' requires access to "
                f"backend code and models. Set HOST_BACKEND_PATH to the host path "
                f"where the backend directory is mounted."
            )
        volumes = {backend_host_path: {"bind": "/backend", "mode": "ro"}}

        try:
            old_container = self.client.containers.get(container_name)
            logger.info("container_removing_old", container_name=container_name)
            old_container.stop()
            old_container.remove()
        except docker.errors.NotFound:
            pass

        # Use the compose-defined network name for container-to-container communication
        target_network = os.getenv("COMFY_DOCKER_NETWORK", "tnhcomfy")
        logger.debug("container_network", network=target_network)

        logger.info("container_starting", container_name=container_name, port=port)
        try:
            container_config = {
                "image": image_tag,
                "name": container_name,
                # Bind to loopback only. The backend reaches the provider over
                # the COMFY_DOCKER_NETWORK bridge by container name, so there is
                # no reason to expose the provider's management API (which
                # includes /deploy) on every host interface.
                "ports": {f"127.0.0.1:{port}/tcp": port},
                "environment": environment,
                "volumes": volumes,
                "detach": True,
                "remove": False,
                "labels": {"comfy-provider": "true", "provider-id": provider_id},
                "network": target_network,  # Directly join comfy-network
            }
            container = self.client.containers.run(**container_config)
        except Exception:
            # The container may now exist in a failed state, and the snapshot
            # cache still describes the pre-start world.
            self.invalidate_container_snapshot(container_name=container_name)
            raise

        logger.debug("container_network_joined", network=target_network)
        self.invalidate_container_snapshot(container_name=container_name)
        return container

    async def start_container(
        self,
        provider_id: str,
        provider_type: str,
        port: int,
        env_vars: dict[str, str] | None = None,
        rebuild: bool = False,
        container_name: str | None = None,
    ):
        """Start a provider worker container.

        `env_file` used to be a parameter here and was never read by anything —
        no caller passed it, and the code used `env_vars` exclusively.
        """
        logger.info("container_start_request", provider_id=provider_id, port=port)

        resolved_name = container_name or provider_container_name(provider_id)
        # `rebuild` is consumed inside the worker thread; passing it as a
        # keyword keeps the blocking signature free of a flag the loop would
        # otherwise have to read back.
        container = await asyncio.to_thread(
            self._start_container_sync,
            provider_id=provider_id,
            provider_type=provider_type,
            port=port,
            env_vars=env_vars,
            container_name=resolved_name,
            rebuild=rebuild,
        )

        try:
            # Wait for container to be healthy
            await self._wait_for_health(
                container, timeout=DEFAULT_HEALTH_TIMEOUT_SECONDS
            )
            self.running_containers[provider_id] = container
            logger.info(
                "container_started", container_name=resolved_name, provider_id=provider_id
            )
            return container
        except Exception as e:
            logger.error("container_start_failed", provider_id=provider_id, error=str(e))
            self.invalidate_container_snapshot(container_name=resolved_name)
            raise

    def _health_probe_targets(self, container: docker.models.containers.Container) -> list[tuple[str, str]]:
        """Build health probe targets in order of reliability for current runtime."""
        targets: list[tuple[str, str]] = []
        seen_urls = set()

        def add_target(name: str, url: str | None):
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            targets.append((name, url))

        container_name = getattr(container, "name", None)
        port = 8000
        if isinstance(getattr(container, "ports", None), dict):
            for port_key in container.ports:
                if str(port_key).endswith("/tcp"):
                    try:
                        port = int(str(port_key).split("/", 1)[0])
                    except ValueError:
                        pass
                    break
        if container_name:
            # Primary path when backend and worker are on the same container network.
            add_target("container_dns", f"http://{container_name}:{port}/health")

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
                            add_target("container_ip", f"http://{ip_address}:{port}/health")

        ports = container.ports.get(f"{port}/tcp") if isinstance(container.ports, dict) else None
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
    
    def get_container_snapshot(self, provider_id: str, container_name: str | None = None) -> ContainerSnapshot | None:
        """Status/health of a provider container, or None if it does not exist.

        This is the one place container state is read from. `containers.get()` and
        `container.reload()` are blocking round trips to the Docker socket with no
        timeout, and several callers were doing them directly from `async def`
        handlers — `GET /api/v2/providers/` does it twice per provider, serially, so
        a `DOCKER_HOST` pointing at an unreachable endpoint stalled the whole event
        loop for the sum of every connect timeout.

        The TTL cache is what makes a list page affordable: one probe per container
        per window, not two per provider per request. It is not used as a source of
        truth for control flow — `stop_container` and the deploy paths still talk
        to Docker directly.

        Blocking. Call it from `asyncio.to_thread`, or use
        `services.provider_runtime.resolve_provider_runtime_async`, which does.
        """
        name = container_name or provider_container_name(provider_id)
        now = time.monotonic()
        with self._snapshot_lock:
            cached = self._snapshot_cache.get(name)
            if cached is not None and cached[0] > now:
                return cached[1]

        snapshot = self._probe_container(name)
        with self._snapshot_lock:
            self._snapshot_cache[name] = (now + _SNAPSHOT_TTL_SECONDS, snapshot)
        return snapshot

    def invalidate_container_snapshot(self, container_name: str | None = None, provider_id: str | None = None) -> None:
        """Drop a cached snapshot after an action that changes container state."""
        name = container_name or (provider_container_name(provider_id) if provider_id else None)
        with self._snapshot_lock:
            if name is None:
                self._snapshot_cache.clear()
            else:
                self._snapshot_cache.pop(name, None)

    def _probe_container(self, name: str) -> ContainerSnapshot | None:
        client = self.client
        if client is None:
            return None
        try:
            container = client.containers.get(name)
        except docker.errors.NotFound:
            # The only failure that is an answer about *this* container: Docker
            # replied and said there is no such container.
            return None
        except Exception as exc:
            # Everything else is the runtime being unreachable, not the container
            # being down — daemon down, socket permission denied, TLS handshake
            # failure, a context that no longer exists, Podman/Docker API version
            # skew. This used to log at debug and return the same `None` as
            # NotFound, which made the two indistinguishable, and `None` was
            # cached for the full TTL by `get_container_snapshot` — so a
            # host-wide outage was reported as "every container absent" for two
            # seconds per probe. Raise, and let the caller's own contract decide
            # what an unknown state means; `provider_lifecycle_service` already
            # makes exactly this split.
            logger.error(
                "container_runtime_unreachable",
                container=name,
                error=str(exc),
                exc_info=True,
            )
            raise
        try:
            container.reload()
        except Exception as exc:
            # A container that exists but will not reload (removed mid-read) is
            # still worth reporting: `get` succeeded, so it was there a moment ago,
            # and that is a fact about the read rather than about the runtime.
            logger.debug("container_reload_failed", container=name, error=str(exc))
        health = (getattr(container, "attrs", {}) or {}).get("State", {}).get("Health", {}).get("Status")
        return ContainerSnapshot(
            name=name,
            status=getattr(container, "status", None) or "unknown",
            health=health,
        )

    def stop_container(self, provider_id: str):
        """Stop a provider worker container."""
        container_name = provider_container_name(provider_id)
        container = self.running_containers.get(provider_id)
        if not container:
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
        finally:
            # The snapshot describes container state, and the container has
            # changed either way — a stop that raised halfway still means the
            # state is not what the cache says. `invalidate_container_snapshot`
            # had no call site anywhere in the tree, so `resolve_provider_runtime`
            # could report a stopped container as running for up to the 2 s TTL,
            # which is exactly long enough for a load-balancer decision to be
            # made on it.
            self.invalidate_container_snapshot(container_name=container_name)
    
    def get_container_logs(self, provider_id: str, tail: int = 100) -> str:
        """Get logs from a provider container.

        Synchronous: `container.logs()` is a blocking socket read. Callers on the
        request path must offload it (`provider_lifecycle_service` does for its
        other two Docker methods and not for this one).
        """
        container = self.running_containers.get(provider_id)
        if not container:
            container_name = provider_container_name(provider_id)
            try:
                container = self.client.containers.get(container_name)
            except docker.errors.NotFound:
                return f"Container for provider {provider_id} not found"
        
        try:
            return container.logs(tail=tail).decode('utf-8')
        except Exception as e:
            return f"Error getting logs: {e}"
    
    def list_containers(self) -> tuple[list[dict], bool]:
        """List running provider containers, and whether the runtime answered.

        Degrades to an empty list with `False` rather than raising. This method
        had no exception handling at all, so a Docker outage made
        `GET /api/v2/providers/containers/list` answer **500** while
        `GET /api/v2/providers/containers/status`, on the same host in the same
        second, reported every container "stopped" with
        `container_runtime_available: true` — two opposite answers to one
        question, neither of which was true.

        Returns a `(containers, runtime_available)` pair because the empty list
        on its own is exactly what "no provider containers are running" looks
        like, which is the ambiguity that made the 500 the only honest option
        before.
        """
        try:
            containers = self.client.containers.list(
                filters={"label": "comfy-provider=true"}
            )
        except Exception as exc:
            logger.error(
                "container_runtime_unreachable",
                operation="list_containers",
                error=str(exc),
                exc_info=True,
            )
            return [], False

        return [
            {
                "id": c.short_id,
                "name": c.name,
                "provider_id": c.labels.get("provider-id"),
                "status": c.status,
                "ports": c.ports
            }
            for c in containers
        ], True
    
    def cleanup_all(self):
        """Stop and remove all provider containers."""
        logger.info("container_cleanup_all_start", count=len(self.running_containers))
        
        for provider_id in list(self.running_containers.keys()):
            self.stop_container(provider_id)
        
        logger.info("container_cleanup_all_complete")

