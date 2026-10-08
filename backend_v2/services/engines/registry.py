"""
Canonical engine registry: single source of truth for provider types.

`ENGINE_SPECS` owns the declarative spec for every in-process engine:
UI schema (credentials/config fields), routing metadata (category,
worker_type, capabilities), the engine class name, whether it manages
model files, and accepted credential/config aliases for legacy payloads
(e.g. `endpoint_url` → `base_url`).

`api/routes/providers/crud.py` builds its `ENGINE_SCHEMAS` response from
here so schema ↔ factory can never drift again. `engine_factory.py`
uses the alias maps when resolving credentials. `validate_provider_payload`
powers 422-on-save validation in the provider routes.
"""

from typing import Any, Dict, List, Optional

ENGINE_SPECS: Dict[str, Dict[str, Any]] = {
    "modal": {
        "id": "modal",
        "name": "Modal (ComfyUI)",
        "category": "image",
        "worker_type": "image",
        "capabilities": ["image"],
        "description": "Serverless ComfyUI execution on Modal cloud GPU workers with shared volume storage.",
        "engine": "ModalEngine",
        "manages_model_files": True,
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
        "aliases": {
            "credentials": {},
            "config": {},
        },
    },
    "beam": {
        "id": "beam",
        "name": "Beam.cloud (ComfyUI)",
        "category": "image",
        "worker_type": "image",
        "capabilities": ["image"],
        "description": "Serverless ComfyUI execution on Beam.cloud GPU endpoints with persistent storage volume.",
        "engine": "BeamEngine",
        "manages_model_files": True,
        "credentials": [
            {"key": "api_key", "label": "Beam API Key", "type": "password", "required": True, "placeholder": "beam_..."},
            {"key": "workspace_id", "label": "Workspace ID", "type": "text", "required": False, "placeholder": "Workspace ID"},
            {"key": "hf_token", "label": "HuggingFace Token", "type": "password", "required": False, "placeholder": "hf_..."},
            {"key": "civitai_token", "label": "CivitAI Token", "type": "password", "required": False, "placeholder": "CivitAI API token"},
        ],
        "config": [
            {"key": "gpu_url", "label": "GPU Realtime / Webhook URL", "type": "text", "required": True, "placeholder": "https://...beam.run"},
            {"key": "storage_url", "label": "Storage REST App URL", "type": "text", "required": True, "placeholder": "https://...beam.run"},
            {"key": "download_url", "label": "Downloader URL (Optional)", "type": "text", "required": False, "placeholder": "Defaults to Storage URL"},
            {"key": "gpu_type", "label": "GPU Accelerator Type", "type": "select", "default": "RTX4090", "options": ["RTX4090", "A10G", "A100", "H100"]},
        ],
        "aliases": {
            "credentials": {},
            "config": {},
        },
    },
    "direct_url": {
        "id": "direct_url",
        "name": "Direct ComfyUI Server",
        "category": "image",
        "worker_type": "image",
        "capabilities": ["image"],
        "description": "Direct HTTP & WebSocket connection to any running ComfyUI server instance.",
        "engine": "DirectComfyEngine",
        "manages_model_files": False,
        "credentials": [
            {"key": "comfyui_api_key", "label": "ComfyUI API Key", "type": "password", "required": False, "placeholder": "Optional auth token"},
            {"key": "agent_api_key", "label": "Remote Agent API Key", "type": "password", "required": False, "placeholder": "Optional agent auth token"},
        ],
        "config": [
            {"key": "comfy_url", "label": "ComfyUI Server URL", "type": "text", "required": True, "default": "http://localhost:8188", "placeholder": "http://localhost:8188"},
            {"key": "remote_agent_url", "label": "Remote Agent Sidecar URL", "type": "text", "required": False, "placeholder": "http://remote-host:8001"},
        ],
        "aliases": {
            "credentials": {
                "comfyui_api_key": ["api_key"],
                "agent_api_key": ["agent_token", "remote_agent_token"],
            },
            "config": {
                "comfy_url": ["comfyui_url", "endpoint_url", "base_url"],
                "remote_agent_url": ["agent_url"],
            },
        },
    },
    "remote_comfy": {
        "id": "remote_comfy",
        "name": "Remote ComfyUI (with Agent Sidecar)",
        "category": "image",
        "worker_type": "image",
        "capabilities": ["image"],
        "description": "Dedicated remote GPU server running ComfyUI alongside the TNHComfy Remote Agent sidecar.",
        "engine": "DirectComfyEngine",
        "manages_model_files": True,
        "credentials": [
            {"key": "remote_agent_token", "label": "Remote Agent Token", "type": "password", "required": False, "placeholder": "Optional agent auth token"},
            {"key": "comfyui_api_key", "label": "ComfyUI API Key", "type": "password", "required": False, "placeholder": "Optional Comfy API key"},
            {"key": "hf_token", "label": "HuggingFace Token", "type": "password", "required": False, "placeholder": "hf_..."},
            {"key": "civitai_token", "label": "CivitAI Token", "type": "password", "required": False, "placeholder": "CivitAI API token"},
        ],
        "config": [
            {"key": "comfy_url", "label": "ComfyUI Server URL", "type": "text", "required": True, "default": "http://remote-server:8188", "placeholder": "http://remote-server:8188"},
            {"key": "remote_agent_url", "label": "Remote Agent Sidecar URL", "type": "text", "required": False, "default": "http://remote-server:8001", "placeholder": "http://remote-server:8001"},
        ],
        "aliases": {
            "credentials": {
                "comfyui_api_key": ["api_key"],
                "remote_agent_token": ["agent_token"],
            },
            "config": {
                "comfy_url": ["comfyui_url", "endpoint_url", "base_url"],
                "remote_agent_url": ["agent_url"],
            },
        },
    },
    "openai_compat": {
        "id": "openai_compat",
        "name": "OpenAI / Local LLM (Ollama, vLLM, OpenRouter)",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "Standard OpenAI chat completion endpoint for local LLMs (Ollama, LM Studio) or hosted APIs.",
        "engine": "OpenAICompatLLMEngine",
        "manages_model_files": False,
        "credentials": [
            {"key": "api_key", "label": "API Key", "type": "password", "required": False, "placeholder": "sk-... (leave empty for local Ollama)"},
        ],
        "config": [
            {"key": "base_url", "label": "API Base URL", "type": "text", "required": True, "default": "http://localhost:11434/v1", "placeholder": "https://api.openai.com/v1"},
            {"key": "model", "label": "Default Model ID", "type": "text", "required": False, "placeholder": "e.g. llama3.2, mistral, gpt-4o"},
            {"key": "temperature", "label": "Default Temperature", "type": "number", "default": 0.7, "step": 0.05, "min": 0.0, "max": 2.0},
            {"key": "max_output_tokens", "label": "Max Output Tokens", "type": "number", "default": 4096},
        ],
        "aliases": {
            "credentials": {
                "api_key": ["openai_api_key"],
                "base_url": [],
            },
            "config": {
                "base_url": ["api_base", "endpoint_url", "openai_api_base"],
                "model": ["default_model"],
            },
        },
    },
    "ollama": {
        "id": "ollama",
        "name": "Ollama (Local LLM)",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "Local LLM runner via Ollama OpenAI-compatible endpoint (Llama 3, Mistral, Qwen, etc.).",
        "engine": "OpenAICompatLLMEngine",
        "manages_model_files": False,
        "credentials": [
            {"key": "api_key", "label": "API Key (Optional)", "type": "password", "required": False, "placeholder": "leave empty for local Ollama"},
        ],
        "config": [
            {"key": "base_url", "label": "Ollama Base URL", "type": "text", "required": True, "default": "http://localhost:11434/v1", "placeholder": "http://localhost:11434/v1"},
            {"key": "model", "label": "Default Model ID", "type": "text", "required": False, "placeholder": "e.g. llama3.2, mistral"},
            {"key": "temperature", "label": "Default Temperature", "type": "number", "default": 0.7, "step": 0.05, "min": 0.0, "max": 2.0},
            {"key": "max_output_tokens", "label": "Max Output Tokens", "type": "number", "default": 4096},
        ],
        "aliases": {
            "credentials": {
                "api_key": ["openai_api_key"],
            },
            "config": {
                "base_url": ["api_base", "endpoint_url", "openai_api_base"],
                "model": ["default_model"],
            },
        },
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "Anthropic Claude Messages API (Claude 3.5 Sonnet, Claude 3.5 Haiku, etc.).",
        "engine": "AnthropicLLMEngine",
        "manages_model_files": False,
        "credentials": [
            {"key": "api_key", "label": "Anthropic API Key", "type": "password", "required": True, "placeholder": "sk-ant-..."},
        ],
        "config": [
            {"key": "model", "label": "Default Model ID", "type": "text", "default": "claude-3-5-sonnet-latest", "placeholder": "claude-3-5-sonnet-latest"},
            {"key": "temperature", "label": "Default Temperature", "type": "number", "default": 0.7, "step": 0.05, "min": 0.0, "max": 1.0},
            {"key": "max_output_tokens", "label": "Max Output Tokens", "type": "number", "default": 4096},
        ],
        "aliases": {
            "credentials": {},
            "config": {
                "model": ["default_model"],
            },
        },
    },
    "google": {
        "id": "google",
        "name": "Google Gemini",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "Google Gemini API via Generative Language endpoints.",
        "engine": "GoogleLLMEngine",
        "manages_model_files": False,
        "credentials": [
            {"key": "api_key", "label": "Google AI API Key", "type": "password", "required": True, "placeholder": "AIza..."},
        ],
        "config": [
            {"key": "model", "label": "Default Model ID", "type": "text", "default": "gemini-2.0-flash", "placeholder": "gemini-2.0-flash"},
            {"key": "temperature", "label": "Default Temperature", "type": "number", "default": 0.7, "step": 0.05, "min": 0.0, "max": 2.0},
            {"key": "max_output_tokens", "label": "Max Output Tokens", "type": "number", "default": 4096},
        ],
        "aliases": {
            "credentials": {},
            "config": {
                "model": ["default_model"],
            },
        },
    },
    "modal_vllm": {
        "id": "modal_vllm",
        "name": "Modal vLLM",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "Serverless vLLM high-throughput engine on Modal cloud GPU volumes.",
        "engine": "ModalVLLMEngine",
        "manages_model_files": True,
        "credentials": [
            {"key": "token_id", "label": "Modal Token ID", "type": "password", "required": True, "placeholder": "ak-..."},
            {"key": "token_secret", "label": "Modal Token Secret", "type": "password", "required": True, "placeholder": "as-..."},
        ],
        "config": [
            {"key": "app_name", "label": "Modal App Name", "type": "text", "default": "comfy-modal-vllm", "placeholder": "comfy-modal-vllm"},
            {"key": "model", "label": "Model ID", "type": "text", "placeholder": "Model ID"},
        ],
        "aliases": {
            "credentials": {},
            "config": {
                "model": ["default_model"],
            },
        },
    },
    "modal_llm": {
        "id": "modal_llm",
        "name": "Modal LLM",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "Serverless LLM worker on Modal cloud GPUs (alias of Modal vLLM engine).",
        "engine": "ModalVLLMEngine",
        "manages_model_files": True,
        "credentials": [
            {"key": "token_id", "label": "Modal Token ID", "type": "password", "required": True, "placeholder": "ak-..."},
            {"key": "token_secret", "label": "Modal Token Secret", "type": "password", "required": True, "placeholder": "as-..."},
        ],
        "config": [
            {"key": "app_name", "label": "Modal App Name", "type": "text", "default": "comfy-modal-vllm", "placeholder": "comfy-modal-vllm"},
            {"key": "model", "label": "Model ID", "type": "text", "placeholder": "Model ID"},
        ],
        "aliases": {
            "credentials": {},
            "config": {
                "model": ["default_model"],
            },
        },
    },
    "modal_tts": {
        "id": "modal_tts",
        "name": "Modal Kokoro / TTS",
        "category": "tts",
        "worker_type": "tts",
        "capabilities": ["tts"],
        "description": "Serverless Text-to-Speech audio synthesis powered by Kokoro on Modal.",
        "engine": "ModalTTSEngine",
        "manages_model_files": False,
        "credentials": [
            {"key": "token_id", "label": "Modal Token ID", "type": "password", "required": True, "placeholder": "ak-..."},
            {"key": "token_secret", "label": "Modal Token Secret", "type": "password", "required": True, "placeholder": "as-..."},
        ],
        "config": [
            {"key": "app_name", "label": "Modal App Name", "type": "text", "default": "comfy-modal-tts", "placeholder": "comfy-modal-tts"},
        ],
        "aliases": {
            "credentials": {},
            "config": {},
        },
    },
}


