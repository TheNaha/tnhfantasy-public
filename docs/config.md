# Configuration reference — `config.json` settings leaves

`.env.example` is the canonical reference for every `COMFY_*` environment variable
(the infra/secrets layer, highest precedence). This page covers the second
layer: the leaves of `DEFAULT_CONFIG` in `backend_v2/config.py`, which are
runtime-editable through the Settings UI (`GET`/`PUT /api/settings`) and
persisted to `config.json`.

## Precedence (highest to lowest)

1. `COMFY_*` environment variables (via `backend_v2/config.py` `Settings`)
2. `config.json` — runtime-editable via the Settings UI, written atomically
3. `DEFAULT_CONFIG` in `backend_v2/config.py` — compiled-in fallback

The loader deep-merges `config.json` over `DEFAULT_CONFIG`, so a file that
omits a leaf keeps the compiled-in default. `config.json` defaults to
`backend_v2/config.json`; `COMFY_CONFIG_PATH` overrides it (Compose sets
`/data/config.json`, on the durable bind mount, so Settings UI changes survive
container recreates — without the override the container's own writable layer is
used and every change is lost on recreate).

## How validation works

Every leaf written through `PUT /api/settings` is checked against
`SECTION_LEAF_ALLOW_LISTS` (an unknown leaf is rejected with a 400) and then
against `_validate_config` range rules. `null` clears an optional override;
`""` on `generator.default_checkpoint` means "unset" and falls back to
`DEFAULT_CHECKPOINT` (`sd_xl_base_1.0.safetensors`). `extra="forbid"` applies
to several request models, so a misspelled leaf is a 422, not a silent drop.

`jobs_cleanup.*` is a documented exception: the leaves exist, are validated and
persisted, but nothing consumes them — the `jobs` table is not pruned by any
scheduled job today. See `docs/maintenance/audit-2026-11-09.md` finding F1.

## Section: `worker`

| Leaf | Type | Default | Range / rule | Purpose |
|---|---|---|---|---|
| `poll_interval` | float | `0.3` | `> 0` | Seconds the job-queue worker loop sleeps between polls. |
| `retry_delay` | int | `5` | `>= 0` | Seconds between job-retry attempts. |
| `poll_limit` | int | `50` | `> 0` | Max jobs fetched per poll cycle. |

Env overrides: none of these have a `COMFY_*` form; they live only in
`config.json`.

## Section: `jobs`

| Leaf | Type | Default | Range / rule | Purpose |
|---|---|---|---|---|
| `max_concurrent` | int | `5` | `> 0` | Max concurrent jobs the queue runs. Editable in Settings but enforced only through the job-runner; lowering it does not throttle a job already in flight. |
| `timeout` | int | `3600` | `> 0` | Client-side stream timeout for image jobs, seconds. Env override: `COMFY_JOB_TIMEOUT`. Do not set below the worker's own limit or a still-running workflow is abandoned. |
| `max_retries` | int | `3` | `>= 0` | Max retries for a failed job. Env override: `COMFY_JOB_MAX_RETRIES`. |
| `5xx_max_retries` | int | `1` | — | Max retries specifically for 5xx provider errors. Env override: `COMFY_5XX_MAX_RETRIES` (maintenance-sweep knob, auto-discovered by `test_env_contracts`). |
| `retry_base_delay` | float | `1.0` | `> 0` | Base seconds for tenacity exponential backoff. Env override: `COMFY_JOB_RETRY_BASE_DELAY`. |
| `retry_max_delay` | float | `60.0` | `> 0` | Cap on the backoff delay. Env override: `COMFY_JOB_RETRY_MAX_DELAY`. |

`jobs.llm` (per-task-type overrides, merged over the top-level job settings):

| Leaf | Type | Default | Range / rule | Purpose |
|---|---|---|---|---|
| `timeout` | int | `180` | `>= 1` | LLM job timeout. |
| `max_retries` | int | `2` | `>= 0` | LLM job max retries. |
| `stagger_delay` | float | `2.0` | `>= 0` | Stagger between LLM failover attempts. |

## Section: `model_sync`

