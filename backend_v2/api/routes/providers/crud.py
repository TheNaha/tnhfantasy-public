# Provider routes - Complete implementation with feature parity to backend_v1
#
# KEY ENDPOINTS:
#   GET    /api/v2/providers              – List all configured providers
#   POST   /api/v2/providers              – Register a new provider
#   GET    /api/v2/providers/{id}         – Get provider details
#   PATCH  /api/v2/providers/{id}         – Update provider config/credentials
#   DELETE /api/v2/providers/{id}         – Remove provider + cascade status records
#   GET    /api/v2/providers/load-balancing – Current LB strategy
#   PUT    /api/v2/providers/load-balancing – Update LB strategy
import asyncio
import time
from types import SimpleNamespace
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from api.deps import (
    get_container_manager,
    get_provider_service,
    get_provider_status_service,
    get_provider_worker_url,
    get_session,
)
from core.entities import Provider
from infrastructure.background_tasks import start_background_task
from infrastructure.http_client import get_http_client
from infrastructure.logging import api_logger
from services.provider_runtime import resolve_provider_runtime_async
from services.provider_service import ProviderService
from services.provider_status_service import invalidate_provider_status_caches

logger = api_logger()




router = APIRouter()


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================


# The task types a provider declares it can serve. Spelled `worker_type` +
# `declared_capabilities` rather than reusing the name `capabilities`, which on
# the read path is the unrelated UI action map (`container`, `deploy`, `setup`,
# ...) that the frontend has always consumed under that key.
WorkerType = Literal["image", "llm", "tts"]
DeclaredCapability = Literal["image", "llm", "tts"]


class ProviderRequest(BaseModel):
    id: str
    type: str = "modal"
    worker_type: WorkerType | None = None
    declared_capabilities: list[DeclaredCapability] | None = None
    enabled: bool = True
    priority: int = 1
    credentials: dict[str, Any] = {}
    runtime_config: dict[str, Any] | None = None
    deploy_config: dict[str, Any] | None = None
    # Legacy compatibility fields accepted on write only.
    config: dict[str, Any] = {}
    container_config: dict[str, Any] | None = None


class ProviderUpdateRequest(BaseModel):
    type: str | None = None
    worker_type: WorkerType | None = None
    declared_capabilities: list[DeclaredCapability] | None = None
    enabled: bool | None = None
    priority: int | None = None
    credentials: dict[str, Any] | None = None
    runtime_config: dict[str, Any] | None = None
    deploy_config: dict[str, Any] | None = None
    # Legacy compatibility fields accepted on write only.
    config: dict[str, Any] | None = None
    container_config: dict[str, Any] | None = None


class LoadBalancingConfigRequest(BaseModel):
    strategy: str | None = None
    fallback_enabled: bool | None = None


class AddCustomProviderModelRequest(BaseModel):
    directory: str
    model_data: dict[str, Any]
    provider_ids: list[str]


class TestConnectionRequest(BaseModel):
    id: str | None = None
    type: str
    credentials: dict[str, Any] = {}
    config: dict[str, Any] = {}



# ============================================================================
# LOAD BALANCER CONFIG
# ============================================================================


@router.get("/config/load-balancing")
async def get_load_balancing_config(session: Session = Depends(get_session)):
    """Get load balancing configuration with stats."""
    service = get_provider_service(session)
    config = service.get_load_balancing_config()
    stats = await service.get_load_balancer_stats()
    return {
        "config": {
            "strategy": config.strategy,
            "fallback_enabled": config.fallback_enabled
        },
        "stats": stats
    }


@router.put("/config/load-balancing")
async def update_load_balancing_config(
    request: LoadBalancingConfigRequest,
    session: Session = Depends(get_session)
):
    """Update load balancing configuration."""
    service = get_provider_service(session)
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    config = await service.update_load_balancing_config(**updates)
    return {
        "status": "success",
        "strategy": config.strategy,
        "fallback_enabled": config.fallback_enabled
    }


