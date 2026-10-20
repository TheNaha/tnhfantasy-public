# Roleplay System Remediation & Unification Plan

**Status:** implementation-ready
**Scope:** backend `backend_v2/`, frontend `frontend_v2/`, migrations, docs
**Origin:** roleplay system review (2026-10-19) — architecture is sound at the data/API layer, but the agentic pipeline on top of it is half-dead and fails silently.

---

## 1. Context

The review established that the roleplay subsystem's **data and API layer is genuinely cohesive** (21 entities, every one with a route and a live frontend consumer; World membership normalized under `services/world_ownership.py`; one `build_context(session, workspace)` serving both chat and story modes). What is not cohesive:

- **3 live defects** were proven empirically (exact tracebacks, live production curl):
  1. `TypeError: build_llm_workflow() got an unexpected keyword argument 'temperature'` — `services/updater_service.py:591-592` vs `services/llm_workflow.py:22-38`. The `try:` in that function starts at line **600**, *after* the call, so the error escapes and lands in `services/job_processing.py:1230` → `logger.debug`. Kills **Stage 4 (Updater)**, and with it Stage 5 (memory extraction) and Stage 6 (Chain), because the whole post-turn block aborts at line 1185.
  2. `ImportError: cannot import name 'render_agent_template' from 'services.agent_variants'` — `services/job_processing.py:467` and `:1082`. The function lives in `services/chat_utils.py:328`. Kills **Stage 6 (Chain)** and the **continuation** path.
  3. `GET /api/v2/llm/agents/with-variants` → **HTTP 500 in production right now** (verified against the running `tnhcomfy-backend`). `api/routes/world_vault/llm_config.py:688` reads `profile.avatar_path`; `AgentProfile` (`core/entities.py:1587-1601`) has no such column.
- **Director Tier 3 is a dead tier.** `services/decision_service.py:316-327` reads `event.get("event") == "token"` and `event.get("status") == "success"`. No engine emits `"event": "token"` anywhere in the backend; engines emit `delta`/`completed`. `full_text` stays empty, Tier 3 returns `None`, the cascade always falls through to the Tier 4 deterministic heuristic.
- **Duplicated API surface:** `api/routes/world_vault/__init__.py:45,51` mount `llm_config_router` and `agents_router` a second time under `/world-vault/llm` and `/world-vault/agents` — 32 duplicate OpenAPI paths.
- **Dead code paths:** `services/job_processing.py:919-921` allow-lists tools `narrate_scene` and `update_world_state` that do not exist in `AGENTIC_TOOLS`; `MAX_AGENTIC_NARRATIONS_PER_EXCHANGE` (`services/orchestrator_service.py:45`) is never read.
- **TTS and Image share LoadBalancer runtime state** (`state_id=1`): `provider_failures` and `round_robin_index` are shared, so a TTS outage can trip the image circuit breaker for a provider serving both, and `get_stats` reports shared counters as a per-modality rollup.
- **The Updater's prompt is hardcoded** (`services/updater_service.py:507`); its `AgentProfile` row and variants are never read.
- **The 6-stage manifest is declarative-only.** `services/chat_pipeline.py` `PIPELINE_STAGES` is served to the UI via `GET /llm/pipeline` but **no code reads it**; execution is hardcoded in `services/job_processing.py`. Limits (4 turns / 4 continuations / 0.55 gate threshold) are duplicated across `chat_pipeline.py`, `core/entities.py:1380,1409`, `services/decision_schema.py:14,19` and hardcoded at `job_processing.py:1081`.
- **Frontend:** 3 dead internal links, no Character→its-Chats view, no worker-health surface, `context_trace["selected_agent"]` written but never read, the 16-gate registry hardcoded in the chat HUD while the canonical one is served by `GET /llm/director/gates`.
- **Backend suite:** `12 failed, 3719 passed, 5 skipped`. None are the 3 live defects, but two are in the roleplay path (`KeyError: 'agentic'` in the scene/swipe routes) and the route-count assertion is coupled to the mount deletion.

