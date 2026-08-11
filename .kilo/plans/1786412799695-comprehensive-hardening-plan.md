# TNHComfy — Comprehensive Hardening & Vision Alignment Plan

## Current State Summary

TNHComfy is a mature, multi-modal AI Fantasy Engine with three working pillars (Image Gen, Roleplay, Story Sandbox) backed by PostgreSQL + pgvector, a unified TaskEvent provider protocol, and a DB-backed asset indexer. The Universal Adapter Pattern is implemented. The codebase is functional but carries accumulated tech debt: race conditions, deprecated APIs, code duplication, large frontend monoliths, and performance hot paths that will degrade as the user base and content grow.

## Goals

1. Eliminate backend stability bugs and race conditions.
2. Remove duplicated code and consolidate shared logic.
3. Complete missing integrations and unify cross-component state flow.
4. Improve startup latency, streaming responsiveness, and DB write efficiency.
5. Refactor frontend monoliths into reusable, virtualized components.
6. Polish UX to match the "Fantasy Hub" vision.
7. Keep the site accessible after every change; defer Audio/TTS/Multi-tenancy.

## Workstreams

### W1 — Backend Stability Fixes (low blast radius, do first)

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 1 | `asyncio.get_event_loop().time()` anti-pattern in `core/events.py` (deprecated 3.12, removed 3.14) | Replace with `time.monotonic()` | `backend_v2/core/events.py:447-449` |
| 2 | `image_worker/worker.py` references `client` in `lifespan` finally block before `client` is defined (fragile if ENGINE is unknown) | Move `client = None` above `lifespan`, guard `await client.close()` with `isinstance(client, ...)` or `hasattr` | `provider_containers/image_worker/worker.py:44-92` |
| 3 | `connected_workers` dict mutated from multiple async handlers without locks (heartbeat, message loop, disconnect, `_get_live_worker`) | Wrap all mutations in an `asyncio.Lock`; make `_get_live_worker` return a copy or hold the lock during iteration | `backend_v2/api/routes/worker_ws.py:63-94, 206, 239, 354-371` |
| 4 | `job_queue.recover_pending_jobs` uses a session from `job_service` in Postgres mode but never closes it after the early-return path | Explicitly close the session after the DB reset path, or refactor to use `get_session_context()` | `backend_v2/services/job_queue.py:522-577` |
| 5 | `JobStatus` FSM allows `PENDING -> FAILED` and `SENT_TO_PROVIDER -> PENDING` transitions, which can cause recovery loops when combined with `recover_pending_jobs` | Restrict FSM so only `FAILED -> PENDING` is allowed for retry; remove `PENDING -> FAILED` and `SENT_TO_PROVIDER -> PENDING` | `backend_v2/services/job_service.py:123-144` |
| 6 | `world_integration_service.py` handlers open raw `Session(engine)` and never close on success paths | Use `get_session_context()` or ensure `finally: session.close()` in every handler | `backend_v2/services/world_integration_service.py:45-420` |

### W2 — Duplication & Shared Logic Cleanup

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 7 | Tavern-var substitution duplicated: `chats.py` imports inline at line 105, `context_builder.py` calls it, `chat_utils.py` defines it. Also `chats.py` has `_substitute_tavern_vars` local alias | Remove inline import from `chats.py:105`; keep `chat_utils.substitute_tavern_vars` as canonical single import | `backend_v2/api/routes/world_vault/chats.py:86-90, 105` |
| 8 | Context token resolution duplicated between `chats.py` and `world_integration_service.py` | Keep `chat_utils.resolve_context_tokens` canonical; remove local imports | `backend_v2/api/routes/world_vault/chats.py`, `backend_v2/services/world_integration_service.py:27` |
| 9 | LLM workflow + metadata assembly duplicated in `chats.py` (impersonate, suggest, narrate, regenerate) | Extract `build_llm_reply_workflow(chat, character, system_prompt, context, model)` helper in `services/llm_workflow.py` and call from all 4 routes | `backend_v2/api/routes/world_vault/chats.py`, `backend_v2/services/llm_workflow.py` |
| 10 | Image workflow + metadata assembly duplicated across `chats.py`, `stories.py`, `orchestrator_service.py`, `world_integration_service.py` | Extract `build_image_job_workflow(prompt, checkpoint, negative_prompt, metadata, workspace, character_id, story_id)` in `services/job_submission_service.py` or `core/workflow_builder.py` | `backend_v2/core/workflow_builder.py`, `backend_v2/services/job_submission_service.py` |
| 11 | `job_processing.py` has 4 near-identical `is_*` boolean blocks (impersonation, illustrate, narrator, chat_reply) to determine event type | Replace with a single `_classify_llm_job_type(job, final_result)` returning an enum/dict | `backend_v2/services/job_processing.py:426-548` |
| 12 | `build_job_outputs` and `normalize_persisted_output` are image-only but live in generic `job_processing.py` | Move to `services/image_processing.py` or keep in `job_processing.py` but gate clearly with `if task_type == "image"` | `backend_v2/services/job_processing.py:63-216` |