@router.get("/load-balancer/stats")
async def get_load_balancer_stats(session: Session = Depends(get_session)):
    """Get load balancer statistics."""
    service = get_provider_service(session)
    stats = await service.get_load_balancer_stats()
    return stats


# Alias paths for frontend compatibility
@router.get("/load-balancing")
async def get_load_balancing_alias(session: Session = Depends(get_session)):
    """Alias for /config/load-balancing."""
    return await get_load_balancing_config(session)


@router.put("/load-balancing")
async def update_load_balancing_alias(
    request: LoadBalancingConfigRequest,
    session: Session = Depends(get_session)
):
    """Alias for /config/load-balancing."""
    return await update_load_balancing_config(request, session)



# ============================================================================
# PROVIDER CRUD ENDPOINTS
# ============================================================================


@router.post("/wake")
async def wake_providers(session: Session = Depends(get_session)):
    """Ping enabled provider containers to wake them up from cold start."""
    service = get_provider_service(session)
    providers = service.get_enabled_providers()
    active_providers = [provider for provider in providers if provider.container_config]
    
    if not active_providers:
        return {"status": "success", "message": "No active containerized providers to wake"}

    async def ping_containers():
        http_client = get_http_client()

        async def ping_worker(provider_id: str):
            try:
                await http_client.get(
                    f"{get_provider_worker_url(provider_id)}/health",
                    timeout=5.0,
                )
            except Exception as exc:
                logger.debug("worker_ping_failed", provider_id=provider_id, error=str(exc))

        await asyncio.gather(
            *(ping_worker(provider.id) for provider in active_providers),
            return_exceptions=True,
        )

    start_background_task(ping_containers(), task_name="wake_provider_containers")
    
    return {"status": "success", "message": f"Wake signal sent to {len(active_providers)} providers"}


async def _republish_known_provider_hosts() -> None:
    """Re-read the provider table after a write, so the token attachment is not stale.

    The set of hosts that count as "one of our providers" is published to
    `infrastructure.http_client` and read from the request path without touching
    the database — a blocking read inside `build_request()` is impossible to
    avoid, because `build_request` is synchronous and runs on the event loop. A
    provider create/update/delete changes the answer, so this is the invalidation
    point that the published cache is missing. Offloaded, and a failure is
    logged rather than raised: the loader publishes `None` on failure, which the
    request path already treats as "attach the token anyway".
    """
    from infrastructure.http_client import load_known_provider_hosts

    try:
        await asyncio.to_thread(load_known_provider_hosts, force=True)
    except Exception as exc:  # pragma: no cover - the loader handles its own failures
        logger.warning("provider_host_republish_failed", error=str(exc))


def _infer_discovery_type(provider_id: str) -> tuple[str, str]:
    """Map a container-derived provider id to (provider_type, worker_type).

    Mirrors what the provider containers themselves heartbeat (see
    image_worker/worker.py and llm_worker/worker.py) so a detected row
    matches what discovery would eventually create.
    """
    if provider_id == "llm-local" or "llm" in provider_id:
        return "openai_compat", "llm"
    # TTS before the `modal-` branch, because a TTS provider is named
    # `tts-modal-<name>` and would otherwise be registered as an image worker —
    # offered checkpoint jobs its container cannot run. Checked before `llm` too
    # for the same reason: the substring test on "llm" is loose enough to catch
    # any name containing it, and order is what makes the specific cases win.
    if "tts" in provider_id:
        return "modal", "tts"
    if provider_id.startswith("modal-"):
        return "modal", "image"
    if provider_id.startswith("beam-"):
        return "beam", "image"
    if provider_id == "direct-url":
        return "direct_url", "image"
    return "direct_url", "image"