**Critical constraint:** the whole post-turn Director block is wrapped in `except Exception → logger.debug` (`services/job_processing.py:1230-1231`). This is *why* three defects produced a green test suite and a silent production failure. Every task in Phase A must also fix the observability that hid it.

---

## 2. Decisions locked with the user

| # | Decision | Choice |
|---|---|---|
| D1 | Scope | Everything, including structural refactors |
| D2 | Duplicate mounts | **Delete** both (`/world-vault/llm/*`, `/world-vault/agents/*`) |
| D3 | Chat↔Story link | **Two nullable provenance FKs** (`Chat.story_id`, `Story.chat_id`) |
| D4 | `AgentProfile.avatar_path` | **Add the column properly** (model + migration + upload endpoint + frontend) |
| D5 | Director cascade | **Stay out-of-band**; fix the event dialect + make Tier 3 provider selection health-aware |
| D6 | LoadBalancer split | **Separate `state_id` per modality** (TTS → 3) |
| D7 | Updater prompt | **Wire it to the `AgentProfile`** (resolve profile + active variant, fall back to hardcoded) |
| D8 | Pre-existing failures | **Fix all 12** in this plan |
| D9 | Gallery code in `world_vault/` | **Move the files, keep the URLs** unchanged |
| D10 | Pipeline manifest | **Make the manifest drive execution** (not just describe it) |

### D10 — what "drive execution" concretely means

