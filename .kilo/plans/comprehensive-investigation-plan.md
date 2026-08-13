# TNHComfy — Comprehensive Investigation & Hardening Plan

## Executive Summary

TNHComfy is a mature, multi-modal AI Fantasy Engine with three working pillars (Image Gen, Roleplay, Story Sandbox) backed by PostgreSQL + pgvector, a unified TaskEvent provider protocol, and a DB-backed asset indexer. The Universal Adapter Pattern is implemented. The codebase is functional but carries accumulated tech debt that will degrade the experience as content grows and the vision expands.

This plan focuses on:
1. **Eliminating remaining backend stability bugs and race conditions**
2. **Removing duplicated code and consolidating shared logic**
3. **Completing missing integrations and unifying cross-component state flow**
4. **Improving startup latency, streaming responsiveness, and DB write efficiency**
5. **Refactoring frontend monoliths into reusable, virtualized components**
6. **Polishing UX to match the "Fantasy Hub" vision**
7. **Keeping the site accessible after every change; deferring Audio/TTS/Multi-tenancy**

---

## Current State: Already Fixed (Previous Hardening Passes)

| Area | Status | Evidence |
|------|--------|----------|
| Deprecated `asyncio.get_event_loop().time()` | ✅ Fixed | `backend_v2/core/events.py:448` uses `time.monotonic()` |
| `image_worker/worker.py` client reference before definition | ✅ Fixed | `client = None` declared at line 45, before `lifespan` |
| Tavern-var substitution duplication | ✅ Consolidated | `services/chat_utils.py` is the single canonical source |
| Context token resolution duplication | ✅ Consolidated | `services/chat_utils.py` defines `resolve_context_tokens` |
| `_provider_health_cache` TTL too aggressive | ✅ Fixed | TTL is 15s (not 5s) in `services/load_balancer.py:55` |
| ChatWorkspace message list virtualization | ✅ Fixed | Uses `@tanstack/react-virtual` `useVirtualizer` at line 199 |
| `_classify_llm_job_type` extraction | ✅ Fixed | Single function replaces 4 near-identical blocks in `job_processing.py:420` |
| Asset migration fast-path guard | ✅ Fixed | `asset_reconciler.py:377-387` skips walk when partition exists |
| `worker_ws.py` `_workers_lock` | ✅ Fixed | Lock exists at line 66, used in connect/dispatch/disconnect |
| Load balancer DB write frequency | ✅ Fixed | Persists every 20 jobs, not on every release/failure |

---

## Workstreams

### W1 — Backend Stability Fixes (low blast radius, do first)

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 1 | `JobStatus` FSM allows `PENDING -> FAILED` and `SENT_TO_PROVIDER -> PENDING`, causing recovery loops when combined with `recover_pending_jobs` | Restrict FSM: remove `PENDING -> FAILED` and `SENT_TO_PROVIDER -> PENDING`; only `FAILED -> PENDING` allowed for retry | `backend_v2/services/job_service.py:16-26` |
| 2 | `worker_ws.py` `_get_live_worker_unlocked` mutates `connected_workers` without a lock when called from `get_connected_workers()` and `is_worker_connected()` | Wrap mutations in `async with _workers_lock` inside `_get_live_worker_unlocked`, or make callers hold the lock | `backend_v2/api/routes/worker_ws.py:82-108, 111-123` |
| 3 | `job_queue.recover_pending_jobs` uses a session from `job_service` in Postgres mode but never closes it after the early-return path | Explicitly close the session after the DB reset path, or refactor to use `get_session_context()` | `backend_v2/services/job_queue.py:522-577` |
| 4 | `world_integration_service.py` handlers use `with Session(engine)` in async functions — synchronous sessions in async code | Replace with `get_session_context()` or ensure `finally: session.close()` in every handler with async-safe pattern | `backend_v2/services/world_integration_service.py:45-420` |
| 5 | `orchestrator_service.py` `_tool_narrate_scene` opens 3 separate `get_session_sync()` sessions in a single tool call | Consolidate to one session with explicit `try/finally: session.close()` | `backend_v2/services/orchestrator_service.py:289-381, 401-443` |