@router.post("/detect")
async def detect_provider_containers(
    container_manager = Depends(get_container_manager),
    service: ProviderService = Depends(get_provider_service),
):
    """Register running provider containers that are not yet providers.

    Scans deployment-managed containers (label comfy-provider=true) and
    compose-managed `tnhcomfy-*` containers when a container runtime socket
    is available, upserting the missing ones via the same path discovery
    heartbeats use. When no socket is available (typical compose setup),
    container workers self-register through their heartbeat — this endpoint
    then reports what is already known.
    """
    container_runtime_available = container_manager is not None
    existing = {p.id for p in service.repo.get_all()}
    candidates: dict[str, str] = {}

    if container_manager:
        # Both of these are synchronous Docker socket reads with no timeout, on
        # the event loop of an `async def` handler. `list_containers` is a raw
        # `client.containers.list()` with no TTL cache, so this was a blocking
        # round-trip to the daemon on every call, stalling every other
        # in-flight request for its duration. `container_manager`'s own
        # docstring says to call it from `asyncio.to_thread`.
        #
        # The session work below stays on the loop: it is bounded, indexed, and
        # moving a request-scoped `Session` into a worker thread is the pattern
        # that breaks the moment anything else uses it concurrently.
        def _scan() -> tuple[list[dict], bool, object, str | None]:
            entries, runtime_available = container_manager.list_containers()
            try:
                raw = container_manager.client.containers.list(all=False)
            except Exception as exc:
                return entries, runtime_available, [], str(exc)
            return entries, runtime_available, raw, None

        entries, list_runtime_available, raw, scan_error = await asyncio.to_thread(_scan)
        container_runtime_available = container_runtime_available and list_runtime_available

        for entry in entries:
            name = entry.get("name") or ""
            provider_id = entry.get("provider_id") or (
                name[len("tnhcomfy-"):] if name.startswith("tnhcomfy-") else None
            )
            if provider_id:
                candidates[provider_id] = name

        if scan_error is not None:
            logger.warning("detect_container_scan_failed", error=scan_error)
            container_runtime_available = False

        skip_prefixes = ("tnhcomfy-backend", "tnhcomfy-frontend", "tnhcomfy-db", "tnhcomfy-deploy-")
        for container in raw:
            name = container.name
            if not name.startswith("tnhcomfy-"):
                continue
            if name.startswith(skip_prefixes):
                continue
            provider_id = (container.labels or {}).get("provider-id") or name[len("tnhcomfy-"):]
            candidates[provider_id] = name

    created: list[str] = []
    for provider_id, container_name in sorted(candidates.items()):
        if provider_id in existing:
            continue
        provider_type, worker_type = _infer_discovery_type(provider_id)
        await service.upsert_provider_from_discovery(
            provider_id=provider_id,
            provider_type=provider_type,
            worker_type=worker_type,
            internal_url=f"http://{container_name}:8000",
        )
        # Container SCAN has no heartbeat payload, so capabilities come from the
        # inferred worker_type alone — a scanned `tts-modal-*` container gets
        # `[worker_type]` from the upsert default, which is correct. The heartbeat
        # path, when the container is reachable, overrides with what it declares.
        created.append(provider_id)

    already = sorted(existing)
    logger.info("providers_detected", created=created, already=already,
                container_runtime_available=container_runtime_available)
    return {
        "created": created,
        "already": already,
        "container_runtime_available": container_runtime_available,
    }


