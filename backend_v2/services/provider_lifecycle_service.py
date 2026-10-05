from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
from sqlmodel import Session

import docker

from core.events import EventType, emit_provider_event
from core.exceptions import ProviderError, ServiceUnavailableError
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from infrastructure.providers.runtime import provider_container_name
from services.provider_runtime import resolve_provider_runtime_async
from services.provider_service import ProviderService
from services.provider_status_service import ProviderStatusService

# The worker's `/reconcile` vocabulary, read rather than assumed.
#
# `provider_core/base_client.py` returns `{"status": "started"}` after spawning
# its reconciliation task, and `{"status": "already_running"}` when one is in
# flight — both mean the backend should wait and let the worker report back.
# The LLM and TTS workers have no model tree and answer `ok` / `skipped` with
# counts, and never push a terminal state. `image_worker` and the Modal/Beam
# engines report `completed` / `error` / `indeterminate` synchronously for the
# quick-sync path.
_RECONCILIATION_IN_FLIGHT_STATUSES = frozenset(
    {"started", "queued", "already_running", "running", "reconciling", "pending"}
)
_RECONCILIATION_FAILED_STATUSES = frozenset({"error", "failed"})


def _as_dict(response: Any) -> dict[str, Any]:
    """A worker's JSON body, or `{}` when it is not a JSON object.

    The response is not trusted to be well-formed: a proxy in front of the
    worker can answer 200 with an HTML error page, and a worker built from an
    older image can answer 200 with a bare list. Neither is a reason for the
    backend to write a state it cannot justify — hence `{}`, which lands on the
    terminal branch with an honest message instead of raising.
    """
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}

logger = get_logger("provider_lifecycle")


