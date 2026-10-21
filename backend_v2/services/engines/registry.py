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

# --------------------------------------------------------------------------
# The two axes a provider is described by.
#
# CATEGORY (what work it does) is stored in the `worker_type` column, kept under
# that name so no provider row or API payload has to move. Read it through
# `Provider.category`.
#
# TRANSPORT (how the backend reaches it) was never explicit — it was implied by
# the provider *type* string. That is why the provider page read as ambiguous and
# why four empty cells in the matrix below were invisible: a "Beam LLM" was not
# a thing anyone could see was missing.
#
# The matrix is the contract the provider UI and the factory both read, so a
# missing cell is a hole in the product rather than a surprise at dispatch.
# --------------------------------------------------------------------------
TRANSPORT_MODAL = "modal"    # Modal serverless (Modal SDK -> app function)
TRANSPORT_BEAM = "beam"      # Beam serverless
TRANSPORT_REMOTE = "remote"  # our own container, deployed anywhere with Docker
TRANSPORT_DIRECT = "direct"  # straight to a hosted API protocol

TRANSPORTS = (TRANSPORT_MODAL, TRANSPORT_BEAM, TRANSPORT_REMOTE, TRANSPORT_DIRECT)

CATEGORY_IMAGE = "image"
CATEGORY_LLM = "llm"
CATEGORY_TTS = "tts"
CATEGORY_HYBRID = "hybrid"

#: transport -> (category -> provider type id), or None where the cell is empty.
#: A cell may name a *family* — a tuple of types that share the cell and differ
#: only in which API protocol they speak (the direct-LLM cell). `ENGINE_SPECS`
#: below stays the flat source of truth for each *type*; this is the question
#: "what can serve X over Y", answered in one place.
PROVIDER_MATRIX: Dict[str, Dict[str, Optional[str]]] = {
    TRANSPORT_MODAL: {
        CATEGORY_IMAGE: "modal",
        CATEGORY_LLM: "modal_llm",
        CATEGORY_TTS: "modal_tts",
        CATEGORY_HYBRID: None,
    },
    TRANSPORT_BEAM: {
        CATEGORY_IMAGE: "beam",
        CATEGORY_LLM: "beam_llm",
        CATEGORY_TTS: "beam_tts",
        CATEGORY_HYBRID: None,
    },
    TRANSPORT_REMOTE: {
        CATEGORY_IMAGE: "remote_comfy",
        CATEGORY_LLM: "remote_llm",
        CATEGORY_TTS: "remote_tts",
        CATEGORY_HYBRID: "remote_hybrid",
    },
    TRANSPORT_DIRECT: {
        CATEGORY_IMAGE: "direct_url",
        # A *family*, not one type: the direct-LLM cell is filled by several
        # provider types that differ only in which hosted API protocol they
        # speak. Listing them here rather than None keeps the cell filled — a
        # hostable OpenAI-compatible endpoint (a local vLLM, Ollama,
        # OpenRouter) is a real option, not a gap.
        CATEGORY_LLM: ("openai_compat", "ollama", "anthropic", "google"),
        CATEGORY_TTS: "direct_tts",
        CATEGORY_HYBRID: None,
    },
}