@router.post("/{provider_id}/ping")
async def ping_provider(provider_id: str, session: Session = Depends(get_session)):
    """Ping a provider worker from the backend network and report latency.

    Browsers cannot resolve docker-internal worker hostnames (tnhcomfy-<id>),
    so the health probe is proxied through the backend instead of being
    fetched directly from the client.
    """
    provider = session.get(Provider, provider_id)
    if not provider:
        return {
            "healthy": False,
            "worker_url": None,
            "latency_ms": None,
            "error": "Provider not found",
        }

    base_url = None
    runtime = await resolve_provider_runtime_async(provider)
    if runtime.mode == "in_process":
        from services.engines.engine_factory import get_engine

        engine = get_engine(provider_id, provider)
        if engine:
            try:
                # Bounded like the container /health probe below; an engine
                # whose upstream hangs must answer unhealthy, not hang ping.
                health = await asyncio.wait_for(engine.check_health(), timeout=10.0)
            except Exception as exc:
                # Parity with container path which returned {healthy:false}
                # instead of 500 on probe failure.
                return {
                    "healthy": False,
                    "worker_url": "in_process",
                    "latency_ms": 0,
                    "error": str(exc),
                }
            # "ok" counts: llm_config.test_llm_provider treats healthy/ok/ready
            # as healthy, and engines report both vocabularies.
            is_healthy = bool(
                health.get("ready") or health.get("status") in ("healthy", "ok")
            )
            return {
                "healthy": is_healthy,
                "worker_url": "in_process",
                "latency_ms": health.get("latency_ms", 0),
                "error": None if is_healthy else health.get("error"),
            }

    if runtime.worker_url:
        base_url = runtime.worker_url.rstrip("/")
    elif provider.container_config:
        base_url = get_provider_worker_url(provider_id).rstrip("/")
    if not base_url:
        return {
            "healthy": False,
            "worker_url": None,
            "latency_ms": None,
            "error": "No worker URL configured for this provider",
        }

    client = get_http_client()
    started = time.monotonic()
    try:
        resp = await client.get(f"{base_url}/health", timeout=10.0)
    except Exception as e:
        latency_ms = int((time.monotonic() - started) * 1000)
        return {
            "healthy": False,
            "worker_url": base_url,
            "latency_ms": latency_ms,
            "error": f"Health check failed: {e}",
        }
    latency_ms = int((time.monotonic() - started) * 1000)
    return {
        "healthy": resp.status_code == 200,
        "worker_url": base_url,
        "latency_ms": latency_ms,
        "error": None if resp.status_code == 200 else f"Health check failed: HTTP {resp.status_code}",
    }


# ============================================================================
# ENGINE SCHEMAS & INTERACTIVE TEST BENCH
# ============================================================================