### W2 — Duplication & Shared Logic Cleanup

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 6 | LLM workflow + metadata assembly duplicated in `chats.py` (impersonate, suggest, generate_scene, illustrate) | Extract `build_llm_reply_workflow(chat, character, system_prompt, context, model, type_, extra_metadata)` helper in `services/llm_workflow.py` and call from all routes | `backend_v2/api/routes/world_vault/chats.py`, `backend_v2/services/llm_workflow.py` |
| 7 | Image workflow + metadata assembly duplicated across `chats.py`, `stories.py`, `orchestrator_service.py`, `world_integration_service.py` | Extract `build_image_job_workflow(prompt, checkpoint, negative_prompt, metadata, workspace, character_id, story_id, filename_prefix)` in `services/job_submission_service.py` | `backend_v2/services/job_submission_service.py`, `core/workflow_builder.py` |
| 8 | `_chat_context_kwargs` local helper in `chats.py` duplicates logic from `context_builder.py` | Remove local helper; call `build_system_prompt_sections_async` / `build_chat_context_async` directly with explicit kwargs | `backend_v2/api/routes/world_vault/chats.py:112-128` |
| 9 | `build_job_outputs` and `normalize_persisted_output` are image-only but live in generic `job_processing.py` | Move to `services/image_processing.py` or keep in `job_processing.py` but gate clearly with `if task_type == "image"` | `backend_v2/services/job_processing.py:63-216` |
| 10 | `orchestrator_service.py` is 712 lines with mixed concerns (tool execution, LLM workflow building, inline narration) | Split into `orchestrator_service.py` (tool routing) + `narrator_service.py` (inline narration logic) + keep `execute_tool` thin | `backend_v2/services/orchestrator_service.py` |

### W3 — Missing / Incomplete Integrations

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 11 | No unified "Fantasy Hub" landing page. Dashboard is stats-only; users must know URLs to reach Roleplay/Story/Image workspaces | Build a minimal landing `/` with three large cards (Image Gen, Roleplay, Story Sandbox) linking to the three workspaces; move Dashboard to `/statistics` | `frontend_v2/src/App.jsx`, `frontend_v2/src/pages/Dashboard.jsx` |
| 12 | Cross-workspace asset migration is backend-only (no UI). Users cannot move images between Roleplay/Story/Main galleries | Add a "Move to..." action in `SceneGallery` dropdown that calls a new backend endpoint | `frontend_v2/src/components/SceneGallery.jsx`, `backend_v2/api/routes/assets.py` (new) |
| 13 | No global search across Characters, Chats, Stories, and Images | Add a top-bar search input that opens a unified results modal, querying a new backend search endpoint | `frontend_v2/src/App.jsx`, `backend_v2/api/routes/world_vault/search.py` (new) |
| 14 | Beam provider compose block is commented out, env template is empty, and there is no active Beam runtime test | Either uncomment + wire a Beam smoke test, or remove dead compose block + `.env.beam` to reduce noise | `docker-compose.yml`, `.env.beam` |
| 15 | `provider_containers/venv` is a committed binary directory | Remove from git history and add to `.gitignore` | `.gitignore`, `provider_containers/venv/` |
| 16 | `.env.example.*` templates are sparse and missing keys used in compose | Expand `.env.example.backend` and `.env.example.provider` with all documented env vars | `.env.example.backend`, `.env.example.provider` |
| 17 | `remote_comfy` provider has no volume mount in `docker-compose.yml` | Add `volumes: - ./data:/data` to match other providers | `docker-compose.yml:284-315` |

### W4 — Performance & Reliability

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 18 | `context_builder.py` loads ALL chat messages into memory just to slice the last 20 for lorebook query | Use keyset pagination: query only the last 50 messages for embedding context | `backend_v2/services/context_builder.py` |
| 19 | `job_runner.py` re-fetches job status via `job_service.get_job()` inside the retry loop, adding DB round-trips on every provider switch | Cache the job object locally within `execute_job` and only re-fetch on `JobCancelledError`/terminal events | `backend_v2/services/job_runner.py:276-286` |
| 20 | `useLLMJobResult` still polls `/api/jobs/{id}` even when WS is connected (5s blind spot before first poll checks cache) | On WS connect, subscribe to `job.{jobId}` topic immediately; skip the initial 5s delay when `getConnectionStatus() === 'connected'` | `frontend_v2/src/hooks/useLLMJobResult.js:86-114` |
| 21 | `ChatWorkspace.jsx` and `StorySandbox.jsx` are 1500+ line monoliths with duplicated command palette, context panel, and streaming logic | Extract shared components: `ChatCommandPalette`, `StreamingInput`, `ContextPanel` into `frontend_v2/src/components/chat/` and `frontend_v2/src/components/story/` | `frontend_v2/src/pages/ChatWorkspace.jsx`, `frontend_v2/src/pages/StorySandbox.jsx` |
| 22 | `useWorldVault.js` is 506 lines mixing ~15 query hooks and ~15 mutation hooks | Split into `useCharacters.js`, `useChats.js`, `useMessages.js`, `useStories.js`, `useLorebooks.js` | `frontend_v2/src/hooks/useWorldVault.js` |
| 23 | `worldVaultStore.js` is vestigial (9 lines, only tracks `activeChatId` which is URL-driven) | Remove store or expand its purpose (e.g., track active workspace, recently accessed entities) | `frontend_v2/src/store/worldVaultStore.js` |
| 24 | `collectionsApi.js` uses mixed named + default exports, inconsistent with other API modules | Standardize to named exports only | `frontend_v2/src/api/collectionsApi.js` |
| 25 | `models.js` is skeletal (only has `deleteV2`) | Expand to include `list`, `get`, `create` or document why direct API calls in components are intentional | `frontend_v2/src/api/models.js` |