### W3 — Missing / Incomplete Integrations

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 13 | No unified "Fantasy Hub" landing page. Dashboard is stats-only; users must know URLs to reach Roleplay/Story/Image workspaces | Build a minimal landing `/` with three large cards (Image Gen, Roleplay, Story Sandbox) linking to the three workspaces; move Dashboard to `/statistics` | `frontend_v2/src/App.jsx`, `frontend_v2/src/pages/Dashboard.jsx` |
| 14 | Cross-workspace asset migration is backend-only (no UI). Users cannot move images between Roleplay/Story/Main galleries | Add a "Move to..." action in `SceneGallery` dropdown that calls `POST /api/v2/assets/{id}/move` with target workspace/character/story | `frontend_v2/src/components/SceneGallery.jsx`, `backend_v2/api/routes/collections.py` (new endpoint) |
| 15 | Beam provider compose block is commented out, env template is empty, and there is no active Beam runtime test | Either uncomment + wire a Beam smoke test, or remove dead compose block + `.env.beam` to reduce noise | `docker-compose.yml:212-245`, `.env.beam` |
| 16 | `provider_containers/venv` is committed (large binary) | Remove from git history and add to `.gitignore` | `.gitignore`, `provider_containers/venv/` |
| 17 | `.env.example.*` templates are sparse and missing keys used in compose | Expand `.env.example.backend` and `.env.example.provider` with all documented env vars | `.env.example.backend`, `.env.example.provider` |
| 18 | `non_AGENTS.md` and `README.md` don't document the exact rebuild command or provider profile usage | Add the `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d` command and profile explanation | `README.md`, `non_AGENTS.md` |

### W4 — Performance & Reliability

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 19 | Asset migration `move_existing_assets` does `os.walk` on every backend startup, even when no legacy files exist | Add a fast-path guard: if `output_dir/{user_id}/` already exists and contains >0 PNGs, skip the walk unless `COMFY_ASSET_MIGRATION_FORCE=1` | `backend_v2/services/asset_reconciler.py:358-476` |
| 20 | Load balancer writes to DB on every `release_job`, `report_failure`, and every 5th `_track_job` | Batch persistence: debounce `save_state_to_db` with a 5s in-memory timer; flush on shutdown | `backend_v2/services/load_balancer.py:555-718` |
| 21 | Provider health-check TTL is 5s (`_provider_health_cache`); for stable serverless providers this is wasteful | Increase TTL to 15s for image workers and 30s for LLM workers (they are always-on endpoints); add circuit-breaker after 3 consecutive failures | `backend_v2/services/load_balancer.py:39-56, 284-345` |
| 22 | `context_builder.py` loads ALL chat messages into memory just to slice the last 20 for the lorebook query | Use keyset pagination: query only the last 50 messages for embedding context | `backend_v2/services/context_builder.py` |
| 23 | `ChatWorkspace` message list is not virtualized (only `SceneGallery` is). Long chats cause frame drops | Wire `@tanstack/react-virtual` (row-based) to the message list in `ChatWorkspace`; reuse the `useVirtualizer` pattern already imported | `frontend_v2/src/pages/ChatWorkspace.jsx` |
| 24 | `useLLMJobResult` still polls `/api/jobs/{id}` even when WS is connected (5s blind spot before first poll checks cache) | On WS connect, subscribe to `job.{jobId}` topic immediately; skip the initial 5s delay entirely when `getConnectionStatus() === 'connected'` | `frontend_v2/src/hooks/useLLMJobResult.js:86-114` |
| 25 | `job_runner.py` re-fetches job status via `job_service.get_job()` inside the retry loop, adding DB round-trips on every provider switch | Cache the job object locally within `execute_job` and only re-fetch on `JobCancelledError`/terminal events | `backend_v2/services/job_runner.py:276-286` |