ENGINE_SCHEMAS: dict[str, dict[str, Any]] = {
    "modal": {
        "id": "modal",
        "name": "Modal (ComfyUI)",
        "category": "image",
        "worker_type": "image",
        "capabilities": ["image"],
        "description": "Serverless ComfyUI execution on Modal cloud GPU workers with shared volume storage.",
        "credentials": [
            {"key": "token_id", "label": "Modal Token ID", "type": "password", "required": True, "placeholder": "ak-..."},
            {"key": "token_secret", "label": "Modal Token Secret", "type": "password", "required": True, "placeholder": "as-..."},
            {"key": "hf_token", "label": "HuggingFace Token", "type": "password", "required": False, "placeholder": "hf_..."},
            {"key": "civitai_token", "label": "CivitAI Token", "type": "password", "required": False, "placeholder": "CivitAI API token"},
        ],
        "config": [
            {"key": "app_name", "label": "Modal App Name", "type": "text", "default": "comfy-modal-stack", "placeholder": "comfy-modal-stack"},
            {"key": "enable_memory_snapshot", "label": "Memory Snapshot", "type": "checkbox", "default": False, "help_text": "Use memory snapshot container if deployed"},
        ],
    },
    "beam": {
        "id": "beam",
        "name": "Beam.cloud (ComfyUI)",
        "category": "image",
        "worker_type": "image",
        "capabilities": ["image"],
        "description": "Serverless ComfyUI execution on Beam.cloud GPU endpoints with persistent storage volume.",
        "credentials": [
            {"key": "api_key", "label": "Beam API Key", "type": "password", "required": True, "placeholder": "beam_..."},
            {"key": "workspace_id", "label": "Workspace ID", "type": "text", "required": False, "placeholder": "Workspace ID"},
            {"key": "hf_token", "label": "HuggingFace Token", "type": "password", "required": False, "placeholder": "hf_..."},
            {"key": "civitai_token", "label": "CivitAI Token", "type": "password", "required": False, "placeholder": "CivitAI Token"},
        ],
        "config": [
            {"key": "gpu_url", "label": "GPU Realtime / Webhook URL", "type": "text", "required": True, "placeholder": "https://...beam.run"},
            {"key": "storage_url", "label": "Storage REST App URL", "type": "text", "required": True, "placeholder": "https://...beam.run"},
            {"key": "download_url", "label": "Downloader URL (Optional)", "type": "text", "required": False, "placeholder": "Defaults to Storage URL"},
            {"key": "gpu_type", "label": "GPU Accelerator Type", "type": "select", "default": "RTX4090", "options": ["RTX4090", "A10G", "A100", "H100"]},
        ],
    },
    "direct_url": {
        "id": "direct_url",
        "name": "Direct ComfyUI Server",
        "category": "image",
        "worker_type": "image",
        "capabilities": ["image"],
        "description": "Direct HTTP & WebSocket connection to any running ComfyUI server instance.",
        "credentials": [
            {"key": "comfyui_api_key", "label": "ComfyUI API Key", "type": "password", "required": False, "placeholder": "Optional auth token"},
            {"key": "agent_api_key", "label": "Remote Agent API Key", "type": "password", "required": False, "placeholder": "Optional agent auth token"},
        ],
        "config": [
            {"key": "comfy_url", "label": "ComfyUI Server URL", "type": "text", "required": True, "default": "http://localhost:8188", "placeholder": "http://localhost:8188"},
            {"key": "remote_agent_url", "label": "Remote Agent Sidecar URL", "type": "text", "required": False, "placeholder": "http://remote-host:8001"},
        ],
    },
    "openai_compat": {
        "id": "openai_compat",
        "name": "OpenAI / Local LLM (Ollama, vLLM, OpenRouter)",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "Standard OpenAI chat completion endpoint for local LLMs (Ollama, LM Studio) or hosted APIs.",
        "credentials": [
            {"key": "api_key", "label": "API Key", "type": "password", "required": False, "placeholder": "sk-... (leave empty for local Ollama)"},
        ],
        "config": [
            {"key": "base_url", "label": "API Base URL", "type": "text", "required": True, "default": "http://localhost:11434/v1", "placeholder": "https://api.openai.com/v1"},
            {"key": "model", "label": "Default Model ID", "type": "text", "required": False, "placeholder": "e.g. llama3.2, mistral, gpt-4o"},
            {"key": "temperature", "label": "Default Temperature", "type": "number", "default": 0.7, "step": 0.05, "min": 0.0, "max": 2.0},
            {"key": "max_output_tokens", "label": "Max Output Tokens", "type": "number", "default": 4096},
        ],
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "Anthropic Claude Messages API (Claude 3.5 Sonnet, Claude 3.5 Haiku, etc.).",
        "credentials": [
            {"key": "api_key", "label": "Anthropic API Key", "type": "password", "required": True, "placeholder": "sk-ant-..."},
        ],
        "config": [
            {"key": "model", "label": "Default Model ID", "type": "text", "default": "claude-3-5-sonnet-latest", "placeholder": "claude-3-5-sonnet-latest"},
            {"key": "temperature", "label": "Default Temperature", "type": "number", "default": 0.7, "step": 0.05, "min": 0.0, "max": 1.0},
            {"key": "max_output_tokens", "label": "Max Output Tokens", "type": "number", "default": 4096},
        ],
    },
    "google": {
        "id": "google",
        "name": "Google Gemini",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "Google Gemini API via Generative Language endpoints.",
        "credentials": [
            {"key": "api_key", "label": "Google AI API Key", "type": "password", "required": True, "placeholder": "AIza..."},
        ],
        "config": [
            {"key": "model", "label": "Default Model ID", "type": "text", "default": "gemini-2.0-flash", "placeholder": "gemini-2.0-flash"},
            {"key": "temperature", "label": "Default Temperature", "type": "number", "default": 0.7, "step": 0.05, "min": 0.0, "max": 2.0},
            {"key": "max_output_tokens", "label": "Max Output Tokens", "type": "number", "default": 4096},
        ],
    },
    "modal_vllm": {
        "id": "modal_vllm",
        "name": "Modal vLLM",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "Serverless vLLM high-throughput engine on Modal cloud GPU volumes.",
        "credentials": [
            {"key": "token_id", "label": "Modal Token ID", "type": "password", "required": True, "placeholder": "ak-..."},
            {"key": "token_secret", "label": "Modal Token Secret", "type": "password", "required": True, "placeholder": "as-..."},
        ],
        "config": [
            {"key": "app_name", "label": "Modal App Name", "type": "text", "default": "comfy-modal-vllm", "placeholder": "comfy-modal-vllm"},
            {"key": "model", "label": "Model ID", "type": "text", "placeholder": "Model ID"},
        ],
    },
    "modal_tts": {
        "id": "modal_tts",
        "name": "Modal Kokoro / TTS",
        "category": "tts",
        "worker_type": "tts",
        "capabilities": ["tts"],
        "description": "Serverless Text-to-Speech audio synthesis powered by Kokoro on Modal.",
        "credentials": [
            {"key": "token_id", "label": "Modal Token ID", "type": "password", "required": True, "placeholder": "ak-..."},
            {"key": "token_secret", "label": "Modal Token Secret", "type": "password", "required": True, "placeholder": "as-..."},
        ],
        "config": [
            {"key": "app_name", "label": "Modal App Name", "type": "text", "default": "comfy-modal-tts", "placeholder": "comfy-modal-tts"},
        ],
    },
}