def get_engine_spec(provider_type: str) -> Optional[Dict[str, Any]]:
    """Return the canonical spec for a provider type, or None when unknown."""
    if not provider_type:
        return None
    return ENGINE_SPECS.get(provider_type)


def list_engine_specs() -> List[Dict[str, Any]]:
    """Return all canonical specs in registry order."""
    return list(ENGINE_SPECS.values())


def ui_schemas() -> Dict[str, Dict[str, Any]]:
    """Project registry specs to the UI schema shape served by the API.

    Strips engine-internal keys (`engine`, `manages_model_files`, `aliases`)
    so the wire shape stays exactly what the frontend expects.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for key, spec in ENGINE_SPECS.items():
        out[key] = {
            "id": spec["id"],
            "name": spec["name"],
            "category": spec["category"],
            "worker_type": spec["worker_type"],
            "capabilities": spec["capabilities"],
            "description": spec["description"],
            "credentials": spec["credentials"],
            "config": spec["config"],
        }
    return out


def _field_present(
    fields: List[Dict[str, Any]],
    provided: Dict[str, Any],
    section_aliases: Dict[str, List[str]],
    other_section: Dict[str, Any],
) -> List[str]:
    """Return names of required fields missing from both sections.

    A field counts as present when its canonical key — or any of its
    aliases — appears non-empty in *either* the credentials or the config
    dict. Cross-section lookup matters because legacy providers stored
    URLs/keys on whichever side the old modal happened to write.
    A `required` field with a `default` is satisfiable without user input,
    so only required-without-default fields can fail.
    """
    missing: List[str] = []
    for field in fields:
        if not field.get("required"):
            continue
        if "default" in field:
            continue
        key = field["key"]
        candidates = [key] + list(section_aliases.get(key, []))
        found = any(
            (provided.get(c) or other_section.get(c))
            not in (None, "")
            for c in candidates
        )
        if not found:
            missing.append(key)
    return missing


def missing_provider_fields(
    provider_type: str,
    credentials: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Structured form of `validate_provider_payload` for status summaries.

    Returns `{"credentials": [...], "config": [...], "unknown_type": bool}`
    with the names of required-without-default fields missing from either
    section (aliases honoured). Unknown types report `unknown_type: True`
    with empty missing lists so callers can decide how to display them.
    """
    spec = get_engine_spec(provider_type)
    if spec is None:
        return {"credentials": [], "config": [], "unknown_type": True}
    creds = credentials or {}
    cfg = config or {}
    aliases = spec.get("aliases", {}) or {}
    return {
        "credentials": _field_present(
            spec.get("credentials", []), creds, aliases.get("credentials", {}), cfg
        ),
        "config": _field_present(
            spec.get("config", []), cfg, aliases.get("config", {}), creds
        ),
        "unknown_type": False,
    }


def validate_provider_payload(
    provider_type: str,
    credentials: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Validate a provider payload against its registry spec.

    Returns a list of human-readable error strings (empty = valid).
    Unknown types are an error; required-without-default credential and
    config fields must be present under their canonical key or an alias.
    """
    spec = get_engine_spec(provider_type)
    if spec is None:
        known = ", ".join(sorted(ENGINE_SPECS))
        return [f"Unknown provider type '{provider_type}'. Known types: {known}"]
    creds = credentials or {}
    cfg = config or {}
    aliases = spec.get("aliases", {}) or {}
    errors: List[str] = []
    for name in _field_present(
        spec.get("credentials", []), creds, aliases.get("credentials", {}), cfg
    ):
        errors.append(f"Missing required credential '{name}' for type '{provider_type}'")
    for name in _field_present(
        spec.get("config", []), cfg, aliases.get("config", {}), creds
    ):
        errors.append(f"Missing required config '{name}' for type '{provider_type}'")
    return errors