### W5 — Frontend UX / QoL Improvements

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 26 | `ChatWorkspace.jsx` and `StorySandbox.jsx` are 2000+ line monoliths with duplicated command palette, context panel, and streaming logic | Extract shared components: `ChatCommandPalette`, `StreamingInput`, `ContextPanel`, `BeatPanel` into `frontend_v2/src/components/chat/` and `frontend_v2/src/components/story/` | `frontend_v2/src/pages/ChatWorkspace.jsx`, `frontend_v2/src/pages/StorySandbox.jsx` |
| 27 | No global search across Characters, Chats, Stories, and Images | Add a top-bar search input that opens a unified results modal, querying `/api/v2/search?q=...` (new backend endpoint) | `frontend_v2/src/App.jsx`, `backend_v2/api/routes/world_vault/` (new search route) |
| 28 | Mobile bottom tab bar exists but some workspace pages don't hide the browser chrome / don't handle safe-area-inset | Audit all pages for `env(safe-area-inset-bottom)` and add `viewport-fit=cover` to `index.html` | `frontend_v2/index.html`, `frontend_v2/src/components/BottomTabBar.jsx` |
| 29 | ChatWorkspace slash commands (`/silent`, `/story`, `/puppet`, `/time`, `/location`, `/action`) are hardcoded but not discoverable | Add a `/?` command palette overlay triggered by `/` key, listing all commands with descriptions | `frontend_v2/src/pages/ChatWorkspace.jsx` |
| 30 | StorySandbox lacks a "Read Mode" (full-screen, distraction-free reading) | Add a toggle that hides sidebars and renders only the chapter text with large typography | `frontend_v2/src/pages/StorySandbox.jsx` |

### W6 — Architectural Improvements for the Vision

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 31 | No unified "workspace switcher" — users navigate via URL or sidebar; the connection between Image Gen, Roleplay, and Story is implicit | Add a top-level workspace switcher (tabs or dropdown) that persists the active workspace in `localStorage` and syncs with backend `?workspace=` param | `frontend_v2/src/App.jsx`, `frontend_v2/src/store/worldVaultStore.js` |
| 32 | `Job.metadata_` is a free-form JSON blob used for routing (`workspace`, `character_id`, `story_id`, `source`) | Add typed optional columns (`workspace`, `character_id`, `story_id`, `source`) to `Job` for SQL-level filtering and indexing; deprecate JSON blob usage gradually | `backend_v2/core/entities.py`, `backend_v2/infrastructure/migrations/steps.py` |
| 33 | Agentic orchestrator depth is not persisted per-message, making it impossible for the UI to show "step 3 of 5" in agentic chains | Add `agentic_depth` to `Message.message_metadata` when inserting tool-call transcripts; read it in the UI | `backend_v2/services/job_processing.py`, `backend_v2/services/world_integration_service.py`, `frontend_v2/src/pages/ChatWorkspace.jsx` |
| 34 | `build_image_workflow` in `core/workflow_builder.py` is a thin wrapper that doesn't support img2img/inpaint masks or ControlNet conditioning from chat/story context | Extend `build_image_workflow` to accept optional `init_image`, `mask`, `controlnets` params; expose via a new `POST /api/v2/workflows/image` schema | `backend_v2/core/workflow_builder.py`, `backend_v2/api/routes/generation.py` |
| 35 | LLM context window is global; per-chat/per-story overrides exist but the UI doesn't surface them clearly | Add a "Context Settings" panel in ChatWorkspace and StorySandbox that lets users set max tokens, temperature, and model per conversation | `frontend_v2/src/pages/ChatWorkspace.jsx`, `frontend_v2/src/pages/StorySandbox.jsx`, backend existing `PATCH /api/v2/chats/{id}` and `PATCH /api/v2/stories/{id}` |

## Migration / Rollout Plan

1. **Week 1 (W1 + W2):** Backend bug fixes and code consolidation. Run existing container stack; verify with `curl http://localhost:8002/api/health` + UI smoke tests after each batch.
2. **Week 2 (W3 + W4):** Frontend integration additions (Fantasy Hub, cross-workspace move, search), performance patches (asset migration guard, LB debounce, health TTL), and Docker hygiene (Beam removal, `.gitignore`, README updates).
3. **Week 3 (W5):** Frontend refactor — extract shared chat/story components, virtualize message lists, add command palette and read mode.
4. **Week 4 (W6):** Architectural improvements — workspace switcher, typed Job columns, agentic depth persistence, extended workflow builder, context settings UI.

## Validation

- Backend: `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d` succeeds; `curl http://localhost:8002/api/health` returns 200.
- Frontend: `http://localhost:5174` loads; React Query devtools show no stale cache errors.
- Workers: `tnhcomfy-modal-zetsuke` and `tnhcomfy-llm-local` health checks pass.
- E2E: Create chat → send message → trigger agentic image → verify image appears in chat + roleplay gallery.
- Story: Create story → continue → branch → illustrate → verify images appear in story gallery.
- Performance: Backend startup <15s; LB state writes <1 per minute under load; asset migration skips walk on warm starts.

## Open Decisions

1. **Beam provider**: Remove commented-out compose block and `.env.beam` now, or keep as placeholder?
2. **Job.metadata_ typed columns**: Add `workspace`, `character_id`, `story_id`, `source` as real columns now, or keep JSON-only until multi-tenancy?
3. **Frontend framework**: Stay on React JSX or migrate to TypeScript? TS catches more bugs but adds build complexity for a single-user project.
4. **Max agentic depth**: Increase for Story Sandbox (where longer chains make sense), or keep uniform at 5?