The 6 stages are **not** a linear walk: Triage runs in the request path, Act *is* the generation, Audit runs post-generation, and Update/Illustrate/Chain are each enqueued as a **separate job** (Update additionally carries a `pending_chain` payload so Chain runs in the Updater's completion hook to avoid a stale-state race). Continuation is an early-return branch out of Audit, not a stage of its own.

So the manifest becomes the **authoritative stage registry**, not a loop body:

- `PipelineStage` gains `executor: str` — a dotted path to the function that performs the stage (resolved lazily, so no import cycle).
- `next_stages` becomes an **ordered** tuple so it encodes order, not just adjacency.
- A new `services/pipeline_runner.py` owns: stage lookup, limit resolution, and `run_stage(key, ctx)`. `services/job_processing.py` and `api/routes/world_vault/chats.py` call the runner instead of calling stage functions directly, so **enablement, ordering, and limits come from the manifest** while the work stays in the existing functions.
- Limits move to a single leaf module and are imported by the manifest, the entities, and the decision schema — so `GET /llm/pipeline` can never quote a number the code does not use.

**The refactor must be behaviour-preserving.** The four bug fixes are separate, deliberate deltas and are sequenced *before* the refactor (Phase A then Phase G), with Phase B's tests as the safety net.

---

## 3. Ordered tasks

Phases run in order. Within a phase, tasks are listed in dependency order.

### Phase A — Stop the bleeding (live defects + observability)

- **A1.** `backend_v2/services/job_processing.py:467` and `:1082` — split the bad import:
  ```python
  from services.agent_variants import resolve_agent
  from services.chat_utils import render_agent_template
  ```
  (matches the correct usage already at `api/routes/world_vault/agents.py:22` and `services/illustrator_service.py:121`).
- **A2.** `backend_v2/services/updater_service.py:577-598` — remove the `temperature=0.2` / `max_output_tokens=600` kwargs and pass `samplers={"temperature": 0.2, "max_output_tokens": 600}` instead. `build_llm_workflow` merges `samplers` into the workflow at `services/llm_workflow.py:84-85` with caller samplers winning over the role sampler, which is the intended precedence.
- **A3.** `backend_v2/core/entities.py` — add `avatar_path: str | None = Field(default=None)` to `AgentProfile` (after `max_tokens`, line 1599). This makes `api/routes/world_vault/llm_config.py:688` resolve, killing the live 500.
- **A4.** `backend_v2/infrastructure/migrations/steps.py` — add **migration 105** `_migration_105_agent_profile_avatar_path(conn)`: `ALTER TABLE agent_profiles ADD COLUMN avatar_path TEXT`. Register it in `_get_schema_migration_steps()` after the `104_variant_routing_tags` entry (line 1888-1892) as `MigrationStep(version="105_agent_profile_avatar_path", description=..., apply_fn=...)`.
- **A5.** `backend_v2/services/decision_service.py:268-344` — fix the Tier 3 event dialect: accumulate `event["text"]` on `event == "delta"`, and on `event == "completed"` take `event["outputs"][0]["content"]` (fall back to `["text"]`). Drop the `"event" == "token"` and `"status" == "success"` branches. Keep the 15 s timeout.
- **A6.** `backend_v2/services/decision_service.py:278-284` — replace the health-blind `resolve_default_provider(self.session)` with LoadBalancer selection: `create_load_balancer(self.session, task_type="llm").get_next_provider(task_type="llm")` (async; the method is already async). Fall back to `resolve_default_provider` only if the LB returns nothing.
- **A7.** `backend_v2/services/job_processing.py:1230-1231` — `logger.debug` → `logger.warning` for `post_turn_director_or_memory_hook_failed`. Also `api/routes/world_vault/chats.py:1150-1151` `send_message_director_eval_skipped` → `logger.warning`. In `services/decision_service.py`, raise the *exception* paths in the cascade from `logger.debug` to `logger.warning` (lines ~132, ~183, ~230, ~265, ~343) — but leave the "tier not available" `return None` paths quiet, since a missing remote agent is normal.
- **A8.** `backend_v2/services/job_processing.py:919-921` — replace the allow-list `{"generate_image", "narrate_scene", "update_world_state"}` with `{"generate_image"}` (the only tool in `AGENTIC_TOOLS`, `services/orchestrator_service.py:84-114`).
- **A9.** `backend_v2/services/orchestrator_service.py:45` — delete `MAX_AGENTIC_NARRATIONS_PER_EXCHANGE` and the stale comment block at lines 39-43 that describes the deleted `narrate_scene` tool.
- **A10.** Grep the frontend for `max_agentic_narrations` / `maxAgenticNarrations`. If a UI control exposes it, either implement the narration tool or remove the control; if nothing exposes it, record the `Chat.max_agentic_narrations` / `Story.max_agentic_narrations` columns as vestigial in `docs/STATUS.md` (do **not** drop the columns — that is a separate API/DB break).

### Phase B — Close the coverage hole (lock in Phase A)

New file: `backend_v2/tests/test_chat_pipeline_execution.py`.

- **B1.** `_stage_chain` — assert a next-turn LLM job is enqueued when the chaining decision says continue, and that nothing is enqueued when it says stop or when `next_speaker == "user"`.
- **B2.** `enqueue_state_updater_if_needed` — assert an `llm` job is created with `type == "state_updater"`, `background == True`, and that the gated schema contains only the fired gates' fields.
- **B3.** Continuation — an audit returning `is_complete=False` produces a continuation job with `continuation_count == 1` and `source == "continuation"`.
- **B4.** Director Tier 3 — feed a fake engine emitting canonical `delta` + `completed` events; assert a non-`None` decision whose `engine_used` starts with `util_llm_json`.
- **B5.** `GET /api/v2/llm/agents/with-variants` — **seed at least one `AgentProfile`** in the test. The existing `tests/test_director_and_updater.py:773-786` guards with `if body:` and the pytest DB has no seeded agents, which is exactly why the `avatar_path` 500 was never caught. Assert `avatar_path` is present in the payload.
- **B6.** An integration test: a completed `chat_reply` job produces a `state_updater` job **and** a chained job. This is the single test that would have caught all three Phase A defects.

### Phase C — API surface cleanup

- **C1.** `backend_v2/api/routes/world_vault/__init__.py` — delete lines **45** and **51** (the duplicate `/world-vault/llm` and `/world-vault/agents` mounts).
- **C2.** `backend_v2/tests/test_model_catalog.py:84,94,103,111` — repoint from `/api/v2/world-vault/llm/catalog…` to `/api/v2/llm/catalog…`.
- **C3.** Delete the 3 superseded expression sub-routes in `backend_v2/api/routes/world_vault/characters.py` (`:388` POST, `:407` PUT, `:423` DELETE). `PATCH /characters/{id}` (`api/routes/world_vault/characters.py` + frontend `hooks/useExpressions.js:13`) becomes the **single** expression write path — the current two-writer setup forces the renderer to pick a winner at `frontend_v2/src/components/chat/ExpressionSelector.jsx:15`.
- **C4.** Delete `GET /llm/traces/{chat_id}` (`backend_v2/api/routes/world_vault/llm_config.py:839`). It duplicates `GET /chats/{chat_id}/director-traces` (`chats.py:2844`), which is the one the frontend uses (`frontend_v2/src/hooks/usePipeline.js:60`).
- **C5.** **Keep** the per-entity `GET /{id}` detail routes, `GET /memories`, `POST /voices/speak`, `GET /world-vault/onboarding/archetypes` — these are legitimate REST surface that the SPA happens not to call. They are not defects. (Three of them get real consumers in Phase H.)

### Phase D — Data model additions

- **D1.** `backend_v2/core/entities.py` — `Chat`: add `story_id: str | None = Field(default=None, foreign_key="chats.id")`… **careful — use the correct FK target**: `story_id: str | None = Field(default=None, index=True)` pointing at `stories.id`; `Story`: add `chat_id: str | None = Field(default=None, index=True)` pointing at `chats.id`. Both nullable, no cycle: a chat exported *from* a story sets `Story.chat_id`; a chat started *from* a story sets `Chat.story_id`. Never both for the same pair.
- **D2.** `backend_v2/infrastructure/migrations/steps.py` — **migration 106** `_migration_106_chat_story_provenance(conn)`: add both columns + indexes to `chats` and `stories`. Register after migration 105.
- **D3.** `backend_v2/api/routes/world_vault/chats.py:2596` (`POST /{chat_id}/export-story`) — set `Story.chat_id = chat_id` on the created story.
- **D4.** `backend_v2/api/routes/world_vault/stories.py:2864` (`POST /{story_id}/start-chat`) — set `Chat.story_id = story_id` on the created chat.
- **D5.** `backend_v2/services/reference_cleanup.py` — when a Story is deleted, null `Chat.story_id`; when a Chat is deleted, null `Story.chat_id`. Follow the existing `scrub_entity_references` pattern.
- **D6.** `backend_v2/api/routes/world_vault/agents.py` — add `POST /agents/{id}/avatar` and `GET /agents/{id}/avatar`, mirroring `characters.py:548-568` (upload: `require_declared_size`, `read_upload_bounded`, `inspect_image`, write to `{settings.character_avatar_dir}/{agent_id}/avatar.png`) and `characters.py:659-663` (serve: `FileResponse` with the media type inferred from the extension).
- **D7.** `backend_v2/api/routes/world_vault/agents.py:40,54` — keep `avatar_path` on `AgentProfileCreate`/`AgentProfileUpdate` (now backed by a real column), and set `extra="forbid"` on both request models so a typo'd field is a 422 rather than a silent drop — matching the precedent documented at `backend_v2/api/routes/world_vault/characters.py:64-66`.

### Phase E — Worker layer

- **E1.** `backend_v2/services/load_balancer_factory.py:34-40` — give TTS its own runtime state: `state_id=3` with `get_runtime_state(3)`. The LLM path already uses `state_id=2`.
  *No migration needed*: `LoadBalancerState` rows are keyed by `id` and created on demand by `save_state_to_db` (`services/load_balancer.py:310-313`), and `load_state_from_db` runs per-instance with `self.state_id` (`services/load_balancer.py:388`).
- **E2.** `backend_v2/services/load_balancer.py:820-861` `get_stats` — the per-modality rollup now reads from genuinely separate state; verify the TTS row no longer reports image counters.
- **E3.** `backend_v2/services/job_processing.py` and `services/world_integration_service.py:240-250` — set `image_context` on the `scene_illustrate` image job so the resulting IMAGE message carries real content instead of the literal `"Generated Image:"` (`world_integration_service.py:997`). The agentic-tool path already sets it (`services/orchestrator_service.py:490-493`).
- **E4.** `backend_v2/services/world_integration_service.py:991-997` — fall back to the scene prompt when `image_context` is absent rather than emitting a bare `"Generated Image:"`.

### Phase F — Updater wiring

- **F1.** `backend_v2/services/updater_service.py:518-614` `enqueue_state_updater_if_needed` — resolve the `updater` agent with `resolve_agent(session, "updater", require_enabled=False)`; if found, render its variant's `system_prompt_template` via `render_agent_template` and use it as the Updater's system prompt, falling back to the current hardcoded `"You are a precise JSON-only roleplay state extractor..."` (`:581`). Mirror the continuation-agent pattern at `services/job_processing.py:1091-1111`.
- **F2.** Apply the resolved agent's `sampler_overrides()` **under** the explicit `samplers={"temperature": 0.2, "max_output_tokens": 600}` from A2, so the JSON-extraction temperature is not silently overridden by a variant's creative temperature. Document the precedence in a comment.
- **F3.** `backend_v2/services/decision_schema.py:134-159` `GATE_FIELD_MAP` — `scene_tension` and `pacing_directive` are written by the Updater (`services/updater_service.py:787-790`) but appear in **no** gate map, so the filter always drops them. Either add them to the map (with the gate that authorizes them) or remove them from the Updater's write loop. Recommend: **remove them from the write loop** — `record_director_decision` already owns `scene_tension` (`services/updater_service.py:360`) and `pacing_directive` is a Director output, not a Statekeeper delta.

### Phase G — Manifest drives execution

- **G1.** **New** `backend_v2/core/pipeline_limits.py` — a dependency-free leaf module (no imports, so `core/entities.py` can import it without a cycle) holding the single source of every pipeline number:
  ```python
  MAX_AUTONOMOUS_TURNS = 4
  MAX_CONTINUATIONS = 4
  MAX_AGENTIC_IMAGES = 2
  UPDATER_GATE_THRESHOLD = 0.55
  IMAGE_TRIGGER_THRESHOLD = 0.65
  AUTONOMY_CHAIN_THRESHOLDS = {"strict": 1.0, "balanced": 0.65, "cinematic": 0.50}
  DIRECTOR_TIMEOUT_SECONDS = 15.0
  ```
- **G2.** `backend_v2/core/entities.py:1409` — `Chat.max_autonomous_turns` default becomes `MAX_AUTONOMOUS_TURNS`; same for `Story.max_autonomous_turns`.
- **G3.** `backend_v2/services/decision_schema.py:14,19` — `UPDATER_GATE_THRESHOLD` and `IMAGE_TRIGGER_THRESHOLD` become imports from `core.pipeline_limits` (re-exported so existing importers keep working).
- **G4.** `backend_v2/services/job_processing.py:1081` (`continuation_count < 4`) and `:490-491` (`threshold_by_level`) — import from `core.pipeline_limits` instead of hardcoding.
- **G5.** `backend_v2/services/chat_pipeline.py` — `PipelineStage` gains `executor: str` (dotted path) and `next_stages` becomes an ordered tuple. `PIPELINE_STAGES` gets the executor for each stage. `get_pipeline_manifest()` reads its `limits` block from `core.pipeline_limits` so the served manifest can never quote a number the code does not use.
- **G6.** **New** `backend_v2/services/pipeline_runner.py`:
  - `stage(key) -> PipelineStage`
  - `limit(key, name, default=None)` — resolves from the stage's `limits`, falling back to the global limits
  - `run_stage(key, ctx)` — resolves the `executor` dotted path lazily (`importlib`) and calls it
  - `run_from(key, ctx)` — walks `next_stages` in declared order, skipping a stage whose gate is not met and stopping at `"user"`
  - Executor paths are strings resolved at call time → no import cycle with `core/entities.py`.
- **G7.** `backend_v2/services/job_processing.py` — extract the post-turn block (lines ~1025-1231) into per-stage executor functions (`_stage_audit`, `_stage_illustrate`, `_stage_update`, `_stage_chain`) and drive them from `pipeline_runner.run_from("audit", ctx)`. **Move the existing code without changing its behaviour** — the Update→Chain handoff via `pending_chain` (`:1184-1192`, `:823`) and the continuation early-return (`:1081-1140`) must be preserved exactly.
- **G8.** `backend_v2/api/routes/world_vault/chats.py:1095-1160` — the pre-generation Triage block calls `pipeline_runner.run_stage("triage", ctx)` instead of invoking the decision service directly.
- **G9.** `backend_v2/services/chat_pipeline.py` — update the module docstring: the manifest is now authoritative, not a description. `GET /llm/pipeline` output is unchanged in shape, so the LLM Studio frontend needs no change.

### Phase H — Frontend cohesion

- **H1.** Fix the 3 dead internal links:
  - `frontend_v2/src/components/chat/ChatContextPanel.jsx:2148` — `/stories?storyId=` → `/story?storyId=` (route is `/story`, singular; `frontend_v2/src/App.jsx:117-121`).
  - `frontend_v2/src/pages/WorldArchitect.jsx:494` — `/chats?chatId=` → `/chat?chatId=`.
  - `frontend_v2/src/pages/WorldArchitect.jsx:457` — `/worlds/${world_id}` → `/worlds` (no `:worldId` route is registered at `App.jsx:146`).
- **H2.** **Character → its Chats.** Add a "Chats" list to the character modal / `frontend_v2/src/pages/Characters.jsx` using `GET /api/v2/chats?character_id=…` (verify the backend filter exists; if not, add it to `backend_v2/api/routes/world_vault/chats.py`'s list route). Also add an "Open character page" escape from `frontend_v2/src/components/chat/CharacterDetailsModal.jsx`.
- **H3.** **Worker health in the roleplay UI.** Consume `GET /api/v2/llm/providers/health` in the chat surface — a banner in `frontend_v2/src/pages/ChatWorkspace.jsx` when `healthy_count === 0` or `total_count === 0`, plus a "Model" tab entry in `frontend_v2/src/components/chat/ChatContextPanel.jsx`. The endpoint already exists (`backend_v2/api/routes/world_vault/llm_config.py:629-648`); only the frontend consumer is missing.
- **H4.** **Show which agent Laya routed to.** `context_trace["selected_agent"]` is written at `backend_v2/api/routes/world_vault/chats.py:1168` and read by nobody in the chat UI. Surface it in `frontend_v2/src/components/chat/DirectorReasoningHUD.jsx` alongside the existing speaker/agent fields.
- **H5.** **Use the canonical gate registry.** `frontend_v2/src/components/chat/DirectorReasoningHUD.jsx:24-41` hard-codes `SIXTEEN_GATES`. Replace with the registry from `GET /api/v2/llm/director/gates` (already fetched by `frontend_v2/src/hooks/useLLMProviderStatus.js:217-224`), keeping the hardcoded list only as the offline fallback the file already documents.
- **H6.** **Consume `GET /llm/agents/with-variants`** in the LLM Studio Agent tab (`frontend_v2/src/pages/LLMStudio.jsx:429` + `:2579`) to replace the current N+1 (list, then variants per agent) with one round trip.
- **H7.** **Link to LLM Studio from the roleplay entry point.** `frontend_v2/src/pages/RoleplayWorkspace.jsx` — add LLM Studio to the "Expert tools" grid (`frontend_v2/src/constants/navigation.js:21-32`, which the sidebar also renders at `Layout.jsx:495-497`, so both surfaces stay in sync) and a provider-health card in the "Your world" section.
- **H8.** **Deduplicate the chat list cache.** `GET /api/v2/chats` is cached under 3 different query keys (`frontend_v2/src/hooks/useChatWorkspaceData.js:48`, `frontend_v2/src/pages/RoleplayWorkspace.jsx:48`, `frontend_v2/src/hooks/useChats.js:317`). Consolidate onto one key factory. Also resolve the `GET /characters` double-fetch: `frontend_v2/src/hooks/useExpressions.js:8` re-fetches data already in the `useCharacters()` list payload.
- **H9.** **Agent avatars.** Add an avatar upload + display to the Agent Studio modal (`frontend_v2/src/pages/LLMStudio.jsx` `AgentModal`) using the new `POST /agents/{id}/avatar` + `GET /agents/{id}/avatar` endpoints.
- **H10.** **Chat↔Story links.** With D1's provenance FKs, surface "started from this story" on the chat and "exported from this chat" on the story.

### Phase I — Gallery code out of the `world_vault` namespace

- **I1.** Create `backend_v2/api/routes/gallery/` and move `backend_v2/api/routes/world_vault/tags.py` and `backend_v2/api/routes/world_vault/sessions.py` into it.
- **I2.** Mount them from the gallery package with the **same URL prefixes** (`/api/v2/sessions`, `/api/v2/asset/{id}/tags`, `/api/v2/tags`, `/api/v2/assets/auto-tag`, `/api/v2/assets/facet`) so the frontend needs **zero** change and the OpenAPI surface is unchanged.
- **I3.** Fix any import-path references (`backend_v2/tests/`, `backend_v2/api/routes/__init__.py`, and any `from api.routes.world_vault import tags` style imports).

### Phase J — Pre-existing failures (all 12)

- **J1.** `KeyError: 'agentic'` in the scene/swipe routes. The Laya refactor removed tool attachment from the chat send path (`backend_v2/api/routes/world_vault/chats.py:1258-1261`) but the swipe and scene routes lost their agentic stamping with it, so `job.metadata_["agentic"]` is absent.
  - **Swipe** (`chats.py:1597-1608`): if the target message had `tool_calls` (or `message_metadata["agentic"]`), attach the agentic tools and stamp the metadata — mirroring `stories.py:1258-1287`:
    ```python
    if prev_agentic:
        workflow["tools"] = filter_agentic_tools(AGENTIC_TOOLS, allow_image=True)
        metadata.update({
            "agentic": True,
            "orchestrator_depth": 0,
            "max_agentic_depth": chat.max_agentic_depth or 3,
            **budget_metadata_for(chat),
        })
    ```
    `prev_agentic` is already computed at `chats.py:1684`.
  - **Scene** (`chats.py:2436-2455`): always stamp `"agentic": True` and attach the tools, per `tests/test_chat_routes_extended.py:301`.
  - `filter_agentic_tools` and `budget_metadata_for` are in `backend_v2/services/orchestrator_service.py` (`:117` and `:171`).
- **J2.** Route-count assertions: `backend_v2/tests/test_app_boot_smoke.py:478` (`len(spec["paths"]) == 278`) and `:481` (operations == 361). **Recompute these LAST**, after every route change in Phases C, D and I has landed, and update the comment block above them (`:465-477`) the way the file already documents each bump. Also update `docs/STATUS.md:202` (currently quotes "247 of 249 live paths … 329-operation") so `tests/test_api_docs_contract.py:173` passes.
- **J3.** `docs/api.md` — the duplicate `/world-vault/llm/*` and `/world-vault/agents/*` paths were never documented, so removing them *raises* coverage. Add the `/api/v2/llm/*` and `/api/v2/agents/*` paths that **are** live but undocumented, to lift coverage above the 65% floor in `tests/test_api_docs_contract.py:147`.
- **J4.** `tests/test_event_loop_invariant.py` — 11 violations, all in `backend_v2/api/routes/world_vault/onboarding.py` (lines 202, 243, 256, 274, 291, 311, 329, 345, 490, 505, 521). Move the blocking work off the event loop with `asyncio.to_thread`, matching the pattern already used in `chats.py:552,566`.
- **J5.** `tests/test_env_contracts.py::TestDirectionA` — 21 undocumented env vars, mostly in `remote_agent/`. Document them in the env-var contract file the test scans.
- **J6.** `tests/test_http_client.py` — 3 failures that pass in isolation (test-ordering pollution). Isolate the shared state between tests.

### Phase K — Docs

- **K1.** `docs/STATUS.md` — record: the four repaired pipeline stages; the removed duplicate mounts (a **breaking API change** for any consumer of `/api/v2/world-vault/llm/*` and `/api/v2/world-vault/agents/*`); the new `Chat.story_id` / `Story.chat_id` provenance; the agent-avatar feature; the TTS/Image LoadBalancer split; the vestigial `max_agentic_narrations` columns; the remaining known-failing tests (if any survive J).
- **K2.** `docs/api.md` — see J3.
- **K3.** `docs/provider-architecture.md` — record the Director's out-of-band status (deliberate) and the Tier 3 health-aware selection.

---

## 4. Risks

| Risk | Mitigation |
|---|---|
| **Phase G touches the highest-risk file** (`services/job_processing.py`, 1679 lines) while the pipeline is being repaired | G runs *after* A and B. The Phase B integration test (B6) is the safety net. G7 must be a pure code-move; any behavioural difference is a bug. |
| **Deleting the duplicate mounts is a breaking API change** | No product consumer exists (only `tests/test_model_catalog.py`). Recorded in `docs/STATUS.md` (K1). The OpenAPI spec is not published outside the app — there is no `openapi.json` in the repo. |
| **The TTS LoadBalancer split changes provider selection behaviour** | TTS is a low-volume path with few providers. `state_id=3` needs no migration (row created on demand). E2 verifies the stats rollup. |
| **Wiring the Updater to its AgentProfile could change extraction output** | F2 keeps the explicit `temperature=0.2` / `max_output_tokens=600` precedence. B2 asserts the gated schema. Roll out behind the existing `enabled` flag on the agent row. |
| **The 16-gate hardcoded list in the frontend has `fallbackKey` aliases for drifted key names** | H5 keeps the hardcoded list as the offline fallback; the live registry is preferred. Do not delete the constant in the same change. |
| **Phase I file moves can break imports** | `git mv` preserves history; grep for every import of the two modules before and after. URLs are unchanged, so the frontend is unaffected. |
| **Route-count assertions break mid-plan** | J2 is explicitly last. Do not touch `test_app_boot_smoke.py:478-481` until Phases C, D and I are done. |

---

## 5. Validation

Run from `backend_v2/` (venv at `.venv/bin/python`):

```bash
# Per-phase gate
.venv/bin/python -m pytest tests/test_chat_pipeline_execution.py -q
.venv/bin/python -m pytest tests/test_multi_agent_workflow.py tests/test_director_and_updater.py \
  tests/test_agent_profiles.py tests/test_agent_variants.py tests/test_llm_workflow.py \
  tests/test_orchestrator_service.py tests/test_load_balancer.py -q

# Full suite — must end at 0 failed
.venv/bin/python -m pytest -q

# Lint (ruff selects F only)
.venv/bin/ruff check .
```

Frontend (`frontend_v2/`):

```bash
npm test
npm run lint
npm run build
```

Manual acceptance checks:

1. `GET /api/v2/llm/agents/with-variants` returns **200** with a seeded agent table (regression for the live 500).
2. `PUT /api/v2/agents/{id}` with `avatar_path` in the body returns 200 and persists the value.
3. A chat turn that fires a gate produces a `state_updater` job, and the `state_snapshot` on the chat reflects the applied deltas.
4. A chat turn where the Director says "continue" produces a second turn in the same interaction (Stage 6 live).
5. A truncated generation produces a continuation job (continuation live).
6. `GET /api/v2/llm/pipeline` and the numbers the code actually uses agree.
7. TTS and Image report separate provider counters in `GET /api/v2/providers/load-balancer/stats`.
8. The three previously-dead frontend links navigate to a real page.
9. A chat exported to a story and a story started as a chat each show the provenance link in both directions.

---

## 6. Out of scope

- Rewriting the Director's decision schema, the 18 gate keys, or `GATE_FIELD_MAP`'s coverage (beyond F3).
- Implementing the `narrate_scene` / `update_world_state` agentic tools (A8/A9 remove the dead references; the tools themselves are not being built).
- Any change to the story sandbox's editing model, the World Architect's LLM analysis prompts, or the onboarding 20-endpoint surface.
- Building a Memories page (Phase C5 keeps `GET /memories`; a dedicated surface is separate work).
- Dropping the `Chat.max_agentic_narrations` / `Story.max_agentic_narrations` columns (recorded as vestigial instead).
- Provider-side changes to `remote_agent/` beyond the env-var documentation in J5.