@router.get("/schemas")
async def get_provider_schemas():
    """Return declarative schemas and field definitions for supported provider engines."""
    return {
        "engines": ENGINE_SCHEMAS,
        "categories": [
            {"id": "image", "label": "Image Generation", "icon": "image"},
            {"id": "llm", "label": "Language Models (LLM)", "icon": "message-square"},
            {"id": "tts", "label": "Voice & Audio (TTS)", "icon": "mic"},
        ],
    }


@router.post("/test-connection")
async def test_provider_connection(request: TestConnectionRequest):
    """Test connection and authentication for an engine configuration without saving."""
    from services.engines.engine_factory import can_create_engine, get_engine, invalidate_engine

    schema = ENGINE_SCHEMAS.get(request.type)
    worker_type = schema.get("worker_type", "image") if schema else "image"
    temp_id = f"__test_conn_{int(time.monotonic() * 1000)}__"
    mock_provider = SimpleNamespace(
        id=temp_id,
        type=request.type,
        worker_type=worker_type,
        capabilities=[worker_type],
        credentials=request.credentials,
        config=request.config,
    )

    if not can_create_engine(mock_provider):
        return {
            "healthy": False,
            "status": "unhealthy",
            "ready": False,
            "latency_ms": None,
            "error": "Required credentials or configuration missing for this engine",
        }

    try:
        engine = get_engine(temp_id, mock_provider)
        if not engine:
            return {
                "healthy": False,
                "status": "unhealthy",
                "ready": False,
                "latency_ms": None,
                "error": "Failed to initialize engine",
            }

        health = await asyncio.wait_for(engine.check_health(), timeout=15.0)
        is_healthy = bool(health.get("ready") or health.get("status") == "healthy")
        return {
            "healthy": is_healthy,
            "status": health.get("status", "healthy" if is_healthy else "unhealthy"),
            "ready": is_healthy,
            "latency_ms": health.get("latency_ms"),
            "details": health,
            "error": health.get("error"),
        }
    except Exception as exc:
        return {
            "healthy": False,
            "status": "unhealthy",
            "ready": False,
            "latency_ms": None,
            "error": str(exc),
        }
    finally:
        invalidate_engine(temp_id)


@router.post("/{provider_id}/test")
async def test_existing_provider(provider_id: str, session: Session = Depends(get_session)):
    """Test connection and health of an existing registered provider."""
    provider = session.get(Provider, provider_id)
    if not provider:
        return {"healthy": False, "status": "not_found", "error": f"Provider '{provider_id}' not found"}

    from services.engines.engine_factory import can_create_engine, get_engine

    if can_create_engine(provider):
        engine = get_engine(provider_id, provider)
        if engine:
            try:
                health = await asyncio.wait_for(engine.check_health(), timeout=15.0)
                is_healthy = bool(health.get("ready") or health.get("status") == "healthy")
                return {
                    "healthy": is_healthy,
                    "status": health.get("status", "healthy" if is_healthy else "unhealthy"),
                    "ready": is_healthy,
                    "latency_ms": health.get("latency_ms"),
                    "details": health,
                    "error": health.get("error"),
                }
            except Exception as exc:
                return {
                    "healthy": False,
                    "status": "unhealthy",
                    "ready": False,
                    "latency_ms": None,
                    "error": str(exc),
                }

    # Fallback to ping_provider
    return await ping_provider(provider_id, session)