ENGINE_SPECS: Dict[str, Dict[str, Any]] = {
    "modal": {
        "id": "modal",
        "transport": "modal",
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
        "transport": "beam",
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
            # The engine reads this for `/object_info` and it has no form field,
            # so it fell back to `storage_url` — which serves no `/object_info`
            # and 404s. The node catalogue was therefore broken for every Beam
            # provider created through the Providers modal, while
            # `scripts/deploy.sh` and `deployables/README.md` both told the
            # operator to publish the URL they had no way to enter.
            {"key": "extractor_url", "label": "Extractor REST URL", "type": "text", "required": False, "placeholder": "https://...beam.run"},
            {"key": "gpu_type", "label": "GPU Accelerator Type", "type": "select", "default": "RTX4090", "options": ["RTX4090", "A10G", "A100", "H100"]},
        ],
        "aliases": {
            "credentials": {},
            "config": {},
        },
    },
    "direct_url": {
        "id": "direct_url",
        "transport": "direct",
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
        "transport": "remote",
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
        "transport": "direct",
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
        "transport": "direct",
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
        "transport": "direct",
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
        "transport": "direct",
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
    "modal_llm": {
        "id": "modal_llm",
        "transport": "modal",
        "name": "Modal llama.cpp",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "llama.cpp GGUF servers on Modal: one per role, scale-to-zero on its own idle timer.",
        "engine": "ModalLlamaCPPEngine",
        "manages_model_files": True,
        "credentials": [
            {"key": "token_id", "label": "Modal Token ID", "type": "password", "required": True, "placeholder": "ak-..."},
            {"key": "token_secret", "label": "Modal Token Secret", "type": "password", "required": True, "placeholder": "as-..."},
        ],
        "config": [
            # `tnh-llm` is what `deployables/modal/llm/app.py` publishes
            # (`APP_NAME`). This default is not cosmetic: the Providers modal
            # seeds every save from the schema defaults
            # (`ProviderModal.schemaConfigDefaults`), and `engine_factory`
            # reads `config["app_name"]` BEFORE its own fallback. A wrong
            # default here is therefore the app every UI-created `modal_llm`
            # provider dials, and the engine's own `tnh-llm` fallback becomes
            # unreachable through the UI. It read `comfy-modal-vllm` — the name
            # of the deleted vLLM-era worker — until `test_deployable_contract`
            # compared it against the deployable.
            {"key": "app_name", "label": "Modal App Name", "type": "text", "default": "tnh-llm", "placeholder": "tnh-llm"},
            {"key": "cls_name", "label": "Modal Class Name", "type": "text", "default": "ChatLLM", "placeholder": "ChatLLM"},
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
        "transport": "modal",
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
    # ------------------------------------------------------------------
    # The Beam / Remote cells for the LLM and TTS categories.
    #
    # These four were empty before this pass. The Beam integration only ever
    # spoke the ComfyUI WebSocket protocol, and the container path for LLM/TTS
    # was deleted in 9a91e6f2 and folded in-process. `remote_agent/` still owns
    # the HTTP/auth/storage shape, so the REMOTE engines reuse that and add only
    # the inference protocol each category needs.
    # ------------------------------------------------------------------
    "beam_llm": {
        "id": "beam_llm",
        "transport": "beam",
        "name": "Beam.cloud (LLM)",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "Serverless LLM on Beam.cloud: a llama.cpp or vLLM endpoint behind Beam's realtime handler.",
        "engine": "BeamLLMEngine",
        "manages_model_files": True,
        "credentials": [
            {"key": "api_key", "label": "Beam API Key", "type": "password", "required": True},
            {"key": "workspace_id", "label": "Workspace ID", "type": "text", "required": False},
        ],
        "config": [
            {"key": "gpu_url", "label": "Beam LLM Realtime URL", "type": "text", "required": True, "placeholder": "https://...beam.run"},
            {"key": "default_model", "label": "Default Model", "type": "text", "required": False, "placeholder": "rp"},
        ],
        "aliases": {"credentials": {}, "config": {}},
    },
    "beam_tts": {
        "id": "beam_tts",
        "transport": "beam",
        "name": "Beam.cloud (TTS)",
        "category": "tts",
        "worker_type": "tts",
        "capabilities": ["tts"],
        "description": "Serverless speech synthesis on Beam.cloud, streaming audio back over its realtime handler.",
        "engine": "BeamTTSEngine",
        "manages_model_files": False,
        "credentials": [
            {"key": "api_key", "label": "Beam API Key", "type": "password", "required": True},
        ],
        "config": [
            {"key": "gpu_url", "label": "Beam TTS Realtime URL", "type": "text", "required": True, "placeholder": "https://...beam.run"},
            {"key": "default_voice", "label": "Default Voice", "type": "text", "required": False},
        ],
        "aliases": {"credentials": {}, "config": {}},
    },
    "remote_llm": {
        "id": "remote_llm",
        "transport": "remote",
        "name": "Self-hosted LLM Container",
        "category": "llm",
        "worker_type": "llm",
        "capabilities": ["llm"],
        "description": "The TNHComfy LLM container, deployed on any Docker host with a GPU. OpenAI-compatible, speaks the remote_agent service token, and owns a models tree it can list, download into, validate and delete from — 1-to-1 with modal_llm.",
        "engine": "RemoteLLMEngine",
        # True, and it is the parity claim. The sidecar serves /list-models,
        # /download-model, /validate-models, /delete-model, /upload-file and
        # /setup in `llm` mode exactly as in `model` mode, and
        # `RemoteAgentFileMixin` is what calls them. This used to read False,
        # which made a `remote_llm` provider generate and nothing else while
        # `modal_llm` owned a models volume and overrode thirteen methods.
        "manages_model_files": True,
        "credentials": [
            {"key": "agent_token", "label": "Service Token", "type": "password", "required": True},
            {"key": "hf_token", "label": "HuggingFace Token", "type": "password", "required": False},
        ],
        "config": [
            {"key": "agent_url", "label": "Container URL", "type": "text", "required": True, "placeholder": "http://gpu-box:8001"},
            {"key": "default_model", "label": "Default Model", "type": "text", "required": False, "placeholder": "util"},
        ],
        "aliases": {
            "credentials": {"agent_token": ["remote_agent_token", "token"]},
            "config": {"agent_url": ["remote_agent_url", "url"]},
        },
    },
    "remote_tts": {
        "id": "remote_tts",
        "transport": "remote",
        "name": "Self-hosted TTS Container",
        "category": "tts",
        "worker_type": "tts",
        "capabilities": ["tts"],
        "description": "The TNHComfy TTS container, deployed on any Docker host with a GPU. Speaks the remote_agent service token and owns a storage root it can list, upload to and delete from — 1-to-1 with modal_tts.",
        "engine": "RemoteTTSEngine",
        # False, matching `modal_tts`: a TTS worker's storage root holds audio
        # clips, not a ComfyUI models tree. The engine still has the mixin's full
        # file surface (list/upload/stream/delete/setup) — `manages_model_files`
        # is about whether to walk CHECKPOINT_DIRECTORIES, not about capability.
        "manages_model_files": False,
        "credentials": [
            {"key": "agent_token", "label": "Service Token", "type": "password", "required": True},
        ],
        "config": [
            {"key": "agent_url", "label": "Container URL", "type": "text", "required": True, "placeholder": "http://gpu-box:8002"},
            {"key": "default_voice", "label": "Default Voice", "type": "text", "required": False},
        ],
        "aliases": {
            "credentials": {"agent_token": ["remote_agent_token", "token"]},
            "config": {"agent_url": ["remote_agent_url", "url"]},
        },
    },
    "direct_tts": {
        "id": "direct_tts",
        "transport": "direct",
        "name": "Direct ComfyUI (TTS)",
        "category": "tts",
        "worker_type": "tts",
        "capabilities": ["tts"],
        "description": "A ComfyUI rig that already serves speech. The workflow graph is the difference, not the machine; no model files of its own to reconcile.",
        "engine": "DirectTTSEngine",
        "manages_model_files": False,
        "credentials": [
            {"key": "comfyui_api_key", "label": "ComfyUI API Key", "type": "password", "required": False},
        ],
        "config": [
            {"key": "comfy_url", "label": "ComfyUI Server URL", "type": "text", "required": True, "default": "http://localhost:8188"},
            {"key": "default_voice", "label": "Default Voice", "type": "text", "required": False},
        ],
        "aliases": {"credentials": {}, "config": {}},
    },
    "remote_hybrid": {
        "id": "remote_hybrid",
        "transport": "remote",
        "name": "Self-hosted Hybrid Worker",
        "category": "hybrid",
        "worker_type": "hybrid",
        "capabilities": ["image", "llm", "tts"],
        "description": "Unified self-hosted worker running ComfyUI (image/TTS) and llama-server (LLM) on a single GPU node. Supports auto-detected hardware capability markers and VRAM scheduling.",
        "engine": "HybridRemoteEngine",
        "manages_model_files": True,
        "credentials": [
            {"key": "agent_token", "label": "Service Token", "type": "password", "required": True},
            {"key": "hf_token", "label": "HuggingFace Token", "type": "password", "required": False},
            {"key": "civitai_token", "label": "CivitAI Token", "type": "password", "required": False},
        ],
        "config": [
            {"key": "base_url", "label": "Worker Host URL (NetBird / Tunnel)", "type": "text", "required": True, "placeholder": "http://100.x.x.x"},
            {"key": "comfy_port", "label": "ComfyUI Port", "type": "number", "default": 8188},
            {"key": "agent_port", "label": "Agent Port", "type": "number", "default": 8001},
            {"key": "llm_port", "label": "LLM Port", "type": "number", "default": 8003},
            {"key": "concurrency_policy", "label": "Concurrency / VRAM Policy", "type": "select", "options": ["auto", "exclusive", "semi_concurrent", "concurrent"], "default": "auto", "help_text": "auto: auto-detect from GPU VRAM. exclusive: VRAM swap for L4/T4. semi_concurrent: concurrent RP + Comfy for A100-40GB. concurrent: unconstrained for A100-80GB."},
        ],
        "aliases": {
            "credentials": {"agent_token": ["remote_agent_token", "token"]},
            "config": {"base_url": ["url", "agent_url", "remote_agent_url"]},
        },
    },

}


def get_engine_spec(provider_type: str) -> Optional[Dict[str, Any]]:
    """Return the canonical spec for a provider type, or None when unknown."""
    if not provider_type:
        return None
    return ENGINE_SPECS.get(provider_type)


# ---------------------------------------------------------------------------
# Routing: single source of truth for provider → spec resolution.
#
# engine_factory.py previously repeated this routing in three places
# (can_create_engine / engine_supports_setup / get_engine) with prefix and
# capability fallbacks that could drift independently. All three now call
# resolve_provider_type() so the mapping lives here, next to the specs.
# ---------------------------------------------------------------------------

#: Legacy / shorthand type names that never got their own spec.
def resolve_transport(provider_type: Optional[str]) -> Optional[str]:
    """The transport a provider type uses, or None when the type is unknown.

    Reads the spec first, then the matrix. An unknown type resolves to None
    rather than to a guess: callers must treat None as "ask the registry", never
    as "direct", because guessing direct silently points a provider at the wrong
    protocol.
    """
    if not provider_type:
        return None
    # Resolve aliases first: `modal_vllm` is not a spec any more, but a row still
    # carrying it is a modal_llm row and must answer "modal", not None.
    resolved = _TYPE_ALIASES.get(provider_type, provider_type)
    spec = get_engine_spec(resolved) or {}
    transport = spec.get("transport")
    if transport:
        return transport
    for transport_name, cells in PROVIDER_MATRIX.items():
        for value in cells.values():
            if provider_type in _cell_provider_types(value):
                return transport_name
    return None


def _cell_provider_types(value: Any) -> List[str]:
    """The provider types occupying a matrix cell, empty list when unfilled."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def matrix_cells() -> List[Dict[str, Any]]:
    """Every (category, transport) cell, unfilled ones included.

    The provider UI renders from this so a cell with no provider type shows as
    unavailable with a reason, instead of not existing at all — which is how four
    cells went missing from the product without anyone noticing.

    `provider_types` is a list because one cell can hold a family (direct-LLM
    speaks several different hosted APIs); `provider_type` is the first member,
    kept for callers that want the simple case.
    """
    cells: List[Dict[str, Any]] = []
    for transport, columns in PROVIDER_MATRIX.items():
        for category, value in columns.items():
            types = _cell_provider_types(value)
            missing = [t for t in types if t not in ENGINE_SPECS]
            cells.append({
                "category": category,
                "transport": transport,
                "provider_types": types,
                "provider_type": types[0] if types else None,
                "filled": bool(types) and not missing,
            })
    return cells


#: Generic hosted-LLM types whose "vllm"-bearing id was historically a
#: mis-typed Modal vLLM pod. Narrow on purpose: an override that could reach a
#: transport type would re-label a `beam_llm`/`remote_llm` row as `modal_llm`,
#: which is precisely the ambiguity this pass exists to remove. `modal_vllm` is
#: absent because it is an alias now, and an alias never reaches this check.
_LEGACY_VLLM_MISTYPED = frozenset({"openai_compat", "ollama"})

#: The id has to name MODAL for the legacy rescue to apply.
#:
#: The rescue existed for a row whose generic hosted type was a mis-typed
#: Modal vLLM pod - the pod speaks the OpenAI API, so the row said
#: `openai_compat`, and the id said `vllm`.
#:
#: But `openai_compat` and `ollama` are ALSO what a legitimate SELF-HOSTED
#: vLLM says - that is what those types are for ("a local vLLM, Ollama,
#: OpenRouter"). So the rescue, as it stood, took every self-hosted vLLM
#: provider and re-labelled it `modal_llm`: the request went to a Modal
#: llama.cpp app instead of the operator's own box, at a different cost,
#: with no error and no log line. Measured on the resolver:
#:
#:     type='openai_compat'  id='selfhost-vllm'  ->  modal_llm   (wrong)
#:     type='ollama'         id='local-vllm'     ->  modal_llm   (wrong)
#:
#: So the id must ALSO say Modal for the rescue to fire. A self-hosted
#: provider's id says where it lives, and that is the only thing that
#: distinguishes the two cases.
_LEGACY_VLLM_MISTYPED_ID_MARKER = "modal"

_TYPE_ALIASES: Dict[str, str] = {
    # The direction of this alias was flipped on 2026-10-15. `modal_vllm` used
    # to be canonical with `modal_llm` folded into it, because the engine was a
    # vLLM pod. It has been llama.cpp since `deployables/modal/llm/app.py` was rewritten —
    # `ghcr.io/ggml-org/llama.cpp:server-cuda`, `llama-server` per role — so the
    # type that names the runtime honestly is the canonical one. Existing rows
    # carrying `modal_vllm` keep resolving, which is why this is an alias and
    # not a rename with a migration.
    "modal_vllm": "modal_llm",
    "tts": "modal_tts",
    "openai": "openai_compat",
    "gemini": "google",
    "direct": "direct_url",
    "comfy_direct": "direct_url",
}

#: provider_id prefixes that imply a type when `type` is empty/unknown.
#: Order matters: TTS before LLM before image, mirroring the old factory
#: branch order (a tts+llm hybrid without image capability is TTS).
# Order matters and is most-specific-first. The Beam/Remote LLM and TTS families
# have to precede the bare `beam-` / `modal-` prefixes they used to be swallowed
# by, and all of them have to precede the substring heuristics further down —
# otherwise `remote-llm-vllm-1` (a container that really does run vLLM) resolves
# to `modal_llm` on the strength of the word "vllm" in its id.
_ID_PREFIXES = (
    ("beam-llm-", "beam_llm"),
    ("beam_llm_", "beam_llm"),
    ("beam-tts-", "beam_tts"),
    ("beam_tts_", "beam_tts"),
    ("remote-hybrid-", "remote_hybrid"),
    ("remote_hybrid_", "remote_hybrid"),
    ("remote-llm-", "remote_llm"),
    ("remote_llm_", "remote_llm"),
    ("remote-tts-", "remote_tts"),
    ("remote_tts_", "remote_tts"),
    ("direct-tts-", "direct_tts"),
    ("direct_tts_", "direct_tts"),
    ("remote-comfy-", "remote_comfy"),
    ("remote-comfy", "remote_comfy"),
    ("direct-comfy-", "direct_url"),
    ("direct-comfy", "direct_url"),
    ("tts-", "modal_tts"),
    ("tts_", "modal_tts"),
    ("llm-", "openai_compat"),
    ("llm_", "openai_compat"),
    ("modal-", "modal"),
    ("modal_", "modal"),
    ("beam-", "beam"),
    ("beam_", "beam"),
)


def _capability_fallback(capabilities, worker_type: str) -> Optional[str]:
    caps = set(capabilities or [])
    if worker_type == "hybrid" or ("image" in caps and "llm" in caps):
        return "remote_hybrid"
    if "tts" in caps and "image" not in caps:
        return "modal_tts"
    if worker_type == "llm" or "llm" in caps:
        return "openai_compat"
    if "image" in caps:
        return "direct_url"
    return None


def resolve_provider_type(
    provider_type: str = "",
    provider_id: str = "",
    worker_type: str = "",
    capabilities=None,
) -> Optional[str]:
    """Resolve any provider identity to a canonical ENGINE_SPECS key.

    Precedence: exact spec hit → legacy alias → id prefix (most specific
    first) → substring heuristics → worker_type/capability fallback.
    Returns None when nothing matches.

    The substring rules are deliberately LAST. They are legacy rescues for rows
    written before `type` was reliable, and putting them last is what stops them
    from re-labelling a provider that now knows what it is.
    """
    # An explicit type that is a spec wins outright.
    #
    # One legacy rescue survives: a row whose *generic hosted* type was a
    # mis-typed Modal vLLM pod, recoverable because the id says "vllm" AND
    # says "modal" - the pod speaks the OpenAI API, so the row said
    # `openai_compat`, and the id said `modal-vllm`.
    #
    # It is scoped to `_LEGACY_VLLM_MISTYPED` and to ids that name Modal,
    # because the new transports legitimately contain "vllm" — a `beam_llm`
    # or `remote_llm` row must never be re-labelled `modal_llm`, and a
    # SELF-HOSTED vLLM provider (`openai_compat` with "vllm" in its id) must
    # not be re-labelled either: that is what those types are for, and
    # re-labelling it sent the request to a Modal app instead of the
    # operator's own box.
    if provider_type in ENGINE_SPECS:
        provider_id_l = (provider_id or "").lower()
        if (
            "vllm" in provider_id_l
            and provider_type in _LEGACY_VLLM_MISTYPED
            and _LEGACY_VLLM_MISTYPED_ID_MARKER in provider_id_l
        ):
            return "modal_llm"
        return provider_type
    if provider_type in _TYPE_ALIASES:
        return _TYPE_ALIASES[provider_type]
    pid = provider_id or ""
    for prefix, target in _ID_PREFIXES:
        if pid.startswith(prefix):
            return target
    lowered = pid.lower()
    if "remote-hybrid" in lowered or "remote_hybrid" in lowered:
        return "remote_hybrid"
    if "remote-comfy" in lowered or "remote_comfy" in lowered:
        return "remote_comfy"
    if "direct" in lowered:
        return "direct_url"
    # Same rule as the legacy rescue above: the id has to name Modal.
    # A provider whose type is unknown and whose id merely says "vllm" is
    # not thereby a Modal pod - it is far more likely to be somebody's own
    # vLLM box, which is exactly what the previous rule mis-routed.
    if "vllm" in lowered and _LEGACY_VLLM_MISTYPED_ID_MARKER in lowered:
        return "modal_llm"
    return _capability_fallback(capabilities, worker_type)


#: Resolved types whose engine implements setup (owns storage needing
#: init, or no-op success). Hosted LLM and TTS engines inherit the base
#: setup_models which reports False — they have no model tree. The remote
#: cells are here because `RemoteAgentFileMixin` implements setup for all
#: three, which is what closes the modal/remote parity gap.
_SUPPORTS_SETUP = frozenset({
    "modal", "beam", "direct_url", "remote_comfy", "modal_llm", "remote_hybrid",
    # Direct TTS shares DirectComfyEngine's no-op setup; a rig with no model
    # tree still answers True so the provider page's setup action does nothing
    # harmful rather than failing. The rest of the new cells host a container
    # that owns its own weights, so they inherit the base's False.
    "direct_tts",
    # `remote_llm` and `remote_comfy` were absent because their engines never
    # called the sidecar's `/setup` — the route answers in every `WORKER_MODE`.
    # `RemoteAgentFileMixin` calls it, so setup works for both.
    #
    # `remote_tts` is NOT here, and is not supposed to be: `RemoteTTSEngine`
    # overrides `setup_models` to return False, matching `ModalTTSEngine`, which
    # inherits the base's False. A TTS root holds audio, not a ComfyUI models
    # tree, so there is nothing to initialise. Adding it would have been the
    # wrong direction to "fix" the one remaining parity mismatch — the honest
    # direction is TTS not doing setup on either transport.
    "remote_llm",
})


def supports_setup(resolved_type: Optional[str]) -> bool:
    """Whether the engine for a resolved type implements setup."""
    return resolved_type in _SUPPORTS_SETUP


def list_engine_specs() -> List[Dict[str, Any]]:
    """Return all canonical specs in registry order."""
    return list(ENGINE_SPECS.values())


def ui_schemas() -> Dict[str, Dict[str, Any]]:
    """Project registry specs to the UI schema shape served by the API.

    Strips engine-internal keys (`engine`, `manages_model_files`, `aliases`)
    so the wire shape stays exactly what the frontend expects.

    `transport` is ADDED, not stripped: the provider modal groups by
    category x transport so the four empty cells that used to be invisible
    show up as choices that do not exist rather than as choices nobody made.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for key, spec in ENGINE_SPECS.items():
        out[key] = {
            "id": spec["id"],
            "name": spec["name"],
            "category": spec["category"],
            "transport": spec.get("transport"),
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