class ProviderLifecycleService:
    """Orchestrate provider runtime/container lifecycle operations."""

    def __init__(
        self,
        session: Session,
        *,
        provider_service: ProviderService | None = None,
        container_manager: Any = None,
        invalidate_caches: Callable[[str | None], None] | None = None,
    ) -> None:
        self.session = session
        self.provider_service = provider_service or ProviderService(session)
        self.status_service = ProviderStatusService(session, provider_service=self.provider_service)
        self.container_manager = container_manager
        self.invalidate_caches = invalidate_caches or (lambda _provider_id=None: None)

    def _require_container_manager(self):
        if not self.container_manager:
            raise ProviderError("provider-runtime", "Container manager not initialized")
        return self.container_manager

    async def start_container(self, provider_id: str) -> dict[str, Any]:
        container_manager = self._require_container_manager()
        provider = await self.provider_service.get_provider(provider_id)
        container_config = provider.container_config
        if not container_config:
            raise ProviderError(
                provider_id,
                f"Provider '{provider_id}' is not configured for containerized mode",
            )

        container = await container_manager.start_container(
            provider_id=provider_id,
            provider_type=provider.type,
            port=container_config.get("port", 8000),
            env_vars=self.provider_service.build_provider_environment(provider),
            container_name=container_config.get("container_name"),
        )
        self.invalidate_caches(provider_id)
        await emit_provider_event(
            EventType.PROVIDER_CONTAINER_STATUS,
            provider_id,
            {"status": "running"},
        )
        return {
            "status": "success",
            "message": f"Container for provider '{provider_id}' started",
            "container_id": container.short_id,
        }

    async def stop_container(self, provider_id: str) -> dict[str, Any]:
        container_manager = self._require_container_manager()
        await asyncio.to_thread(container_manager.stop_container, provider_id)
        self.invalidate_caches(provider_id)
        await emit_provider_event(
            EventType.PROVIDER_CONTAINER_STATUS,
            provider_id,
            {"status": "stopped"},
        )
        return {
            "status": "success",
            "message": f"Container for provider '{provider_id}' stopped",
        }

    async def restart_container(self, provider_id: str) -> dict[str, Any]:
        await self.stop_container(provider_id)
        await self.start_container(provider_id)
        return {
            "status": "success",
            "message": f"Container for provider '{provider_id}' restarted",
        }

    def get_container_logs(self, provider_id: str, tail: int = 100) -> dict[str, Any]:
        if not self.container_manager:
            return {
                "provider_id": provider_id,
                "logs": "Container logs are unavailable (container manager not initialized). Please use 'docker compose logs' for local debugging.",
            }
        logs = self.container_manager.get_container_logs(provider_id, tail=tail)
        return {
            "provider_id": provider_id,
            "logs": logs,
        }

    async def get_container_status(self, provider_id: str) -> dict[str, Any]:
        container_manager = self._require_container_manager()
        provider = await self.provider_service.get_provider(provider_id)
        container_config = provider.container_config or {}
        container_name = container_config.get("container_name") or provider_container_name(provider_id)

        try:
            container = await asyncio.to_thread(container_manager.client.containers.get, container_name)
        except docker.errors.NotFound:
            # The only failure that genuinely means "stopped": Docker answered
            # and said there is no such container.
            return {
                "provider_id": provider_id,
                "status": "stopped",
                "running": False,
            }
        except Exception as exc:
            # Everything else is the runtime being unreachable, not the container
            # being down: daemon down, socket permission denied, TLS handshake
            # failure, a context that no longer exists, a Podman/Docker API
            # version skew. Reporting "stopped" for those answered the one
            # question nobody asked and hid the real one — a host-wide runtime
            # outage rendered as N independent, individually-actionable
            # "this container is stopped" verdicts. NotFound is still a valid
            # answer about one container; this is not an answer about any.
            logger.error(
                "container_runtime_unreachable",
                provider_id=provider_id,
                container_name=container_name,
                error=str(exc),
                exc_info=True,
            )
            raise ServiceUnavailableError(
                "Container runtime is unreachable",
                service="container_runtime",
            ) from exc

        await asyncio.to_thread(container.reload)

        healthy = False
        try:
            health_status = container.attrs.get("State", {}).get("Health", {}).get("Status")
            if health_status:
                healthy = health_status == "healthy"
            else:
                port = container.ports.get(f"{container_config.get('port', 8000)}/tcp")
                if port:
                    host_port = port[0].get("HostPort")
                    if host_port:
                        client = get_http_client()
                        response = await client.get(f"http://localhost:{host_port}/health", timeout=2.0)
                        healthy = response.status_code == 200
        except Exception as exc:
            logger.debug("provider_health_refresh_failed", provider_id=provider_id, error=str(exc))

        if container.status == "running":
            container_manager.running_containers[provider_id] = container
        elif provider_id in container_manager.running_containers:
            del container_manager.running_containers[provider_id]

        return {
            "provider_id": provider_id,
            "status": container.status,
            "running": container.status == "running",
            "healthy": healthy,
            "container_id": container.short_id,
            "ports": container.ports,
        }

    async def setup_provider(self, provider_id: str) -> dict[str, Any]:
        provider = await self.provider_service.get_provider(provider_id)
        runtime = await resolve_provider_runtime_async(provider)
        if not runtime.supports_setup or runtime.mode not in ("container_http", "discovery"):
            raise ProviderError(
                provider_id,
                "Setup requires a provider with a reachable worker runtime",
            )

        http_client = get_http_client()
        try:
            response = await http_client.post(
                f"{runtime.worker_url}/setup",
                timeout=30.0,
            )
            response.raise_for_status()
            result = response.json()
        except httpx.TimeoutException as exc:
            raise ProviderError(
                provider_id,
                f"Setup request to worker timed out: {type(exc).__name__}",
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            error_message = str(exc).strip() or type(exc).__name__
            raise ProviderError(
                provider_id,
                f"Failed to run provider setup via worker: {error_message}",
            ) from exc

        worker_status = result.get("status") if isinstance(result, dict) else None
        worker_message = result.get("message") if isinstance(result, dict) else None
        accepted = worker_status in {"queued", "started"}

        return {
            "status": "accepted" if accepted else "success",
            "message": worker_message or (
                f"Provider '{provider_id}' setup queued (via worker)"
                if accepted
                else f"Provider '{provider_id}' setup complete (via worker)"
            ),
            "result": result,
        }

    async def sync_provider_models(self, provider_id: str) -> dict[str, Any]:
        return await self.trigger_reconciliation(provider_id, force=True, quick_sync=True)

    async def trigger_reconciliation(self, provider_id: str, force: bool = False, quick_sync: bool = False) -> dict[str, Any]:
        provider = await self.provider_service.get_provider(provider_id)
        runtime = await resolve_provider_runtime_async(provider)
        if not runtime.supports_reconciliation or runtime.mode not in ("container_http", "discovery"):
            raise ProviderError(
                provider_id,
                "Reconciliation is only available for container-backed or discovered providers",
            )

        session_state = await self.provider_service.start_reconciliation_session(provider_id, force=force)
        if not session_state.get("accepted"):
            return {
                "status": "already_running",
                "provider_id": provider_id,
                "message": session_state.get("message", "Reconciliation already in progress"),
                "reconciliation_state": session_state.get("state"),
            }

        http_client = get_http_client()
        try:
            response = await http_client.post(
                f"{runtime.worker_url}/reconcile",
                json={"quick_sync": quick_sync},
                timeout=5.0,
            )
        except httpx.HTTPError as exc:
            await asyncio.to_thread(
                self.provider_service.upsert_reconciliation_state,
                provider_id,
                {
                    "status": "failed",
                    "message": f"Failed to reach worker: {exc!s}",
                },
            )
            self.invalidate_caches(provider_id)
            raise

        if response.status_code == 200:
            # The worker answers `/reconcile` with a *status*, and the status
            # decides whether this provider is now busy or already done. It used
            # to be discarded, so every 200 became "reconciling / starting" and
            # the backend waited for the worker to report back.
            #
            # For the image workers that is right: they POST progress to
            # `/reconciliation-event` and finish the state themselves. For the
            # LLM and TTS workers it never happens — they have no model tree to
            # reconcile and answer immediately with `skipped` / `ok`, and they
            # never push a terminal state. Live proof on a running stack:
            # `llm-local` and `tts-modal-hp196` both sat at
            # `status: "reconciling", phase: "starting", message:
            # "Reconciliation started in worker"` with `updated_at` frozen,
            # reading "Reconciliation started in worker" while the worker had
            # answered "skipped" in milliseconds. `RECONCILIATION_IN_PROGRESS_TTL`
            # is 180 minutes, so that is three hours of a provider card claiming
            # to be busy, per trigger.
            #
            # So the worker's own vocabulary is honoured here. `setup_models`
            # twenty lines up in this file already reads `worker_status` and
            # branches on it; this was the same decision not repeated.
            worker_result = _as_dict(response)
            worker_status = str(worker_result.get("status") or "").strip()
            worker_message = (
                worker_result.get("message")
                or worker_result.get("note")
                or worker_result.get("message")
                or f"Reconciliation {' '.join(worker_status.split())}"
            ).strip()

            if worker_status in _RECONCILIATION_IN_FLIGHT_STATUSES:
                persisted_state = await asyncio.to_thread(
                    self.provider_service.upsert_reconciliation_state,
                    provider_id,
                    {
                        "status": "reconciling",
                        "phase": "running",
                        "message": worker_message,
                        "last_contact_at": ProviderService._utcnow_iso(),
                    },
                )
                self.invalidate_caches(provider_id)
                return {
                    "status": "triggered",
                    "provider_id": provider_id,
                    "message": worker_message,
                    "reconciliation": self.status_service.normalize_reconciliation_for_card(
                        persisted_state
                    ),
                }

            # Terminal: the worker had nothing to do, or finished synchronously.
            # Record that as the outcome rather than as work in flight.
            terminal_status = "failed" if worker_status in _RECONCILIATION_FAILED_STATUSES else "completed"
            persisted_state = await asyncio.to_thread(
                self.provider_service.upsert_reconciliation_state,
                provider_id,
                {
                    "status": terminal_status,
                    "phase": worker_status or terminal_status,
                    "message": worker_message,
                    "stats": worker_result.get("stats") or {},
                    "errors": worker_result.get("errors") or [],
                    "last_contact_at": ProviderService._utcnow_iso(),
                },
            )
            self.invalidate_caches(provider_id)
            return {
                "status": terminal_status,
                "provider_id": provider_id,
                "message": worker_message,
                "reconciliation": self.status_service.normalize_reconciliation_for_card(
                    persisted_state
                ),
            }

        if response.status_code == 409:
            await asyncio.to_thread(
                self.provider_service.upsert_reconciliation_state,
                provider_id,
                {
                    "status": "reconciling",
                    "phase": "running",
                    "message": "Worker reported reconciliation already in progress",
                    "last_contact_at": ProviderService._utcnow_iso(),
                },
            )
            return {
                "status": "already_running",
                "provider_id": provider_id,
                "message": "Reconciliation already running in worker",
            }

        body = response.text
        await asyncio.to_thread(
            self.provider_service.upsert_reconciliation_state,
            provider_id,
            {
                "status": "failed",
                "message": f"Failed to trigger reconciliation: {body}",
            },
        )
        raise httpx.HTTPStatusError(
            f"Failed to trigger reconciliation: {body}",
            request=response.request,
            response=response,
        )

    async def get_reconciliation_status(self, provider_id: str) -> dict[str, Any]:
        provider = await self.provider_service.get_provider(provider_id)
        persisted_state = await self.provider_service.get_provider_reconciliation_state(provider_id)
        runtime = await resolve_provider_runtime_async(provider)

        if runtime.mode not in ("container_http", "discovery"):
            if persisted_state.get("status") and persisted_state.get("status") != "idle":
                return persisted_state
            return {
                "provider_id": provider_id,
                "status": "idle",
                "message": "Status tracking is only available for container-backed or discovered providers",
            }

        http_client = get_http_client()
        try:
            response = await http_client.get(
                f"{runtime.worker_url}/reconciliation-status",
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            if persisted_state.get("status") and persisted_state.get("status") != "idle":
                merged_state = dict(persisted_state)
                merged_state["message"] = merged_state.get("message") or "Worker unreachable; showing last persisted reconciliation state"
                merged_state["warning"] = f"Cannot reach worker: {exc!s}"
                return merged_state
            return {
                "provider_id": provider_id,
                "status": "idle",
                "warning": f"Cannot reach worker: {exc!s}",
            }

        if response.status_code == 200:
            worker_state = response.json()
            return await asyncio.to_thread(
                self.provider_service.upsert_reconciliation_state,
                provider_id,
                {
                    **worker_state,
                    "last_contact_at": ProviderService._utcnow_iso(),
                },
            )

        if response.status_code == 404:
            if persisted_state.get("status") and persisted_state.get("status") != "idle":
                return persisted_state
            return {
                "provider_id": provider_id,
                "status": "idle",
                "message": "Status tracking not available",
            }

        if persisted_state.get("status") and persisted_state.get("status") != "idle":
            return persisted_state
        raise httpx.HTTPStatusError(
            "Failed to get reconciliation status",
            request=response.request,
            response=response,
        )