| Leaf | Type | Default | Range / rule | Purpose |
|---|---|---|---|---|
| `interval` | int | `300` | `> 0` | Model-sync interval, seconds. Env override: `COMFY_MODEL_SYNC_INTERVAL` (read as `model_sync_interval`). |
| `retry_delay` | int | `10` | `>= 0` | Retry delay after a sync failure. |
| `reconciliation_interval` | int | `120` | — | Model-reconciliation interval. Env override: `COMFY_RECONCILIATION_INTERVAL` (read as `reconciliation_interval`). |

## Section: `roleplay`

| Leaf | Type | Default | Purpose |
|---|---|---|---|
| `label_speakers` | bool | `true` | Prefix each speaking turn with the speaker's name; noise in single-character chats, the only turn discriminator in multi-character ones. |
| `narrator_prefix` | string | `"[Narration]"` | Prefix for narrator turns. Never sent as `role: "system"` (providers that concatenate system messages would bury narration at the end of instructions). |
| `image_prefix` | string | `"[Scene]"` | Prefix for image turns, kept in position so the model knows an illustration happened where it happened. |

## Section: `downloads`

| Leaf | Type | Default | Range / rule | Purpose |
|---|---|---|---|---|
| `chunk_size` | int | `8192` | `> 0` | Bytes per download chunk. Env override: `COMFY_DOWNLOAD_CHUNK_SIZE` (read as `download_chunk_size`). |
| `auto_remove_delay` | int | `5` | `>= 0` | Seconds before a downloaded model file is auto-removed. Env override: `COMFY_DOWNLOAD_AUTO_REMOVE_DELAY` (read as `download_auto_remove_delay`). |

## Section: `modal`

| Leaf | Type | Default | Range / rule | Purpose |
|---|---|---|---|---|
| `timeout` | int | `300` | `> 0` | Modal call timeout. Env override: `COMFY_MODAL_TIMEOUT` (read as `modal_timeout`). |
| `max_containers` | int | `1` | `> 0` | Max concurrent Modal containers. Env override: `COMFY_MODAL_MAX_CONTAINERS` (read as `modal_max_containers`). |
| `scaledown_window` | int | `5` | `>= 0` | Modal scale-down window. Env override: `COMFY_MODAL_SCALEDOWN_WINDOW` (read as `modal_scaledown_window`). |

The removed `modal.vllm` block (gpu_type / timeout_seconds / max_model_len) is
deliberately absent: nothing read it, and the LLM Modal engine reads its own
`MODAL_VLLM_*` environment variables instead.

## Section: `api`

| Leaf | Type | Default | Purpose |
|---|---|---|---|
| `gzip_minimum_size` | int | `1000` | Responses below this many bytes are not gzipped. Env override: `COMFY_GZIP_MINIMUM_SIZE`. |
| `cors_origins` | list of strings | six origins | Every origin the stack is reached on; port and scheme matter (e.g. `https://100.150.0.4` does not match `http://100.150.0.4:5174`). Omitting the frontend's direct origin makes socket.io return 400 and realtime stays dead while HTTP looks fine. Env override: `COMFY_CORS_ORIGINS`. |

The default list:
`http://localhost:5174`, `http://localhost:8002`, `http://127.0.0.1:5174`,
`https://comfy.lan.thenaha.my.id`, `https://100.150.0.4`,
`http://100.150.0.4:5174`.

## Section: `jobs_cleanup`

| Leaf | Type | Default | Range / rule | Consumed? |
|---|---|---|---|---|
| `max_age_hours` | int | `24` | — | No (D2 — see above) |
| `auto_cleanup` | bool | `false` | — | No (D2 — see above) |
| `cleanup_interval` | int | `3600` | — | No (D2 — see above) |

These are validated and persisted through Settings but `run_data_cleanup()`
prunes provider-state artifacts, stale providers, and orphaned models only —
never old jobs. Flagged for operator decision because enabling consumption
deletes user data.

## Section: `image_processing`

| Leaf | Type | Default | Purpose |
|---|---|---|---|
| `thumbnail_sizes` | object | `{"medium": 512}` | Thumbnail size presets. |
| `thumbnail_format` | string | `"webp"` | Thumbnail image format. |
| `thumbnail_quality` | int | `90` | Thumbnail JPEG/WebP quality. |
| `thumbnail_directory` | string | `"thumb"` | Subdirectory for thumbnails under the asset output tree. |
| `output_date_hierarchy` | bool | `true` | Partition output images under `YYYY/MM/DD/`. |
| `embed_metadata_in_png` | bool | `true` | Embed generation metadata in PNG sidecars. An editable Settings toggle the PNG writer consults. |
| `blurhash_components_x` | int | `4` | Blurhash X components. |
| `blurhash_components_y` | int | `3` | Blurhash Y components. |
| `blurhash_resize_max` | int | `64` | Blurhash resize max dimension. |

