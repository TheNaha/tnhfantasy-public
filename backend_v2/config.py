# Pydantic Settings Configuration + Full Config Management
# Combines v2's Pydantic approach with v1's file-based config persistence
#
# CONFIG SYSTEM SPLIT:
# .env (via Pydantic Settings) — infrastructure/secrets, rarely changes:
#   COMFY_DATABASE_URL, OUTPUT_DIR, INPUT_DIR, COMFY_PREVIEW_CACHE_DIR
#   HF_TOKEN, CIVITAI_TOKEN, MODAL_TOKEN_*, BEAM_API_KEY
#   COMFY_CORS_ORIGINS, COMFY_WORKER_BACKEND_URL
# config.json — runtime app behavior, UI-editable without restart:
#   Job concurrency, timeouts, retry settings
#   Image processing / thumbnail settings
#   Scheduler intervals
#
# CONFIGURATION PRECEDENCE (highest to lowest):
# 1. Environment variables (COMFY_* prefix)
# 2. File-based config (config.json) - runtime editable via API
# 3. DEFAULT_CONFIG (fallback values)
#
# This allows:
# - Production deployments to use env vars for secrets and overrides
# - Runtime configuration updates via UI without restarts
# - Sensible defaults for quick setup
import copy
import json
import os


def env_positive_int(raw_value: str | None, default: int) -> int:
    """Read an int env var, falling back to `default` on a bad value.

    The bare `int(os.getenv(...))` form crashes the whole process at import
    when the value is misspelled — a typo in a deployment env file is then a
    boot failure instead of a logged warning and a working default, which is
    the opposite of what an operational knob should do.
    """
    try:
        parsed = int(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else default


def env_positive_float(raw_value: str | None, default: float) -> float:
    """Float counterpart of `env_positive_int`, same failure mode."""
    try:
        parsed = float(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed > 0 else default
from functools import lru_cache
from typing import Any

from pydantic import model_validator
from pydantic_settings import BaseSettings

import structlog
import tempfile
import threading

_cfg_logger = structlog.get_logger().bind(logger_name="config")


# ============================================================================
# DEFAULT CONFIGURATION - Fallback if config.json doesn't exist
# ============================================================================
DEFAULT_CHECKPOINT = "sd_xl_base_1.0.safetensors"

#: Fallback for the single-tenant default user partition. `AppConfig.default_user_id`
#: (COMFY_DEFAULT_USER_ID) overrides this at runtime for multi-tenant deployments.
DEFAULT_USER_ID_FALLBACK = "default_user"

DEFAULT_CONFIG = {
    "worker": {
        "poll_interval": 0.3,
        "retry_delay": 5,
        "poll_limit": 50
    },
    "jobs": {
        # `default_limit` and `max_in_memory` are GONE (2026-10-21).
        #
        # They were user-editable settings with a description and a validation
        # rule, and nothing read them: the job list limit is the hardcoded
        # `limit: int = 20` on `GET /api/jobs`, and the in-process queue is an
        # unbounded `asyncio.Queue()`. A settings page that offered them
        # promised an effect that never happened.
        #
        # A config.json that still carries them keeps working: the loader
        # deep-merges the file over the defaults and nothing reads the keys.
        "max_concurrent": 5,
        # Client-side stream timeout for image jobs, so the backend never gives
        # up on a workflow the worker is still legally running.
        #
        # This comment used to say it was "aligned with the image worker's
        # INFERENCE_TIMEOUT_SECONDS". No code reads that name. The worker's knob
        # is `COMFYUI_TIMEOUT_SECONDS` (`image_worker/worker.py:70`) and it
        # also defaults to 3600, so the intent holds — but the two are
        # independent: lowering one does not lower the other, and lowering THIS
        # one below the worker's is exactly the case that abandons a running
        # workflow. Env override: COMFY_JOB_TIMEOUT.
        "timeout": 3600,
        "max_retries": 3,
        "5xx_max_retries": 1,
        "retry_base_delay": 1.0,
        "retry_max_delay": 60.0,
        "llm": {
            "timeout": 180,
            "max_retries": 2,
            "stagger_delay": 2.0,
        },
    },
    "model_sync": {
        "interval": 300,
        "retry_delay": 10,
        "reconciliation_interval": 120
    },

    # How a stored chat message becomes an LLM turn. See
    # `services.context_builder.llm_turn_for` for why these exist as settings
    # rather than as code: the mapping is what decides whether the model can
    # tell a character reply from a narration from an image, and every chat's
    # prompt is built from it.
    "roleplay": {
        # Name each speaking turn. In a single-character chat the character's
        # name is already the whole subject of the system prompt, so the prefix
        # is noise; with more than one participant it is the only thing
        # distinguishing one `assistant` turn from the next.
        "label_speakers": True,
        # A narrator turn is NOT a character turn and NOT a system instruction.
        # It used to be sent as `role: "system"`, which on a provider that
        # concatenates every system message into the system prompt rips the
        # narration out of its place in the dialogue and appends it to the end
        # of the instructions, unmarked.
        "narrator_prefix": "[Narration]",
        # An image turn carries no text the model asked for. Labelled and kept
        # in position, so the model knows an illustration happened where it
        # happened rather than not at all.
        "image_prefix": "[Scene]",
    },
    "downloads": {
        "chunk_size": 8192,
        "auto_remove_delay": 5
    },
        "modal": {
            "timeout": 300,
            "max_containers": 1,
            "scaledown_window": 5,
            # No `vllm` block. It held gpu_type / timeout_seconds /
            # max_model_len and nothing ever read it — not
            # `infrastructure/providers/modal_config.py`, not the validator
            # below, not any route — so an operator could set it in `config.json`
            # and see no effect. The LLM Modal engine reads its own
            # `MODAL_VLLM_*` environment variables instead.
        },
    "api": {
        "gzip_minimum_size": 1000,
        # Every origin this stack is actually reached on. The port is not
        # optional: `https://100.150.0.4` is Traefik on 443, and
        # `http://100.150.0.4:5174` is the Vite dev server directly — a different
        # scheme *and* a different port, so the first is not a match for the
        # second.
        #
        # Measured: browsing `http://100.150.0.4:5174` made the socket.io
        # handshake return 400 `"http://100.150.0.4:5174 is not an accepted
        # origin."`, which the client retries forever, which is the permanent
        # "Disconnected from server. Trying to reconnect" toast. Nothing in the
        # HTTP surface fails, so the app looks fine while realtime is dead.
        "cors_origins": [
            "http://localhost:5174",
            "http://localhost:8002",
            "http://127.0.0.1:5174",
            "https://comfy.lan.thenaha.my.id",
            "https://100.150.0.4",
            "http://100.150.0.4:5174",
        ]
    },
    "jobs_cleanup": {
        "max_age_hours": 24,
        "auto_cleanup": False,
        "cleanup_interval": 3600
    },
    "image_processing": {
        "thumbnail_sizes": {
            "medium": 512
        },
        "thumbnail_format": "webp",
        "thumbnail_quality": 90,
        "thumbnail_directory": "thumb",
        "output_date_hierarchy": True,
        "embed_metadata_in_png": True,
        "blurhash_components_x": 4,
        "blurhash_components_y": 3,
        "blurhash_resize_max": 64
    },
    "generator": {
        # The single definition lives here, not in core.workflow_builder:
        # config.py is the lowest-level module (infrastructure.database imports
        # it), so importing anything from `core` at module scope is circular.
        # core.workflow_builder imports this constant instead.
        "default_checkpoint": DEFAULT_CHECKPOINT
    },
    "ai": {
        "maxContextTokens": 4096,
        "temperature": 0.8,
        "idleSimEnabled": False,
        "idleSimIntervalSeconds": 600,
        # Declared here so the key is a real, documented config leaf rather than
        # an implicit one: `services/rag_pipeline.rag_enabled()` already read
        # it with a `True` default, so adding the key changes no behaviour.
        "ragEnabled": True,
        # Cosine-distance cutoff for semantic retrieval, applied to BOTH the
        # character-memory search and the lorebook search. pgvector's
        # `cosine_distance` is 0 for identical, 1.0 for orthogonal and 2.0 for
        # opposite, so 1.0 is "no relationship at all" and anything above it is
        # noise.
        #
        # There was no cutoff, so the top-N were injected unconditionally: the
        # nearest neighbour was included even when it was semantically unrelated,
        # which spends prompt budget on distractor lore and, because
        # `memory_extraction` inserts duplicate memories that are then always
        # near-identical to each other, the same few memories were retrieved for
        # every query. Raising this drops those; set it to 2.0 to restore the
        # old unconditional top-N.
        "ragMaxDistance": 0.6,
        # Whether a chat reply may enqueue the background LLM call that writes
        # character memories.
        #
        # There was no gate at all, so this was an unconditional paid call on
        # every Nth turn with no way to turn it off — including for swipes and
        # regenerations, and for idle-simulation replies the user never wrote.
        # Default stays TRUE so upgrading changes no behaviour, but the switch
        # now exists and is exposed in Settings. Set false to make the cost zero
        # at the price of memories not accumulating.
        "memoryExtractionEnabled": True,
    },
    "system_prompts": {
        # --- Roleplay & Core Dialogue ---
        "roleplay_default": "You are a highly descriptive AI roleplay character. Write engaging, detailed, and immersive responses in character. Stay true to the character's personality, background, and speech patterns. Do not act as an AI assistant.\n\nFormatting rules:\n- Put the character's spoken dialogue in double quotation marks, one line per dialogue.\n- Put actions, narration, sounds, and emphasis in asterisks: *she frowns*.\n- Write actions on their own line, separated from dialogue.\n- Never wrap narration or prose in quotation marks.\n- Never leave stray asterisks or quotes; every * and \" must be paired.\n- Keep dialogue on a single line; do not insert line breaks inside quotes.",
        "narrator": "You are the narrator of an interactive roleplay story. Your job is to describe the world around the conversation: the environment, the passage of time, off-screen events, and transitions between scenes. Decide whether the story needs: continuing the dialogue, adding background information, or cutting to a new scene. Write 2-5 evocative sentences in third person, past tense. Do not speak dialogue and do not act as the character.",
        "suggest_instruction": "CRITICAL INSTRUCTION: You must act as the USER (the person talking to the character). Based on the context, write a single short action or sentence the USER is likely to say or do next. Output ONLY the raw text without wrapping it in quotes or labels.",
        "chat_impersonate": "You are {user}, the human participant in this roleplay with {char}. Write ONE in-character message or action that {user} would realistically say or do next. Output ONLY the raw message text — no labels, no quotes around the whole reply.",
        "chat_scene_illustrate": "You are an AI scene director for a roleplay chat. Read the following recent roleplay chat context and create a visual depiction of the current scene or the main character's action. Output ONLY a highly detailed ComfyUI image prompt (comma-separated Danbooru tags: subject, pose, lighting, camera angle, style, quality tags).",

        # --- Interactive Story Sandbox ---
        "story_continue_default": "You are a master fiction author continuing an interactive, character-driven story. Write compelling, atmospheric prose that advances the narrative naturally. Match the established tone, tense, and POV. Describe character actions, dialogue, and environment vividly. Do not provide meta-commentary or break the fourth wall.",
        "story_action_rewrite": "You are a skilled fiction editor. Rewrite the provided passage according to the author's directive (if any). Preserve the author's voice, tense, POV, and the surrounding story's continuity. Match the surrounding prose style. Output ONLY the rewritten prose — no preamble, no quotes, no commentary.",
        "story_action_expand": "You are a skilled fiction writer. Expand the provided passage with richer detail — sensory description, character interiority, pacing beats — roughly doubling its length. Respect any author's directive. Preserve the author's voice, tense, POV, and continuity with the surrounding story. Output ONLY the expanded prose — no preamble, no quotes.",
        "story_action_summarize": "You are a concise story analyst. Summarize the provided story text into a tight synopsis (at most 150 words) capturing key events, characters, and outcome. Output ONLY the summary prose — no preamble, no bullet points unless asked.",
        "story_illustrate": "You are an AI art director for a story. Given the story chapter text, write a highly detailed ComfyUI prompt (comma-separated Danbooru tags, lighting, camera angle, subjects, mood) that captures the most vivid scene. Return ONLY the prompt text.",
        "story_parse": "You are an AI worldbuilder. Parse the provided story text and extract the following:\n1. Characters (name, physical appearance, personality)\n2. Locations (name, description)\n3. Key Lore (important items, concepts, organizations)\n\nReturn a strictly valid JSON object in this format:\n{\n  \"characters\": [ {\"name\": \"...\", \"description\": \"...\", \"personality\": \"...\"} ],\n  \"locations\": [ {\"name\": \"...\", \"description\": \"...\"} ],\n  \"lorebooks\": [ {\"name\": \"...\", \"description\": \"...\"} ]\n}",
        "story_compile": "You are a literary novel editor. Given the raw roleplay transcript and scene milestones, compile and novelize this story into a cohesive, beautifully polished chapter. Write in immersive literary third-person past tense. Preserve the emotional depth, key character lines, and atmospheric details.",

        # --- Memory & World Vault ---
        "memory_extraction": "You are a memory extraction assistant. Given a conversation between a user and a character, extract durable, factual memories that the character should remember for future interactions.\n\nRules:\n- Extract 1-5 memories maximum\n- Each memory should be a single, concise sentence\n- Focus on: user preferences, character relationships, important events, decisions, opinions, facts about the user\n- Do NOT include trivial greetings or small talk\n- Output ONLY a JSON array of strings, e.g. [\"memory 1\", \"memory 2\"]\n- If nothing worth remembering, output: []",
        "world_onboarding": "You are a master World Architect. Analyze the provided character profile or concept and design a complete, cohesive world vault blueprint with world lore, key factions, primary locations, and starter scenarios. Return strictly valid JSON.",
        "world_lore_enrich": "You are a mythologist and lore archivist. Given a lorebook entry and its world context, enrich the lore entry with historical background, cultural significance, related myths, and story hooks. Return strictly valid JSON with enriched entry details.",
        "world_crossover": "You are an imaginative crossover story weaver. Given two distinct characters, their worlds, and lorebooks, design a compelling crossover scenario, encounter premise, and conflict that brings them together naturally. Return strictly valid JSON.",
        "world_tick": "You are a world simulation engine. Given the current world state, active locations, and resident character statuses, simulate the passage of time: generate world events, faction rumors, and location atmosphere shifts. Return strictly valid JSON.",
        "vision_avatar_analysis": "You are an expert anime and fantasy art analyzer. Carefully examine the character image and output a detailed description of their physical appearance, hair, eyes, expression, clothing style, accessories, and a comma-separated list of Danbooru visual tags. Return strictly valid JSON.",

        # --- Prompt Studio & Expansion ---
        "magic_prompt": "You are an expert AI image generation prompt engineer. Your task is to take a simple user idea and expand it into a highly detailed, comma-separated list of Danbooru-style tags and visual descriptions suitable for Stable Diffusion / ComfyUI. Include lighting, camera angles, quality modifiers (masterpiece, best quality, ultra-detailed), and specific subject details. Return ONLY the expanded prompt text, nothing else. No conversational text.",

        # --- Character Generator Templates ---
        "charGenDescriptionPrompt": "You are an expert character creator. Expand the provided character details into a rich, detailed background description. Return ONLY the text for the description, no markdown or extra chat.",
        "charGenPersonalityPrompt": "You are an expert character creator. Expand the provided character details into a detailed personality profile covering traits, quirks, and mannerisms. Return ONLY the text, no markdown.",
        "charGenScenarioPrompt": "You are an expert character creator. Create an engaging scenario/setting for this character based on their details. Return ONLY the text, no markdown.",
        "charGenFirstMesPrompt": "You are an expert character creator. Write an engaging first message/greeting from this character in their unique voice. Return ONLY the text, no markdown.",
        "charGenMesExamplePrompt": "You are an expert character creator. Write a few short dialogue examples showing how this character speaks. Use <START> to separate examples. Return ONLY the text, no markdown.",
        "charGenSystemPromptPrompt": "You are an expert character creator. Write a custom system prompt that instructs an AI how to play this character. Return ONLY the text, no markdown.",
        "charGenVisualTagsPrompt": "You are an expert character creator. Generate a comma-separated list of Danbooru-style visual tags that describe this character's appearance. Return ONLY the tags, no markdown.",
        "charGenEnrichPrompt": "You are an expert character creator. Read the provided character details and fill in ALL missing fields to enrich the character profile. Output MUST be valid JSON matching exactly these keys: \"description\", \"personality\", \"scenario\", \"first_mes\", \"mes_example\", \"default_time\", \"default_location\". Do not include markdown code blocks, just raw JSON."
    },
    # The user's OWN system-prompt blocks.
    #
    # `system_prompts` above is a fixed set of keys the code looks up by name,
    # so it cannot grow: adding a prompt meant editing the config schema, the
    # validation allow-list and the frontend's copy of the defaults, and there
    # was no way to remove one either.
    #
    # This is a LIST, so it can. Each entry is
    # `{"key", "label", "category", "prompt"}`; the key is what the rest of
    # the system looks a block up by, and the entries are merged into
    # `get_system_prompt_blocks()` alongside the fixed ones.
    "system_prompt_library": [],
}


# ============================================================================
# PYDANTIC SETTINGS (Environment Variable Support)
# ============================================================================
class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # Database
    database_url: str = "sqlite:///./data/db/comfy.db"
    
    # Worker / Job Queue (overrides from env)
    worker_poll_interval: float = 0.3
    max_concurrent_jobs: int = 5
    job_retry_delay: float = 5.0
    
    # Job settings (consolidated from file config)
    #
    # These four are SHADOW values: a getter only reads them when the matching
    # COMFY_* env var is set, in which case pydantic has parsed the value out of
    # the environment and the default here is unreachable. They are still
    # declared, so keep them bound to DEFAULT_CONFIG rather than repeating a
    # literal: `job_timeout` used to default to 300 while the effective default
    # was `jobs.timeout` = 3600, and any future reader that skipped the env
    # check would have silently reinstated the premature-timeout failure the
    # 3600 comment above exists to prevent.
    job_timeout: int = DEFAULT_CONFIG["jobs"]["timeout"]
    job_max_retries: int = DEFAULT_CONFIG["jobs"]["max_retries"]
    job_5xx_max_retries: int = DEFAULT_CONFIG["jobs"]["5xx_max_retries"]
    job_retry_base_delay: float = DEFAULT_CONFIG["jobs"]["retry_base_delay"]
    job_retry_max_delay: float = DEFAULT_CONFIG["jobs"]["retry_max_delay"]
    
    # Downloads
    download_chunk_size: int = 8192
    download_auto_remove_delay: int = 5
    
    # Modal
    modal_timeout: int = 300
    modal_max_containers: int = 1
    modal_scaledown_window: int = 5
    # `modal_vllm_gpu_type` / `modal_vllm_timeout` / `modal_vllm_max_model_len`
    # were removed: three settings that nothing read, so the Settings API
    # accepted them and returned them as if they governed the vLLM provider.
    # The engine is configured through `MODAL_VLLM_*` in the provider's env.
    
    # API
    # Default to frontend dev server origin. Override via COMFY_CORS_ORIGINS for production.
    # Same list as DEFAULT_CONFIG above, and it has to stay in step with it —
    # which is why the reasoning lives on the DEFAULT_CONFIG copy rather than
    # here twice.
    cors_origins: list[str] = [
        "http://localhost:5174",
        "http://localhost:8002",
        "http://127.0.0.1:5174",
        "https://comfy.lan.thenaha.my.id",
        "https://100.150.0.4",
        "http://100.150.0.4:5174",
    ]
    gzip_minimum_size: int = 1000
    worker_backend_url: str = "http://backend_v2:8002"
    
    # Model Sync
    model_sync_interval: int = 300
    reconciliation_interval: int = 120

    # Directories
    # Introduce /{user_id}/ root partitions for multi-tenancy. Configurable so a
    # multi-user deployment can set COMFY_DEFAULT_USER_ID without code changes.
    default_user_id: str = "default_user"
    output_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/output"))
    input_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), "../data/input"))
    character_avatar_dir: str = "/data/characters"
    location_image_dir: str = "/data/location_images"

    @model_validator(mode="before")
    @classmethod
    def load_directories_with_fallback(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "output_dir" not in data or data.get("output_dir") is None:
                comfy_out = os.environ.get("COMFY_OUTPUT_DIR")
                if comfy_out is not None:
                    data["output_dir"] = comfy_out
                else:
                    out = os.environ.get("OUTPUT_DIR")
                    if out is not None:
                        data["output_dir"] = out
            if "input_dir" not in data or data.get("input_dir") is None:
                comfy_in = os.environ.get("COMFY_INPUT_DIR")
                if comfy_in is not None:
                    data["input_dir"] = comfy_in
                else:
                    in_dir = os.environ.get("INPUT_DIR")
                    if in_dir is not None:
                        data["input_dir"] = in_dir
        return data

    class Config:
        env_prefix = "COMFY_"
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()


# ============================================================================
# FILE-BASED CONFIG MANAGEMENT (from v1)
# ============================================================================

# Global configuration instance
_config: dict[str, Any] = None
_config_lock = threading.Lock()

# Where the writable settings file lives.
#
# The default is the repository copy next to this module, which is what you want
# on a dev machine: the Settings UI edits it in place and you can see the diff.
#
# In the container that default is WRONG, and silently so. `backend_v2/Dockerfile`
# does `COPY . .` into `/app` and the production compose mounts only
# `./data:/data`, so `<repo>/config.json` resolves to `/app/config.json` — the
# container's writable layer. `update_config` then reports success, and every
# change made through the Settings UI (system prompts, `generator.default_checkpoint`,
# `jobs.*`, `image_processing.*`) is discarded by the next `up --build` or any
# container recreate. Only the dev override's `./backend_v2:/app` bind mount made
# it durable, which is why this was invisible: dev worked, production did not.
#
# `COMFY_CONFIG_PATH` points it at a durable volume instead. The production
# compose sets it to `/data/config.json`, which is on the same bind mount as the
# Postgres cluster and the generated images, and `_seed_config_file` copies the
# shipped defaults there on first boot so an empty volume still starts.
def _default_config_path() -> str:
    override = os.environ.get("COMFY_CONFIG_PATH", "").strip()
    if override:
        return override
    return os.path.join(os.path.dirname(__file__), "config.json")


_config_path = _default_config_path()


def _seed_config_file(path: str) -> None:
    """Copy the shipped config to `path` when `path` does not exist yet.

    Only ever runs on a missing target, so it cannot overwrite an operator's
    saved settings. `shutil.copyfile` plus a temp-and-rename would be safer
    against a concurrent reader, but this runs once, before the app serves, from
    the lifespan — and `load_config` already tolerates a partially written file
    by falling back to `DEFAULT_CONFIG` with a warning.
    """
    if os.path.exists(path):
        return
    packaged = os.path.join(os.path.dirname(__file__), "config.json")
    try:
        if os.path.abspath(packaged) == os.path.abspath(path):
            return
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(packaged, "r") as src:
            contents = src.read()
        with open(path, "w") as dst:
            dst.write(contents)
        _cfg_logger.info("config_seeded", path=path, source=packaged)
    except Exception as exc:  # pragma: no cover - never block startup on this
        _cfg_logger.warning("config_seed_failed", path=path, error=str(exc))


def load_config(config_path: str = None) -> dict[str, Any]:
    """
    Load configuration from JSON file.
    Creates default config.json if it doesn't exist.
    
    Args:
        config_path: Optional path to config file. Defaults to backend_v2/config.json
        
    Returns:
        Configuration dictionary
    """
    global _config, _config_path
    
    if config_path:
        _config_path = config_path

    _seed_config_file(_config_path)

    # If config exists, load it
    if os.path.exists(_config_path):
        try:
            with open(_config_path, 'r') as f:
                loaded_config = json.load(f)
                # Merge with defaults to ensure all keys exist
                _config = _deep_merge(DEFAULT_CONFIG.copy(), loaded_config)
                _cfg_logger.info("config_loaded", path=_config_path)
                return _config
        except Exception as e:
            _cfg_logger.warning("config_load_failed", path=_config_path, error=str(e))
            # A config file that cannot be parsed is the OPERATOR'S settings,
            # and overwriting it with the defaults destroys them. It used to
            # be exactly that: the parse failed, the file was replaced with
            # DEFAULT_CONFIG, and whatever the operator had set was gone with
            # no record of it.
            #
            # It is easy to hit by accident. The file is written atomically
            # now, but a reader that catches it between a truncate and a
            # write - a test restoring the file, a sync tool, an editor that
            # does not write atomically - sees an empty file, and the next
            # load replaced it.
            #
            # So: move the unreadable file aside, with a timestamp, and only
            # then write the defaults. The operator gets a working app AND
            # their file, under a name that says what happened to it.
            _quarantine_unreadable_config(_config_path)

    # Create default config file
    _config = DEFAULT_CONFIG.copy()
    try:
        directory = os.path.dirname(_config_path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".json")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(_config, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, _config_path)
            _cfg_logger.info("config_created_default", path=_config_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        _cfg_logger.warning("config_create_failed", error=str(e))

    return _config


def _quarantine_unreadable_config(path: str) -> str | None:
    """Move a config file that could not be parsed aside, and say where.

    Returns the new path, or None if the move did not happen.
    """
    import datetime as _dt

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    quarantine = f"{path}.unreadable-{stamp}"
    try:
        os.replace(path, quarantine)
    except OSError as exc:
        _cfg_logger.warning(
            "config_quarantine_failed", path=path, error=str(exc)
        )
        return None
    _cfg_logger.warning(
        "config_quarantined",
        path=path,
        moved_to=quarantine,
        detail=(
            "The config file could not be parsed. It has been moved aside and "
            "the defaults written in its place. Nothing was lost: the "
            "original is at the path above."
        ),
    )
    return quarantine


def get_config() -> dict[str, Any]:
    """
    Get current configuration.
    Loads config if not already loaded.
    
    Returns:
        Configuration dictionary
    """
    global _config
    if _config is None:
        load_config()
    return _config


# Leaves for which a blank string means "unset", not "invalid".
#
# The Settings UI offers "(unset — backend falls back to its compiled-in
# default)" for the default checkpoint, and sent `""` for it. `_check_str`
# rejects a blank string by default, so the only way to express "unset" was a
# 400 — the option could not be selected at all. Blank now means *remove the
# key*, which is what the label claims: `resolve_default_checkpoint()` then
# returns `DEFAULT_CHECKPOINT` because the key is genuinely absent, rather than
# because it holds an empty string that happens to be treated as absent.
BLANK_MEANS_UNSET = frozenset({("generator", "default_checkpoint")})


def _split_unset(updates: dict[str, Any]) -> tuple[dict[str, Any], set[tuple[str, str]]]:
    """Pull blank-valued unsettable leaves out of `updates`.

    Returns the updates with those leaves removed, plus the set of
    `(section, key)` pairs that were blank, for the caller to delete after the
    merge. Sections that become empty are dropped so a deep merge cannot
    re-create them.
    """
    unset: set[tuple[str, str]] = set()
    # A section that is not a dict is passed through UNCHANGED.
    #
    # It used to be filtered out with `if isinstance(body, dict)`, so a
    # list-valued section never reached the validator or the merge — and
    # `update_config` returned success having written nothing. The first
    # list-valued section, `system_prompt_library`, is how a user adds their
    # own system-prompt blocks, and every add, edit and remove of one was a
    # silent no-op that reported 200.
    remaining: dict[str, Any] = {
        section: (dict(body) if isinstance(body, dict) else body)
        for section, body in updates.items()
    }
    for section, body in list(remaining.items()):
        if not isinstance(body, dict):
            continue
        for key, value in list(body.items()):
            if (section, key) in BLANK_MEANS_UNSET and isinstance(value, str) and not value.strip():
                unset.add((section, key))
                body.pop(key)
        if not body:
            remaining.pop(section)
    return remaining, unset


def update_config(updates: dict[str, Any], persist: bool = True) -> dict[str, Any]:
    """
    Update configuration with new values.
    
    Args:
        updates: Dictionary with configuration updates (nested structure)
        persist: Whether to save changes to config.json
        
    Returns:
        Updated configuration dictionary
        
    Raises:
        ValueError: If validation fails
    """
    global _config
    
    # Validate updates before applying
    # Split out the blank-means-unset leaves BEFORE validating, so "unset" is not
    # rejected by the very validator that guards against a typo'd blank.
    unset_updates, unset_leaves = _split_unset(updates)
    _validate_config(unset_updates)

    # Deep merge updates into current config.
    #
    # This is a read-modify-write of a module global, and `settings.py` calls it
    # through `asyncio.to_thread` from two routes — so two concurrent PUTs for
    # different sections could interleave and silently drop one. The lock makes
    # the merge and the write atomic with respect to each other; it is not
    # reentrant, so nothing inside may re-enter.
    #
    # Lazily load config inside the lock so concurrent early requests during
    # startup cannot race on `_config is None` and call `load_config` twice.
    with _config_lock:
        if _config is None:
            load_config()
        _config = _deep_merge(_config, unset_updates)

        # Delete after the merge, inside the same lock, so a concurrent writer
        # cannot observe (or re-persist) a half-applied unset.
        for section, key in unset_leaves:
            body = _config.get(section)
            if isinstance(body, dict):
                body.pop(key, None)

        # Persist to file if requested
        if not persist:
            return _config
        try:
            # Write to a temp file and rename. A plain `open(..., 'w')` truncates
            # first, so a reader — or a crash — could see a half-written
            # config.json. `llm_config.py` already did mkstemp + os.replace +
            # fsync; this brings config.json to the same durability rather than
            # leaving the two config writers on different mechanisms.
            directory = os.path.dirname(_config_path) or "."
            fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".json")
            try:
                with os.fdopen(fd, "w") as handle:
                    json.dump(_config, handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, _config_path)
            except BaseException:
                # Never leave a stray temp file behind for reconciliation or a
                # later read to trip over.
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            _cfg_logger.info("config_saved", path=_config_path)
        except Exception as e:
            _cfg_logger.error("config_save_failed", error=str(e))
            raise
    
    return _config


def reset_config() -> dict[str, Any]:
    """
    Reset configuration to defaults.

    Returns:
        Default configuration dictionary
    """
    global _config

    # Same lock and the same atomic writer as `update_config`, one function
    # above. Without them this was the exact defect `update_config` had just been
    # fixed for: an unlocked write to the module global that a concurrent
    # `update_config` could read mid-assignment, and a truncate-then-write
    # `open(..., 'w')` that a reader — or a crash — could catch half-written.
    # `settings.py` reaches both through `asyncio.to_thread` from two routes, so
    # they really can run at the same time.
    with _config_lock:
        # Remember the pre-reset config so we can restore it if the file write
        # fails — memory and disk must not diverge.
        old_config = copy.deepcopy(_config) if _config is not None else None
        _config = copy.deepcopy(DEFAULT_CONFIG)

        try:
            directory = os.path.dirname(_config_path) or "."
            fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".config-", suffix=".json")
            try:
                with os.fdopen(fd, "w") as handle:
                    json.dump(_config, handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, _config_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            _cfg_logger.info("config_reset")
        except Exception as e:
            # Disk write failed: restore the previous in-memory config and
            # re-raise so the caller knows the reset did not persist.
            _config = old_config if old_config is not None else DEFAULT_CONFIG.copy()
            _cfg_logger.warning("config_reset_save_failed", error=str(e))
            raise

    return _config


def resolve_default_checkpoint() -> str:
    """The configured default checkpoint, or the well-known base name.

    One place, because there were three readers of `generator.default_checkpoint`
    and they disagreed on the empty case:

    - `job_processing.get_default_checkpoint` used
      `.get("default_checkpoint", DEFAULT)`, which returns **None** when the key
      is present but empty — so a config with `default_checkpoint: ""` produced
      a job whose checkpoint was `None`, and the failure surfaced later as a
      missing-model error naming `None`.
    - `image_submission` used `or DEFAULT`, which does fall back.
    - `model_availability_service._resolve_default_checkpoint` used a truthiness
      check and then fell through to `DEFAULT` itself.

    `""` is not a checkpoint, so treat it as absent. Read through `get_config()`
    like every other config reader; do not cache, because `update_config` and
    `reset_config` can replace the whole dict under the caller's feet.
    """
    try:
        configured = (get_config() or {}).get("generator", {}).get("default_checkpoint")
    except Exception:  # pragma: no cover - get_config reads a file
        configured = None
    if configured is None or not str(configured).strip():
        from core.workflow_builder import DEFAULT_CHECKPOINT

        return DEFAULT_CHECKPOINT
    return str(configured)


def _deep_merge(base: dict, updates: dict) -> dict:
    """
    Deep merge two dictionaries.
    
    Args:
        base: Base dictionary
        updates: Updates to merge in
        
    Returns:
        Merged dictionary
    """
    result = base.copy()
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# Configurable system-prompt blocks. Defined here (the lowest-level module) so
# validation can allow-list them; `api/routes/settings.py` re-exports the same
# names for the /system-prompts route instead of maintaining a second list.
SYSTEM_PROMPT_KEYS = frozenset({
    # --- Roleplay & Core Dialogue ---
    "roleplay_default",
    "narrator",
    "suggest_instruction",
    "chat_impersonate",
    "chat_scene_illustrate",

    # --- Interactive Story Sandbox ---
    "story_continue_default",
    "story_action_rewrite",
    "story_action_expand",
    "story_action_summarize",
    "story_illustrate",
    "story_parse",
    "story_compile",

    # --- Memory & World Vault ---
    "memory_extraction",
    "world_onboarding",
    "world_lore_enrich",
    "world_crossover",
    "world_tick",
    "vision_avatar_analysis",

    # --- Prompt Studio & Expansion ---
    "magic_prompt",

    # --- Character Generator Templates ---
    "charGenDescriptionPrompt",
    "charGenPersonalityPrompt",
    "charGenScenarioPrompt",
    "charGenFirstMesPrompt",
    "charGenMesExamplePrompt",
    "charGenSystemPromptPrompt",
    "charGenVisualTagsPrompt",
    "charGenEnrichPrompt",
})


# Leaf allow-lists for the sections that are written by name at their read
# sites. `update_config` deep-merges, so an unknown leaf used to be written into
# config.json and stay there forever: nothing would ever read it, and only
# `reset_config` could remove it. A typo is now rejected at the door instead.
#
# Each list must contain every leaf of the matching DEFAULT_CONFIG section
# (asserted in tests/test_settings_exposure.py) but may be a superset: `ai` also
# carries optional sampler overrides the frontend writes as `null` to mean
# "engine default", plus `ttsEnabled`, which is frontend-only for now.
SECTION_LEAF_ALLOW_LISTS: dict[str, frozenset[str]] = {
    "ai": frozenset({
        "maxContextTokens",
        "temperature",
        "ragMaxDistance",
        "memoryExtractionEnabled",
        "top_p",
        "max_output_tokens",
        "frequency_penalty",
        "presence_penalty",
        "ttsEnabled",
        "ragEnabled",
        "idleSimEnabled",
        "idleSimIntervalSeconds",
    }),
    "generator": frozenset({"default_checkpoint"}),
    "system_prompts": SYSTEM_PROMPT_KEYS,
    # Nested per-task-type block merged over the top-level job settings by
    # `_job_config`; not a top-level DEFAULT_CONFIG section.
    "jobs.llm": frozenset({"timeout", "max_retries", "stagger_delay"}),
    # Top-level sections that were previously unguarded: typos here were
    # silently deep-merged into config.json and persisted forever, removable
    # only by `reset_config`. Every DEFAULT_CONFIG leaf is listed.
    "worker": frozenset({"poll_interval", "retry_delay", "poll_limit"}),
    "jobs": frozenset({
        "max_concurrent",
        "timeout",
        "max_retries",
        "5xx_max_retries",
        "retry_base_delay",
        "retry_max_delay",
        "llm",
    }),
    "model_sync": frozenset({"interval", "retry_delay", "reconciliation_interval"}),
    "roleplay": frozenset({"label_speakers", "narrator_prefix", "image_prefix"}),
    "downloads": frozenset({"chunk_size", "auto_remove_delay"}),
    "modal": frozenset({"timeout", "max_containers", "scaledown_window"}),
    "api": frozenset({"gzip_minimum_size", "cors_origins"}),
    "jobs_cleanup": frozenset({"max_age_hours", "auto_cleanup", "cleanup_interval"}),
    "image_processing": frozenset({
        "thumbnail_sizes",
        "thumbnail_format",
        "thumbnail_quality",
        "thumbnail_directory",
        "output_date_hierarchy",
        "embed_metadata_in_png",
        "blurhash_components_x",
        "blurhash_components_y",
        "blurhash_resize_max",
    }),
}


def _section_body(config: dict[str, Any], section: str) -> dict[str, Any]:
    """Return ``config[section]`` as a dict, rejecting anything else."""
    body = config[section]
    if not isinstance(body, dict):
        raise ValueError(f"{section} must be an object")
    return body


def _reject_unknown_leaves(section: str, body: dict[str, Any]) -> None:
    """Reject leaves outside the section's allow-list."""
    allowed = SECTION_LEAF_ALLOW_LISTS[section]
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise ValueError(
            f"unknown {section} setting(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(sorted(allowed))}"
        )


def _number(section: str, key: str, value: Any) -> float | None:
    """Coerce a numeric leaf, rejecting bools and non-numbers.

    The older range checks below compare directly, so a string arriving from a
    hand-rolled client raised TypeError (a 500) instead of being reported as bad
    input. `None` is passed through: the settings API uses it to clear an
    optional override.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{section}.{key} must be a number")
    return float(value)


def _check_range(section: str, key: str, value: Any, minimum: Any = None, maximum: Any = None) -> None:
    """Range-check one numeric leaf, ignoring `None`."""
    number = _number(section, key, value)
    if number is None:
        return
    if minimum is not None and number < minimum:
        raise ValueError(f"{section}.{key} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{section}.{key} must be <= {maximum}")


def _check_bool(section: str, key: str, value: Any) -> None:
    """Type-check one boolean leaf, ignoring `None`."""
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{section}.{key} must be a boolean")


def _check_str(section: str, key: str, value: Any, *, allow_blank: bool = False) -> None:
    """Type-check one string leaf, ignoring `None`."""
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{section}.{key} must be a string")
    if not allow_blank and not value.strip():
        raise ValueError(f"{section}.{key} must not be blank")


def _validate_config(config: dict[str, Any]) -> None:
    """
    Validate configuration values.
    
    Args:
        config: Configuration dictionary to validate
        
    Raises:
        ValueError: If validation fails
    """
    # Worker validations
    if "worker" in config:
        worker = config["worker"]
        if "poll_interval" in worker and worker["poll_interval"] <= 0:
            raise ValueError("worker.poll_interval must be > 0")
        if "retry_delay" in worker and worker["retry_delay"] < 0:
            raise ValueError("worker.retry_delay must be >= 0")
        if "poll_limit" in worker and worker["poll_limit"] <= 0:
            raise ValueError("worker.poll_limit must be > 0")
    
    # Jobs validations
    if "jobs" in config:
        jobs = config["jobs"]
        if "max_concurrent" in jobs and jobs["max_concurrent"] <= 0:
            raise ValueError("jobs.max_concurrent must be > 0")
        if "timeout" in jobs and jobs["timeout"] <= 0:
            raise ValueError("jobs.timeout must be > 0")
        if "max_retries" in jobs and jobs["max_retries"] < 0:
            raise ValueError("jobs.max_retries must be >= 0")
        if "retry_base_delay" in jobs and jobs["retry_base_delay"] <= 0:
            raise ValueError("jobs.retry_base_delay must be > 0")
        if "retry_max_delay" in jobs and jobs["retry_max_delay"] <= 0:
            raise ValueError("jobs.retry_max_delay must be > 0")
        # Per-task-type LLM overrides, merged over the top-level values by
        # `_job_config`. Unvalidated until now, so a typo or a negative timeout
        # reached the LLM call path.
        if "llm" in jobs and jobs["llm"] is not None:
            llm = _section_body(jobs, "llm")
            _reject_unknown_leaves("jobs.llm", llm)
            _check_range("jobs.llm", "timeout", llm.get("timeout"), minimum=1)
            _check_range("jobs.llm", "max_retries", llm.get("max_retries"), minimum=0)
            _check_range("jobs.llm", "stagger_delay", llm.get("stagger_delay"), minimum=0)
    
    # Model sync validations
    if "model_sync" in config:
        sync = config["model_sync"]
        if "interval" in sync and sync["interval"] <= 0:
            raise ValueError("model_sync.interval must be > 0")
        if "retry_delay" in sync and sync["retry_delay"] < 0:
            raise ValueError("model_sync.retry_delay must be >= 0")
    

    
    # Download validations
    if "downloads" in config:
        downloads = config["downloads"]
        if "chunk_size" in downloads and downloads["chunk_size"] <= 0:
            raise ValueError("downloads.chunk_size must be > 0")
        if "auto_remove_delay" in downloads and downloads["auto_remove_delay"] < 0:
            raise ValueError("downloads.auto_remove_delay must be >= 0")
    
    # Modal validations
    if "modal" in config:
        modal = config["modal"]
        if "timeout" in modal and modal["timeout"] <= 0:
            raise ValueError("modal.timeout must be > 0")
        if "max_containers" in modal and modal["max_containers"] <= 0:
            raise ValueError("modal.max_containers must be > 0")
        if "scaledown_window" in modal and modal["scaledown_window"] < 0:
            raise ValueError("modal.scaledown_window must be >= 0")
    
    # API validations
    if "api" in config:
        api = config["api"]
        if "gzip_minimum_size" in api and api["gzip_minimum_size"] < 0:
            raise ValueError("api.gzip_minimum_size must be >= 0")
        if "cors_origins" in api and api["cors_origins"] is not None:
            origins = api["cors_origins"]
            if not isinstance(origins, list):
                raise ValueError("api.cors_origins must be a list")
            # Bound once at app construction, so a malformed entry would surface
            # as a CORS failure for the whole UI rather than as bad input here.
            for origin in origins:
                _check_str("api.cors_origins", "entry", origin)
    
    # Jobs cleanup validations
    if "jobs_cleanup" in config:
        cleanup = config["jobs_cleanup"]
        if "max_age_hours" in cleanup and cleanup["max_age_hours"] <= 0:
            raise ValueError("jobs_cleanup.max_age_hours must be > 0")
        if "cleanup_interval" in cleanup and cleanup["cleanup_interval"] <= 0:
            raise ValueError("jobs_cleanup.cleanup_interval must be > 0")
        _check_bool("jobs_cleanup", "auto_cleanup", cleanup.get("auto_cleanup"))
    
    # Image processing validations
    if "image_processing" in config:
        img = config["image_processing"]
        if "thumbnail_quality" in img and not (1 <= img["thumbnail_quality"] <= 100):
            raise ValueError("image_processing.thumbnail_quality must be between 1 and 100")
        if "blurhash_components_x" in img and not (1 <= img["blurhash_components_x"] <= 9):
            raise ValueError("image_processing.blurhash_components_x must be between 1 and 9")
        if "blurhash_components_y" in img and not (1 <= img["blurhash_components_y"] <= 9):
            raise ValueError("image_processing.blurhash_components_y must be between 1 and 9")
        if "blurhash_resize_max" in img and img["blurhash_resize_max"] <= 0:
            raise ValueError("image_processing.blurhash_resize_max must be > 0")
        _check_bool("image_processing", "output_date_hierarchy", img.get("output_date_hierarchy"))
        _check_bool("image_processing", "embed_metadata_in_png", img.get("embed_metadata_in_png"))
        _check_str("image_processing", "thumbnail_format", img.get("thumbnail_format"))
        _check_str("image_processing", "thumbnail_directory", img.get("thumbnail_directory"))
        if "thumbnail_sizes" in img and not isinstance(img["thumbnail_sizes"], dict):
            raise ValueError("image_processing.thumbnail_sizes must be an object")

    # See `get_roleplay_context_config`. Validated here so a typo in
    # config.json is a warning at load rather than a prompt that quietly
    # keeps the behaviour the user was trying to turn off.
    if "roleplay" in config:
        rp = _section_body(config, "roleplay")
        _check_bool("roleplay", "label_speakers", rp.get("label_speakers"))
        _check_str("roleplay", "narrator_prefix", rp.get("narrator_prefix"), allow_blank=True)
        _check_str("roleplay", "image_prefix", rp.get("image_prefix"), allow_blank=True)

    # AI validations
    #
    # `ai`, `generator` and `system_prompts` had no branch here at all, so every
    # key in them was accepted and deep-merged into config.json — including
    # typos and junk. The ranges below match the controls the Settings UI
    # exposes so the form and the API agree on what is valid.
    if "ai" in config:
        ai = _section_body(config, "ai")
        _reject_unknown_leaves("ai", ai)
        _check_range("ai", "maxContextTokens", ai.get("maxContextTokens"), minimum=1024, maximum=32768)
        _check_range("ai", "temperature", ai.get("temperature"), minimum=0, maximum=2)
        _check_range("ai", "top_p", ai.get("top_p"), minimum=0, maximum=1)
        _check_range("ai", "max_output_tokens", ai.get("max_output_tokens"), minimum=1, maximum=131072)
        _check_range("ai", "frequency_penalty", ai.get("frequency_penalty"), minimum=-2, maximum=2)
        _check_range("ai", "presence_penalty", ai.get("presence_penalty"), minimum=-2, maximum=2)
        _check_bool("ai", "ttsEnabled", ai.get("ttsEnabled"))
        _check_bool("ai", "ragEnabled", ai.get("ragEnabled"))
        # pgvector cosine_distance runs 0 (identical) to 2 (opposite), so 2.0
        # is the value that disables the cutoff entirely and restores the old
        # unconditional top-N.
        _check_range("ai", "ragMaxDistance", ai.get("ragMaxDistance"), minimum=0, maximum=2)
        _check_bool("ai", "memoryExtractionEnabled", ai.get("memoryExtractionEnabled"))
        _check_bool("ai", "idleSimEnabled", ai.get("idleSimEnabled"))
        # A non-positive interval would either spin the idle-simulation loop or
        # divide by zero in the scheduler, so it is rejected outright rather
        # than coerced.
        _check_range("ai", "idleSimIntervalSeconds", ai.get("idleSimIntervalSeconds"), minimum=1)

    if "generator" in config:
        generator = _section_body(config, "generator")
        _reject_unknown_leaves("generator", generator)
        _check_str("generator", "default_checkpoint", generator.get("default_checkpoint"))

    if "system_prompts" in config:
        prompts = _section_body(config, "system_prompts")
        _reject_unknown_leaves("system_prompts", prompts)
        for key, value in prompts.items():
            _check_str("system_prompts", key, value)

    if "system_prompt_library" in config:
        library = config["system_prompt_library"]
        if not isinstance(library, list):
            raise ValueError("system_prompt_library must be a list")
        seen_keys: set[str] = set()
        for entry in library:
            if not isinstance(entry, dict):
                raise ValueError("each system_prompt_library entry must be an object")
            unknown = sorted(set(entry) - {"key", "label", "category", "prompt"})
            if unknown:
                raise ValueError(
                    "unknown system_prompt_library field(s): "
                    f"{', '.join(unknown)}. Allowed: category, key, label, prompt"
                )
            key = str(entry.get("key") or "").strip()
            if not key:
                raise ValueError("a system_prompt_library entry needs a key")
            if key in SYSTEM_PROMPT_KEYS:
                raise ValueError(
                    f"system_prompt_library key '{key}' collides with a built-in prompt block"
                )
            if key in seen_keys:
                raise ValueError(f"duplicate system_prompt_library key '{key}'")
            seen_keys.add(key)
            for field in ("label", "category", "prompt"):
                value = entry.get(field)
                if value is not None and not isinstance(value, str):
                    raise ValueError(
                        f"system_prompt_library entry '{key}' field '{field}' must be a string"
                    )


# ============================================================================
# CONVENIENCE FUNCTIONS for accessing common settings
# ============================================================================

# Worker settings
def get_worker_poll_interval() -> float:
    """Get worker poll interval in seconds."""
    return get_config()["worker"]["poll_interval"]


def get_worker_retry_delay() -> int:
    """Get worker retry delay in seconds."""
    return get_config()["worker"]["retry_delay"]


def get_worker_poll_limit() -> int:
    """Get worker poll limit."""
    return get_config()["worker"]["poll_limit"]


# Jobs settings
#
# `get_default_jobs_limit()` and `get_max_jobs_in_memory()` are GONE
# (2026-10-21). They read `jobs.default_limit` and `jobs.max_in_memory`,
# which nothing else read: the job list limit is the hardcoded
# `limit: int = 20` on `GET /api/jobs`, and the in-process queue is an
# unbounded `asyncio.Queue()`.
#
# `get_max_concurrent_jobs()` is gone for the same reason from the other
# direction: the queue reads `jobs.max_concurrent` straight out of the config
# dict, so this accessor had no callers at all.
def _env_var_is_set(env_name: str) -> bool:
    """Check if an environment variable is explicitly set (with COMFY_ prefix)."""
    return os.environ.get(f"COMFY_{env_name}") is not None


# Config paths whose file value is IGNORED when the matching env var is set.
#
# Only keys a getter actually guards with `_env_var_is_set` belong here. Several
# `Settings` fields look like overrides (`worker_poll_interval`,
# `max_concurrent_jobs`, `job_retry_delay`, `modal_*`, `model_sync_*`) but no
# getter consults them, so listing them would tell a UI that a field is
# environment-controlled when the env var has no effect at all — the same class
# of lie as a phantom config key.
#
# `api.worker_backend_url` is also env-overridable (see
# `get_worker_backend_url`) but is absent from DEFAULT_CONFIG, so it is absent
# here too and stays out of the settings schema.
ENV_VAR_OVERRIDES: dict[str, str] = {
    "jobs.timeout": "COMFY_JOB_TIMEOUT",
    "jobs.max_retries": "COMFY_JOB_MAX_RETRIES",
    "jobs.retry_base_delay": "COMFY_JOB_RETRY_BASE_DELAY",
    "jobs.retry_max_delay": "COMFY_JOB_RETRY_MAX_DELAY",
    "api.cors_origins": "COMFY_CORS_ORIGINS",
    "api.gzip_minimum_size": "COMFY_GZIP_MINIMUM_SIZE",
}


def get_env_var_overrides() -> dict[str, str]:
    """Return ``{config_path: env_var_name}`` for the overrides *currently set*.

    The settings UI reads this to render an env-overridden field read-only:
    writing it would appear to succeed while the env var kept winning.
    """
    return {
        path: env_name
        for path, env_name in ENV_VAR_OVERRIDES.items()
        if os.environ.get(env_name) is not None
    }


def _normalize_worker_backend_url(url: str | None) -> str:
    """Normalize legacy or empty worker backend URL values."""
    default_url = "http://backend_v2:8002"
    candidate = (url or "").strip()

    if not candidate:
        return default_url

    if "comfy-backend-v2" in candidate:
        normalized = candidate.replace("comfy-backend-v2", "backend_v2")
        _cfg_logger.warning(
            "worker_backend_url_normalized_legacy_host",
            original=candidate,
            normalized=normalized,
        )
        return normalized

    return candidate


def _job_config(task_type: str = "image") -> dict:
    """Return the effective jobs config for a task_type, merging a type-specific
    override block (e.g. ``jobs.llm``) over the top-level defaults."""
    config = dict(get_config()["jobs"])
    base = {k: v for k, v in config.items() if k not in ("image", "llm")}
    if task_type in config and isinstance(config[task_type], dict):
        base.update(config[task_type])
    return base


def get_job_timeout(task_type: str = "image") -> int:
    """Get job timeout in seconds. Prefers env var (settings), falls back to file config."""
    # Use Pydantic settings if explicitly set via env var, else use file config for runtime updates
    return settings.job_timeout if _env_var_is_set("JOB_TIMEOUT") else _job_config(task_type)["timeout"]


def get_job_max_retries(task_type: str = "image") -> int:
    """Get maximum number of job retries. Prefers env var, falls back to file config."""
    return settings.job_max_retries if _env_var_is_set("JOB_MAX_RETRIES") else _job_config(task_type)["max_retries"]


def get_job_5xx_max_retries(task_type: str = "image") -> int:
    """Maximum retries for 5xx provider errors before failing over.

    5xx errors are server-side and often indicate an overloaded or unhealthy
    provider. Retrying them N times on the same provider burns paid
    inferences before failover ever gets a chance. This cap is lower than the
    general max_retries so a flaky provider fails over quickly.

    Prefers env var COMFY_5XX_MAX_RETRIES, falls back to file config
    jobs.5xx_max_retries, then 1.
    """
    if _env_var_is_set("5XX_MAX_RETRIES"):
        return settings.job_5xx_max_retries
    return _job_config(task_type).get("5xx_max_retries", 1)


def get_job_retry_base_delay(task_type: str = "image") -> float:
    """Get base delay for exponential backoff in seconds. Prefers env var, falls back to file config."""
    return settings.job_retry_base_delay if _env_var_is_set("JOB_RETRY_BASE_DELAY") else _job_config(task_type)["retry_base_delay"]


def get_job_retry_max_delay(task_type: str = "image") -> float:
    """Get maximum delay for exponential backoff in seconds. Prefers env var, falls back to file config."""
    return settings.job_retry_max_delay if _env_var_is_set("JOB_RETRY_MAX_DELAY") else _job_config(task_type)["retry_max_delay"]


def get_llm_failover_stagger_delay() -> float:
    """Get the stagger delay (seconds) between LLM provider failover attempts."""
    return _job_config("llm").get("stagger_delay", 2.0)


def get_system_prompt_blocks() -> dict:
    """Get configurable system prompt blocks (roleplay_default, narrator, ...).
    File config wins per-key; DEFAULT_CONFIG fills the rest.

    The user's own library entries are merged in as well, so a prompt the
    Studio added is usable by key everywhere a built-in one is.
    """
    configured = get_config().get("system_prompts", {}) or {}
    defaults = DEFAULT_CONFIG.get("system_prompts", {}) or {}
    merged = dict(defaults)
    if isinstance(configured, dict):
        merged.update({k: v for k, v in configured.items() if isinstance(v, str) and v.strip()})
    for entry in get_system_prompt_library():
        key = str(entry.get("key") or "").strip()
        prompt = str(entry.get("prompt") or "").strip()
        if key and prompt:
            merged[key] = prompt
    return merged


def get_system_prompt_library() -> list:
    """The user's own system-prompt blocks, as a list of entries.

    Each entry is `{"key", "label", "category", "prompt"}`. The list is
    returned as stored, with the built-in defaults supplied for the optional
    fields so the Studio always has something to render.
    """
    entries = get_config().get("system_prompt_library", []) or []
    if not isinstance(entries, list):
        return []
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "").strip()
        if not key:
            continue
        out.append({
            "key": key,
            "label": str(entry.get("label") or key),
            "category": str(entry.get("category") or "Custom"),
            "prompt": str(entry.get("prompt") or ""),
        })
    return out


# Model sync settings
def get_model_sync_interval() -> int:
    """Get model sync interval in seconds."""
    return get_config()["model_sync"]["interval"]


def get_model_sync_retry_delay() -> int:
    """Get model sync retry delay in seconds."""
    return get_config()["model_sync"]["retry_delay"]


def get_reconciliation_interval() -> int:
    """Get reconciliation interval in seconds."""
    return get_config()["model_sync"]["reconciliation_interval"]


def get_worker_backend_url() -> str:
    """Get backend URL exposed to provider containers. Prefers env var, falls back to file config."""
    default_url = "http://backend_v2:8002"
    configured_url = (
        settings.worker_backend_url
        if _env_var_is_set("WORKER_BACKEND_URL")
        else get_config()["api"].get("worker_backend_url", default_url)
    )
    return _normalize_worker_backend_url(configured_url)





# Download settings
def get_download_chunk_size() -> int:
    """Get download chunk size in bytes."""
    return get_config()["downloads"]["chunk_size"]


def get_download_auto_remove_delay() -> int:
    """Get download auto-remove delay in seconds."""
    return get_config()["downloads"]["auto_remove_delay"]


# Modal settings
def get_modal_timeout() -> int:
    """Get Modal timeout in seconds."""
    return get_config()["modal"]["timeout"]


def get_modal_max_containers() -> int:
    """Get Modal max containers."""
    return get_config()["modal"]["max_containers"]


def get_modal_scaledown_window() -> int:
    """Get Modal scaledown window in seconds."""
    return get_config()["modal"]["scaledown_window"]


# API settings
def get_cors_origins() -> list[str]:
    """Get CORS origins list."""
    if _env_var_is_set("CORS_ORIGINS"):
        return settings.cors_origins
    api_config = get_config().get("api", {})
    return api_config.get("cors_origins", settings.cors_origins)


def get_gzip_minimum_size() -> int:
    """Get GZip minimum size in bytes."""
    if _env_var_is_set("GZIP_MINIMUM_SIZE"):
        try:
            return max(0, int(os.environ["COMFY_GZIP_MINIMUM_SIZE"]))
        except (TypeError, ValueError):
            _cfg_logger.warning("invalid_gzip_minimum_size", value=os.environ.get("COMFY_GZIP_MINIMUM_SIZE"))
    configured = get_config().get("api", {}).get("gzip_minimum_size")
    if configured is not None:
        try:
            return max(0, int(configured))
        except (TypeError, ValueError):
            pass
    return max(0, int(settings.gzip_minimum_size))


# Jobs cleanup settings
def get_jobs_cleanup_max_age() -> int:
    """Get max age for job cleanup in hours."""
    return get_config()["jobs_cleanup"]["max_age_hours"]


def get_jobs_cleanup_auto() -> bool:
    """Get whether auto cleanup is enabled."""
    return get_config()["jobs_cleanup"]["auto_cleanup"]


def get_jobs_cleanup_interval() -> int:
    """Get cleanup interval in seconds."""
    return get_config()["jobs_cleanup"]["cleanup_interval"]


# Image processing settings
def get_thumbnail_sizes() -> dict:
    """Get thumbnail sizes configuration."""
    return get_config()["image_processing"]["thumbnail_sizes"]


def get_thumbnail_quality() -> int:
    """Get thumbnail JPEG quality (1-100)."""
    return get_config()["image_processing"]["thumbnail_quality"]


def get_blurhash_components():
    """Get blurhash components as (x, y) tuple."""
    cfg = get_config()["image_processing"]
    return (cfg["blurhash_components_x"], cfg["blurhash_components_y"])


def get_blurhash_resize_max() -> int:
    """Get blurhash resize max dimension."""
    return get_config()["image_processing"]["blurhash_resize_max"]


def get_thumbnail_format() -> str:
    """Get thumbnail format (webp, png, jpg)."""
    return get_config()["image_processing"].get("thumbnail_format", "webp")


def get_thumbnail_directory() -> str:
    """Get thumbnail subdirectory name."""
    return get_config()["image_processing"].get("thumbnail_directory", "thumb")


def get_output_date_hierarchy() -> bool:
    """Get whether to use date-based output hierarchy (YYYY/MM/DD/)."""
    return get_config()["image_processing"].get("output_date_hierarchy", True)


def get_embed_metadata_in_png() -> bool:
    """Get whether to embed metadata directly in PNG files."""
    return get_config()["image_processing"].get("embed_metadata_in_png", True)


def get_roleplay_context_config() -> dict:
    """How a stored chat message is mapped onto an LLM turn.

    `label_speakers`, `narrator_prefix` and `image_prefix` — see the `roleplay`
    block in DEFAULT_CONFIG.

    Defensive about types rather than trusting `_validate` alone: a file config
    that fails validation is discarded whole, but a partially-merged one is not,
    and a non-string prefix would be interpolated straight into a prompt. A
    boolean that is not a bool falls back to True, because a string like
    "false" would otherwise be truthy and the setting could never be turned off.
    """
    body = get_config().get("roleplay")
    body = body if isinstance(body, dict) else {}
    label = body.get("label_speakers")
    if not isinstance(label, bool):
        label = True

    def _prefix(key: str, default: str) -> str:
        value = body.get(key)
        return value if isinstance(value, str) else default

    return {
        "label_speakers": label,
        "narrator_prefix": _prefix("narrator_prefix", "[Narration]"),
        "image_prefix": _prefix("image_prefix", "[Scene]"),
    }