### W5 — Architectural Improvements for the Vision

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 26 | No unified "workspace switcher" — users navigate via URL or sidebar; connection between Image Gen, Roleplay, and Story is implicit | Add a top-level workspace switcher (tabs or dropdown) that persists the active workspace in `localStorage` | `frontend_v2/src/App.jsx`, `frontend_v2/src/components/BottomTabBar.jsx` |
| 27 | `Job.metadata_` is a free-form JSON blob used for routing (`workspace`, `character_id`, `story_id`, `source`) | Add typed optional columns (`workspace`, `character_id`, `story_id`, `source`) to `Job` for SQL-level filtering and indexing | `backend_v2/core/entities.py`, `backend_v2/infrastructure/migrations/steps.py` |
| 28 | Agentic orchestrator depth is not persisted per-message, making it impossible for the UI to show "step 3 of 5" in agentic chains | Add `agentic_depth` to `Message.message_metadata` when inserting tool-call transcripts; read it in the UI | `backend_v2/services/job_processing.py`, `backend_v2/services/world_integration_service.py`, `frontend_v2/src/pages/ChatWorkspace.jsx` |
| 29 | `build_image_workflow` doesn't support img2img/inpaint masks or ControlNet conditioning from chat/story context | Extend `build_image_workflow` to accept optional `init_image`, `mask`, `controlnets` params | `backend_v2/core/workflow_builder.py` |
| 30 | LLM context window settings exist but UI doesn't surface per-chat/per-story overrides clearly | Add a "Context Settings" panel in ChatWorkspace and StorySandbox | `frontend_v2/src/pages/ChatWorkspace.jsx`, `frontend_v2/src/pages/StorySandbox.jsx` |

### W6 — Provider & Docker Hygiene

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 31 | `llm_worker/Dockerfile` lacks unprivileged user creation (runs as root outside compose) | Add `RUN groupadd -r worker && useradd -r -g worker worker` + `USER worker` | `provider_containers/llm_worker/Dockerfile` |
| 32 | Beam provider compose block is commented out with empty env template | Remove dead compose block + `.env.beam` to reduce noise, or uncomment and wire a Beam smoke test | `docker-compose.yml`, `.env.beam` |
| 33 | `provider_containers/venv` is a committed binary directory | Remove from git and add to `.gitignore` | `.gitignore` |
| 34 | No per-provider resource monitoring (CPU/memory/GPU usage not reported) | Add optional `/provider-stats` endpoint reporting container resource usage via Docker SDK | `provider_containers/provider_core/router.py` |
| 35 | `remote_comfy` provider has no volume mount in docker-compose.yml | Add `volumes: - ./data:/data` | `docker-compose.yml:284-315` |

---

## Rollout Plan

1. **Week 1 (W1 + W2):** Backend bug fixes and code consolidation. Run existing container stack; verify with `curl http://localhost:8002/api/health` + UI smoke tests after each batch.
2. **Week 2 (W3 + W4):** Frontend integration additions (Fantasy Hub, cross-workspace move, search), performance patches, and Docker hygiene.
3. **Week 3 (W5):** Frontend refactor — extract shared chat/story components, virtualize message lists, add command palette and read mode.
4. **Week 4 (W6):** Architectural improvements — workspace switcher, typed Job columns, agentic depth persistence, extended workflow builder, context settings UI, provider hygiene.

---

## Validation Criteria

- Backend: `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d` succeeds; `curl http://localhost:8002/api/health` returns 200.
- Frontend: `http://localhost:5174` loads; React Query devtools show no stale cache errors.
- Workers: `tnhcomfy-modal-zetsuke` and `tnhcomfy-llm-local` health checks pass.
- E2E: Create chat → send message → trigger agentic image → verify image appears in chat + roleplay gallery.
- Story: Create story → continue → branch → illustrate → verify images appear in story gallery.
- Performance: Backend startup <15s; LB state writes <1 per minute under load; asset migration skips walk on warm starts.

---

## Open Decisions

1. **Beam provider**: Remove commented-out compose block and `.env.beam` now, or keep as placeholder?
2. **Job.metadata_ typed columns**: Add `workspace`, `character_id`, `story_id`, `source` as real columns now, or keep JSON-only until multi-tenancy?
3. **Frontend framework**: Stay on React JSX or migrate to TypeScript? TS catches more bugs but adds build complexity for a single-user project.
4. **Max agentic depth**: Keep uniform at 5, or increase for Story Sandbox where longer chains make sense?
