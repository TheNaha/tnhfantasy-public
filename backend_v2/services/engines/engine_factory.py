"""
In-Process Engine Factory and Registry.

Manages the lifecycle, caching, and credential resolution for InProcessEngine instances
(ModalEngine, DirectComfyEngine, OpenAICompatLLMEngine, ModalVLLMEngine, ModalTTSEngine).
Resolves credentials from provider DB models, .env.<provider_id> files, and system environment variables.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from cachetools import TTLCache

from infrastructure.logging import get_logger
from services.engines.base import InProcessEngine
from services.engines.beam_engine import BeamEngine
from services.engines.direct_comfy_engine import DirectComfyEngine
from services.engines.llm_engine import ModalVLLMEngine, OpenAICompatLLMEngine, AnthropicLLMEngine, GoogleLLMEngine
from services.engines.modal_engine import HAS_MODAL, ModalEngine
from services.engines.modal_tts_engine import ModalTTSEngine
from services.engines.registry import (
    resolve_provider_type,
    supports_setup as _registry_supports_setup,
)

logger = get_logger("engine_factory")


def _parse_positive_float(raw: str | None, default: float) -> float:
    try:
        value = float(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# Engine instances cache credentials and resolved config, so entries expire:
# an out-of-band credential rotation (env-file edit without a process
# restart) self-heals at worst one TTL late. API-driven PATCH/DELETE calls
# invalidate_engine() for the immediate path. Frozen at import by design
# (TTLCache takes ttl once): changing COMFY_ENGINE_CACHE_TTL_SECONDS
# requires a process restart. Env-only like the other COMFY_* operational
# knobs — see use_in_process_engines() in provider_runtime.py.
ENGINE_CACHE_TTL_SECONDS = _parse_positive_float(
    os.getenv("COMFY_ENGINE_CACHE_TTL_SECONDS"), 1800.0
)
_ENGINE_CACHE: TTLCache = TTLCache(maxsize=128, ttl=ENGINE_CACHE_TTL_SECONDS)

# Locations to search for .env files
#
# The /comfyui path is where the Docker volume mount of the project root lives
# (read-only). Without it, per-provider credential files like .env.modal-zetsuke
# — which sit at the host project root and are only referenced by the *now
# deprecated* provider container services as env_file — are invisible to the
# backend, and can_create_engine() returns False for the existing Modal/Beam
# providers, causing them to silently fall back to container_http mode.
# A non-existent path is harmless (Path.is_file() returns False).
_ENV_SEARCH_PATHS = [
    Path.cwd(),
    Path(__file__).resolve().parent.parent.parent,         # backend_v2/
    Path(__file__).resolve().parent.parent.parent.parent,  # comfyui stack root
    Path(os.getenv("COMFY_PROVIDER_ENV_PATH", "/comfyui")),
]


def _parse_env_file(file_path: Path) -> Dict[str, str]:
    """Parse a simple KEY=VALUE format .env file without external dependencies."""
    env_vars: Dict[str, str] = {}
    if not file_path.is_file():
        return env_vars

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key:
                        env_vars[key] = val
    except Exception as exc:
        logger.warning("env_file_parse_error", path=str(file_path), error=str(exc))
    return env_vars


def get_provider_env(provider_id: str) -> Dict[str, str]:
    """
    Search for .env.<provider_id> in candidate directories.
    Handles variations like '-' vs '_'.
    """
    candidates = [
        f".env.{provider_id}",
        f".env.{provider_id.replace('_', '-')}",
        f".env.{provider_id.replace('-', '_')}",
    ]
    for base_dir in _ENV_SEARCH_PATHS:
        for candidate in candidates:
            file_path = base_dir / candidate
            if file_path.is_file():
                return _parse_env_file(file_path)
    return {}


def can_create_engine(provider: Any) -> bool:
    """Check if the necessary credentials or URLs exist to construct an in-process engine.

    Routing (which provider identity maps to which engine type) lives in
    registry.resolve_provider_type — this function only checks that the
    credentials/URLs the resolved type needs are present.
    """
    if not provider:
        return False
    provider_id = getattr(provider, "id", "")
    provider_type = getattr(provider, "type", "")
    worker_type = getattr(provider, "worker_type", "")
    capabilities = getattr(provider, "capabilities", None) or []
    creds = getattr(provider, "credentials", None) or {}
    config = getattr(provider, "config", None) or {}
    env_vars = get_provider_env(provider_id)

    rtype = resolve_provider_type(provider_type, provider_id, worker_type, capabilities)
    if rtype is None:
        return False

    token_id = (
        creds.get("token_id")
        or creds.get("MODAL_TOKEN_ID")
        or env_vars.get("MODAL_TOKEN_ID")
        or env_vars.get("token_id")
        or os.getenv("MODAL_TOKEN_ID")
    )
    token_secret = (
        creds.get("token_secret")
        or creds.get("MODAL_TOKEN_SECRET")
        or env_vars.get("MODAL_TOKEN_SECRET")
        or env_vars.get("token_secret")
        or os.getenv("MODAL_TOKEN_SECRET")
    )

    # TTS: Modal credentials only.
    if rtype == "modal_tts":
        return bool(HAS_MODAL and token_id and token_secret)

    # Hosted LLM: each wire protocol authenticates with its own key.
    # (Checked before the OpenAICompat base_url fallback so a stray
    # base_url can never misroute them to the wrong protocol.)
    if rtype == "anthropic":
        api_key = (
            creds.get("api_key")
            or creds.get("ANTHROPIC_API_KEY")
            or env_vars.get("ANTHROPIC_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
        )
        return bool(api_key)
    if rtype == "google":
        api_key = (
            creds.get("api_key")
            or creds.get("GOOGLE_API_KEY")
            or env_vars.get("GOOGLE_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )
        return bool(api_key)
    if rtype in ("openai_compat", "ollama"):
        base_url = (
            config.get("base_url")
            or config.get("api_base")
            or config.get("endpoint_url")
            or config.get("openai_api_base")
            or creds.get("base_url")
            or creds.get("api_base")
            or creds.get("endpoint_url")
            or env_vars.get("OPENAI_API_BASE")
            or env_vars.get("BASE_URL")
            or os.getenv("OPENAI_API_BASE")
        )
        return bool(base_url)

    # Serverless LLM (vLLM on Modal): Modal credentials. Both the
    # modal_vllm and modal_llm specs share the ModalVLLMEngine class.
    if rtype in ("modal_vllm", "modal_llm"):
        return bool(HAS_MODAL and token_id and token_secret)

    # Modal image.
    if rtype == "modal":
        return bool(HAS_MODAL and token_id and token_secret)

    # Beam image (serverless REST + websocket, no modal package).
    if rtype == "beam":
        beam_key = (
            creds.get("api_key")
            or creds.get("BEAM_API_KEY")
            or env_vars.get("BEAM_API_KEY")
            or os.getenv("BEAM_API_KEY")
        )
        gpu_url = (
            config.get("gpu_url")
            or creds.get("gpu_url")
            or env_vars.get("BEAM_GPU_URL")
            or os.getenv("BEAM_GPU_URL")
        )
        storage_url = (
            config.get("storage_url")
            or creds.get("storage_url")
            or env_vars.get("BEAM_STORAGE_URL")
            or os.getenv("BEAM_STORAGE_URL")
        )
        return bool(beam_key and gpu_url and storage_url)

    # Direct ComfyUI (plain) or RemoteComfy (ComfyUI + agent sidecar).
    if rtype in ("direct_url", "remote_comfy"):
        # Parity with get_engine below which defaults unset URL to
        # http://localhost:8188: a Direct provider is always constructible.
        return True

    return False


def engine_supports_setup(provider: Any) -> bool:
    """Whether the in-process engine for this provider implements setup.

    Routing lives in registry.resolve_provider_type and the per-type verdict
    in registry.supports_setup — image engines and modal_vllm/modal_llm own
    storage that needs initialising; Direct is trivially true (setup_models
    is a no-op success without an agent); hosted LLM and TTS inherit the
    base setup_models which reports False.
    Callers must still gate on can_create_engine first.
    """
    if not provider:
        return False
    rtype = resolve_provider_type(
        getattr(provider, "type", ""),
        getattr(provider, "id", ""),
        getattr(provider, "worker_type", ""),
        getattr(provider, "capabilities", None) or [],
    )
    return _registry_supports_setup(rtype)


def get_engine(provider_id: str, provider: Optional[Any] = None) -> Optional[InProcessEngine]:
    """
    Retrieve or construct an InProcessEngine instance for provider_id.
    Instances are cached by provider_id.
    """
    if provider_id in _ENGINE_CACHE:
        return _ENGINE_CACHE[provider_id]

    if provider is None:
        try:
            from infrastructure.deps import get_session_sync
            from infrastructure.repositories import ProviderRepository

            session = get_session_sync()
            try:
                repo = ProviderRepository(session)
                provider = repo.get_by_id(provider_id)
            finally:
                session.close()
        except Exception as exc:
            logger.debug("engine_factory_db_lookup_failed", provider_id=provider_id, error=str(exc))

    provider_type = getattr(provider, "type", "") if provider else ""
    worker_type = getattr(provider, "worker_type", "") if provider else ""
    capabilities = getattr(provider, "capabilities", None) or [] if provider else []
    creds = getattr(provider, "credentials", None) or {} if provider else {}
    config = getattr(provider, "config", None) or {} if provider else {}
    env_vars = get_provider_env(provider_id)

    # Single routing decision for all three entry points (can_create /
    # supports_setup / get_engine): registry owns the mapping, the blocks
    # below only construct.
    rtype = resolve_provider_type(provider_type, provider_id, worker_type, capabilities)
    if rtype is None:
        return None

    token_id = (
        creds.get("token_id")
        or creds.get("MODAL_TOKEN_ID")
        or env_vars.get("MODAL_TOKEN_ID")
        or env_vars.get("token_id")
        or os.getenv("MODAL_TOKEN_ID")
    )
    token_secret = (
        creds.get("token_secret")
        or creds.get("MODAL_TOKEN_SECRET")
        or env_vars.get("MODAL_TOKEN_SECRET")
        or env_vars.get("token_secret")
        or os.getenv("MODAL_TOKEN_SECRET")
    )

    # 1. TTS Provider
    if rtype == "modal_tts":
        if token_id and token_secret:
            app_name = (
                config.get("app_name")
                or env_vars.get("MODAL_TTS_APP_NAME")
                or os.getenv("MODAL_TTS_APP_NAME")
                or "comfy-modal-tts"
            )
            cls_name = (
                config.get("cls_name")
                or env_vars.get("MODAL_TTS_CLASS")
                or os.getenv("MODAL_TTS_CLASS")
                or "TTSWorker"
            )
            storage_cls_name = (
                config.get("storage_cls_name")
                or env_vars.get("MODAL_TTS_STORAGE_CLASS")
                or os.getenv("MODAL_TTS_STORAGE_CLASS")
                or "TTSFileStorage"
            )
            engine = ModalTTSEngine(
                provider_id=provider_id,
                token_id=token_id,
                token_secret=token_secret,
                app_name=app_name,
                cls_name=cls_name,
                storage_cls_name=storage_cls_name,
            )
            _ENGINE_CACHE[provider_id] = engine
            return engine

    # 2. LLM Provider (serverless vLLM, hosted APIs, OpenAI-compat local)
    if rtype in ("openai_compat", "ollama", "anthropic", "google", "modal_vllm", "modal_llm"):
        if rtype in ("modal_vllm", "modal_llm"):
            app_name = (
                config.get("app_name")
                or env_vars.get("MODAL_LLM_APP_NAME")
                or os.getenv("MODAL_LLM_APP_NAME")
                or env_vars.get("MODAL_APP_NAME")
                or os.getenv("MODAL_APP_NAME")
                or "vllm-modal-stack"
            )
            cls_name = (
                config.get("cls_name")
                or env_vars.get("MODAL_LLM_CLASS")
                or os.getenv("MODAL_LLM_CLASS")
                or "VLLMEngine"
            )
            engine = ModalVLLMEngine(
                provider_id=provider_id,
                token_id=token_id,
                token_secret=token_secret,
                app_name=app_name,
                cls_name=cls_name,
            )
            _ENGINE_CACHE[provider_id] = engine
            return engine

        # Hosted LLM APIs get their own engines (correct wire protocol).
        # Checked before the OpenAICompat base_url fallback so a stray
        # base_url on the provider can never misroute them.
        if provider_type == "anthropic":
            api_key = (
                creds.get("api_key")
                or creds.get("ANTHROPIC_API_KEY")
                or env_vars.get("ANTHROPIC_API_KEY")
                or os.getenv("ANTHROPIC_API_KEY")
            )
            if api_key:
                default_model = (
                    config.get("default_model")
                    or config.get("model")
                    or env_vars.get("ANTHROPIC_MODEL")
                    or "claude-3-haiku-20240307"
                )
                engine = AnthropicLLMEngine(
                    provider_id=provider_id,
                    api_key=api_key,
                    default_model=default_model,
                )
                _ENGINE_CACHE[provider_id] = engine
                return engine
            return None

        if provider_type in ("google", "gemini"):
            api_key = (
                creds.get("api_key")
                or creds.get("GOOGLE_API_KEY")
                or env_vars.get("GOOGLE_API_KEY")
                or os.getenv("GOOGLE_API_KEY")
            )
            if api_key:
                default_model = (
                    config.get("default_model")
                    or config.get("model")
                    or env_vars.get("GOOGLE_MODEL")
                    or "gemini-1.5-flash"
                )
                engine = GoogleLLMEngine(
                    provider_id=provider_id,
                    api_key=api_key,
                    default_model=default_model,
                )
                _ENGINE_CACHE[provider_id] = engine
                return engine
            return None

        base_url = (
            env_vars.get("OPENAI_API_BASE")
            or env_vars.get("BASE_URL")
            or os.getenv("OPENAI_API_BASE")
            or config.get("base_url")
            or config.get("api_base")
            or config.get("endpoint_url")
            or config.get("openai_api_base")
            or creds.get("base_url")
            or creds.get("api_base")
            or creds.get("endpoint_url")
        )
        if base_url:
            api_key = (
                creds.get("api_key")
                or creds.get("OPENAI_API_KEY")
                or env_vars.get("OPENAI_API_KEY")
                or env_vars.get("API_KEY")
                or os.getenv("OPENAI_API_KEY")
            )
            if not api_key and (provider_type == "ollama" or ":11434" in (base_url or "")):
                api_key = "ollama"
            default_model = (
                config.get("default_model")
                or config.get("model")
                or env_vars.get("OPENAI_MODEL")
                or env_vars.get("MODEL")
                or env_vars.get("LLM_MODEL")
                or os.getenv("LLM_MODEL")
                or "default-model"
            )
            engine = OpenAICompatLLMEngine(
                provider_id=provider_id,
                base_url=base_url,
                api_key=api_key,
                default_model=default_model,
            )
            _ENGINE_CACHE[provider_id] = engine
            return engine

    # 3. Modal Image Provider
    if rtype == "modal":
        app_name = (
            config.get("app_name")
            or env_vars.get("MODAL_APP_NAME")
            or os.getenv("MODAL_APP_NAME")
            or "comfy-modal-stack"
        )
        hf_token = (
            creds.get("hf_token")
            or env_vars.get("HF_TOKEN")
            or os.getenv("HF_TOKEN")
        )
        civitai_token = (
            creds.get("civitai_token")
            or env_vars.get("CIVITAI_TOKEN")
            or os.getenv("CIVITAI_TOKEN")
        )
        # Per-provider config is source of truth for the snapshot flag
        # (registry default False); env is fallback for legacy deployments.
        if "enable_memory_snapshot" in config:
            raw_snapshot = config.get("enable_memory_snapshot")
            if isinstance(raw_snapshot, str):
                enable_snapshot: bool | None = raw_snapshot.strip().lower() in ("true", "1", "yes")
            elif raw_snapshot is None:
                enable_snapshot = None
            else:
                enable_snapshot = bool(raw_snapshot)
        else:
            raw_env = (env_vars.get("ENABLE_MEMORY_SNAPSHOT") or os.getenv("ENABLE_MEMORY_SNAPSHOT") or "").strip().lower()
            enable_snapshot = raw_env in ("true", "1", "yes") if raw_env else False
        if token_id and token_secret:
            engine = ModalEngine(
                provider_id=provider_id,
                token_id=token_id,
                token_secret=token_secret,
                app_name=app_name,
                hf_token=hf_token,
                civitai_token=civitai_token,
                enable_memory_snapshot=enable_snapshot,
            )
            _ENGINE_CACHE[provider_id] = engine
            return engine

    # 3b. Beam Image Provider (serverless REST + websocket, no modal package)
    if rtype == "beam":
        beam_key = (
            creds.get("api_key")
            or creds.get("BEAM_API_KEY")
            or env_vars.get("BEAM_API_KEY")
            or os.getenv("BEAM_API_KEY")
        )
        gpu_url = (
            config.get("gpu_url")
            or creds.get("gpu_url")
            or env_vars.get("BEAM_GPU_URL")
            or os.getenv("BEAM_GPU_URL")
        )
        storage_url = (
            config.get("storage_url")
            or creds.get("storage_url")
            or env_vars.get("BEAM_STORAGE_URL")
            or os.getenv("BEAM_STORAGE_URL")
        )
        download_url = (
            config.get("download_url")
            or creds.get("download_url")
            or env_vars.get("BEAM_DOWNLOAD_URL")
            or os.getenv("BEAM_DOWNLOAD_URL")
            or ""
        )
        extractor_url = (
            config.get("extractor_url")
            or creds.get("extractor_url")
            or env_vars.get("BEAM_EXTRACTOR_URL")
            or os.getenv("BEAM_EXTRACTOR_URL")
            or ""
        )
        workspace_id = (
            creds.get("workspace_id")
            or config.get("workspace_id")
            or env_vars.get("BEAM_WORKSPACE_ID")
            or os.getenv("BEAM_WORKSPACE_ID")
            or ""
        )
        hf_token = (
            creds.get("hf_token")
            or env_vars.get("HF_TOKEN")
            or os.getenv("HF_TOKEN")
            or ""
        )
        civitai_token = (
            creds.get("civitai_token")
            or env_vars.get("CIVITAI_TOKEN")
            or os.getenv("CIVITAI_TOKEN")
            or ""
        )
        if beam_key and gpu_url and storage_url:
            engine = BeamEngine(
                provider_id=provider_id,
                api_key=beam_key,
                workspace_id=workspace_id,
                gpu_url=gpu_url,
                storage_url=storage_url,
                download_url=download_url,
                extractor_url=extractor_url,
                hf_token=hf_token,
                civitai_token=civitai_token,
                gpu_type=(
                    config.get("gpu_type")
                    or creds.get("gpu_type")
                    or env_vars.get("BEAM_GPU_TYPE")
                    or os.getenv("BEAM_GPU_TYPE")
                    or "RTX4090"
                ),
            )
            _ENGINE_CACHE[provider_id] = engine
            return engine
        return None

    # 4. Direct Comfy Provider (plain, or + agent sidecar for remote_comfy)
    if rtype in ("direct_url", "remote_comfy"):
        comfy_url = (
            config.get("comfy_url")
            or config.get("comfyui_url")
            or config.get("endpoint_url")
            or creds.get("comfy_url")
            or creds.get("endpoint_url")
            or env_vars.get("COMFYUI_URL")
            or os.getenv("COMFYUI_URL")
            or "http://localhost:8188"
        )
        api_key = (
            creds.get("api_key")
            or creds.get("comfyui_api_key")
            or creds.get("agent_api_key")
            or config.get("api_key")
            or config.get("comfyui_api_key")
            or env_vars.get("COMFYUI_API_KEY")
            or os.getenv("COMFYUI_API_KEY")
        )
        stall_timeout_raw = config.get("stall_timeout") or env_vars.get("COMFYUI_STALL_TIMEOUT", 300.0)
        try:
            stall_timeout = float(stall_timeout_raw)
        except (TypeError, ValueError):
            logger.warning(
                "engine_factory_stall_timeout_invalid",
                provider_id=provider_id,
                raw=stall_timeout_raw,
            )
            stall_timeout = 300.0
        agent_url = (
            config.get("agent_url")
            or config.get("remote_agent_url")
            or creds.get("agent_url")
            or creds.get("remote_agent_url")
            or env_vars.get("REMOTE_AGENT_URL")
            or env_vars.get("COMFYUI_AGENT_URL")
            or os.getenv("REMOTE_AGENT_URL")
            or ""
        )
        agent_token = (
            creds.get("agent_token")
            or creds.get("remote_agent_token")
            or config.get("agent_token")
            or config.get("remote_agent_token")
            or env_vars.get("REMOTE_AGENT_TOKEN")
            or env_vars.get("COMFYUI_AGENT_TOKEN")
            or os.getenv("REMOTE_AGENT_TOKEN")
            or ""
        )
        if (
            not agent_url
            and (
                provider_type == "remote_comfy"
                or "remote_comfy" in provider_id
                or "remote-comfy" in provider_id
            )
        ):
            # The old remote_comfy container defaulted REMOTE_AGENT_URL to
            # http://localhost:8001. An empty agent_url silently degrades the
            # engine to the direct_url shape (no mutation support, empty
            # agent listings read as success); keep the old default and say
            # so loudly instead.
            agent_url = "http://localhost:8001"
            logger.warning(
                "engine_factory_agent_url_default",
                provider_id=provider_id,
                agent_url=agent_url,
            )

        engine = DirectComfyEngine(
            provider_id=provider_id,
            comfy_url=comfy_url,
            api_key=api_key,
            stall_timeout=stall_timeout,
            agent_url=agent_url,
            agent_token=agent_token,
            hf_token=(
                creds.get("hf_token")
                or env_vars.get("HF_TOKEN")
                or os.getenv("HF_TOKEN")
                or ""
            ),
            civitai_token=(
                creds.get("civitai_token")
                or env_vars.get("CIVITAI_TOKEN")
                or os.getenv("CIVITAI_TOKEN")
                or ""
            ),
        )
        _ENGINE_CACHE[provider_id] = engine
        return engine

    return None


def register_engine(provider_id: str, engine: InProcessEngine) -> None:
    """Manually register an in-process engine (e.g. for testing)."""
    _ENGINE_CACHE[provider_id] = engine


def _close_engine(engine) -> None:
    close = getattr(engine, "close", None)
    if close is None:
        return
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(close())
        except Exception:
            pass
        return
    loop.create_task(close())


def clear_engine_cache() -> None:
    """Clear all cached engine instances, closing any HTTP clients."""
    for engine in list(_ENGINE_CACHE.values()):
        _close_engine(engine)
    _ENGINE_CACHE.clear()


def invalidate_engine(provider_id: str) -> None:
    """Drop one provider's cached engine so the next use rebuilds it.

    Call after credential/config rotation (provider PATCH, token refresh):
    a cached engine otherwise keeps serving with stale credentials until
    the cache TTL expires. (Unbuilt engines are never cached, so a failed
    `get_engine` returning None is *not* sticky — only successful builds
    need invalidating.) The load-balancer health entry goes with it so the
    next dispatch re-probes instead of trusting a verdict for the old config.
    """
    _stale = _ENGINE_CACHE.pop(provider_id, None)
    if _stale is not None:
        _close_engine(_stale)
    try:
        from services.load_balancer import _provider_health_cache

        _provider_health_cache.pop(f"in_process:{provider_id}", None)
    except Exception:
        pass