@router.get("/")
async def list_providers(session: Session = Depends(get_session)):
    """List all providers."""
    service = get_provider_service(session)
    providers = await service.list_providers()
    status_service = get_provider_status_service(session)
    records = await status_service.build_provider_records(providers)
    return {"providers": records, "count": len(records)}


@router.post("/")
async def create_provider(
    request: ProviderRequest,
    session: Session = Depends(get_session)
):
    """Create a new provider."""
    service = get_provider_service(session)
    payload = request.model_dump()
    # The wire field is `declared_capabilities`; the service's normalizer and
    # the DB column both call it `capabilities`. Renamed here rather than in
    # the service so the one place that owns the vocabulary is this one.
    payload["capabilities"] = payload.pop("declared_capabilities", None)
    provider = await service.create_provider(payload)
    await _republish_known_provider_hosts()
    status_service = get_provider_status_service(session)
    return await status_service.build_provider_record(provider.id, provider=provider)


@router.get("/{provider_id}")
async def get_provider(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Get a provider by ID."""
    status_service = get_provider_status_service(session)
    return await status_service.build_provider_record(provider_id)


@router.put("/{provider_id}")
async def update_provider(
    provider_id: str,
    request: ProviderUpdateRequest,
    session: Session = Depends(get_session)
):
    """Update a provider."""
    service = get_provider_service(session)
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    if "declared_capabilities" in updates:
        updates["capabilities"] = updates.pop("declared_capabilities")
    provider = await service.update_provider(provider_id, updates)
    await _republish_known_provider_hosts()
    # Credentials/config may have rotated: drop the cached in-process engine
    # (and its health verdict) so the next use rebuilds from the new values.
    from services.engines.engine_factory import invalidate_engine
    invalidate_engine(provider_id)
    invalidate_provider_status_caches(provider_id)
    status_service = get_provider_status_service(session)
    return await status_service.build_provider_record(provider.id, provider=provider)


# PATCH alias for frontend compatibility
@router.patch("/{provider_id}")
async def patch_provider(
    provider_id: str,
    request: ProviderUpdateRequest,
    session: Session = Depends(get_session)
):
    """Update a provider (PATCH alias)."""
    return await update_provider(provider_id, request, session)


@router.post("/{provider_id}/worker-token")
async def mint_provider_worker_token(provider_id: str, session: Session = Depends(get_session)):
    """Mint (or rotate) the external-worker token for a provider.

    The `/ws/worker/{provider_id}` WebSocket authenticates against
    `config.worker_token`, and nothing could produce that key — so the check could
    only ever fail, no worker could register, and the `external_worker` runtime
    mode was unreachable. This is the missing producer.

    The token is returned in this response and is not readable again: minting
    again rotates it, which is also how a leaked token is invalidated.
    """
    service = get_provider_service(session)
    token = await service.mint_worker_token(provider_id)
    return {"provider_id": provider_id, "worker_token": token}


@router.delete("/{provider_id}/worker-token")
async def revoke_provider_worker_token(provider_id: str, session: Session = Depends(get_session)):
    """Revoke the external-worker token, disabling the mode for this provider."""
    service = get_provider_service(session)
    revoked = await service.revoke_worker_token(provider_id)
    return {"provider_id": provider_id, "revoked": revoked}


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    session: Session = Depends(get_session)
):
    """Delete a provider."""
    service = get_provider_service(session)
    await service.delete_provider(provider_id)
    from services.engines.engine_factory import invalidate_engine
    invalidate_engine(provider_id)
    invalidate_provider_status_caches(provider_id)
    await _republish_known_provider_hosts()
    return {"status": "success"}