## Section: `generator`

| Leaf | Type | Default | Purpose |
|---|---|---|---|
| `default_checkpoint` | string | `sd_xl_base_1.0.safetensors` | Default ComfyUI checkpoint. `""` means unset → falls back to `DEFAULT_CHECKPOINT`. Env: none; resolved through `resolve_default_checkpoint()`. |
| `preview_method` | string | `"auto"` | `"auto"` for live preview, `"none"` for max speed. |
| `live_preview` | bool | `true` | Whether live preview is enabled (overridden by `preview_method == "none"`). |

## Section: `ai`

| Leaf | Type | Default | Purpose |
|---|---|---|---|
| `maxContextTokens` | int | `4096` | Global chat context budget, range-checked 1024–32768. |
| `temperature` | float | `0.8` | Default sampling temperature. |
| `idleSimEnabled` | bool | `false` | Idle simulation (autonomous character activity while away). Registration switch `COMFY_IDLE_SIM_ENABLED` checked at startup; interval overridden by `COMFY_IDLE_SIM_INTERVAL_SECONDS`. |
| `idleSimIntervalSeconds` | int | `600` | Idle-simulation tick interval. |
| `ragEnabled` | bool | `true` | Whether RAG/semantic memory search is enabled. |
| `ragMaxDistance` | float | `0.6` | Cosine-distance cutoff for semantic retrieval (0 identical, 1.0 orthogonal, 2.0 opposite). Above this is noise. |
| `memoryExtractionEnabled` | bool | `true` | Whether a chat reply may enqueue the paid background memory-extraction call. |

Optional sampler-override leaves (frontend writes `null` for "engine default"):
`top_p`, `max_output_tokens`, `frequency_penalty`, `presence_penalty`.
Frontend-only leaf: `ttsEnabled`.

## Section: `system_prompts`

Fixed system-prompt blocks the code looks up by name (allow-listed in
`SYSTEM_PROMPT_KEYS`). Each key maps to a prompt template string:

- Roleplay & Core Dialogue: `roleplay_default`, `narrator`,
  `suggest_instruction`, `chat_impersonate`, `chat_scene_illustrate`
- Story Sandbox: `story_continue_default`, `story_action_rewrite`,
  `story_action_expand`, `story_action_summarize`, `story_illustrate`,
  `story_parse`, `story_compile`
- Memory & World Vault: `memory_extraction`, `world_onboarding`,
  `world_lore_enrich`, `world_crossover`, `world_tick`, `vision_avatar_analysis`
- Prompt Studio & Expansion: `magic_prompt`
- Character Generator Templates: `charGenDescriptionPrompt`,
  `charGenPersonalityPrompt`, `charGenScenarioPrompt`,
  `charGenFirstMesPrompt`, `charGenMesExamplePrompt`,
  `charGenSystemPromptPrompt`, `charGenVisualTagsPrompt`,
  `charGenEnrichPrompt`

These are fixed keys; the set cannot grow through config. To add a prompt
block, use `system_prompt_library` below.

## Section: `system_prompt_library`

A list (default `[]`) of `{"key", "label", "category", "prompt"}` entries.
The key is what the system looks a block up by; entries are merged into
`get_system_prompt_blocks()` alongside the fixed `system_prompts` keys. This
is the extensible replacement for the old fixed-set design: add, edit, remove
without touching the schema.

## Related

- `.env.example` — every `COMFY_*` env var, code-cited (infra/secrets layer).
- `backend_v2/config.py` — `DEFAULT_CONFIG`, `Settings`, `update_config`,
  `reset_config`, `SECTION_LEAF_ALLOW_LISTS`, `_validate_config`.
- `docs/deployment.md` — `COMFY_CONFIG_PATH` and the production config.json
  durability pitfall.
- `docs/maintenance/audit-2026-11-09.md` — finding F1 (`jobs_cleanup` never
  consumed) and F3 (`charGen*` prompts hardcoded/duplicated in the frontend).
