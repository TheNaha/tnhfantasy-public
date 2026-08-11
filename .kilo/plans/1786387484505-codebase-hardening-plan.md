# TNHComfy — Codebase Hardening & Vision Alignment Plan

## Current State Summary

The project has evolved from a ComfyUI wrapper into a multi-modal AI Fantasy Engine with three working pillars (Image Gen, Roleplay, Story Sandbox) backed by PostgreSQL + pgvector. The Universal Adapter Pattern is implemented, the unified TaskEvent protocol is in place, and the DB-backed asset indexer is operational. The single untracked file is `backend_v2/tests/test_context_builder.py`.

## Goals

1. Fix critical bugs and race conditions that can crash or hang the backend/frontend.
2. Remove duplicated code and consolidate shared logic.
3. Complete missing integrations between components (frontend ↔ backend ↔ workers).
4. Improve performance (startup time, streaming, memory usage).
5. Strengthen state-flow correctness (sessions, transactions, event bus, WebSocket).
6. Keep the site accessible after every change; defer Audio/TTS/Multi-tenancy.

## Workstreams (ordered by risk/impact)

### W1 — Backend stability fixes (do first, low blast radius)

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 1 | `asyncio.get_event_loop().time()` anti-pattern in `core/events.py` (deprecated in 3.12, removed later) | Replace with `asyncio.get_running_loop().time()` or `time.monotonic()` | `backend_v2/core/events.py:447-449` |
| 2 | `image_worker/worker.py` references `client` in `lifespan` finally block before `client` is defined (Python resolves at call time, but fragile) | Move `client` initialization above `lifespan` or guard with `try/except NameError` | `provider_containers/image_worker/worker.py:86-91` |
| 3 | `connected_workers` dict mutated from multiple async handlers without locks | Add `asyncio.Lock` around mutations in `worker_ws.py` | `backend_v2/api/routes/worker_ws.py` |
| 4 | Session leak: `job_queue.py` creates `Session(engine)` in `recover_pending_jobs` but only closes in success path | Ensure `finally: session.close()` or use context manager | `backend_v2/services/job_queue.py:522-592` |
| 5 | `ChatWorkspace` + `StorySandbox` are 2000+ line monoliths | Extract `MessageItem`, `ContextPanel`, `BeatPanel` into shared components | `frontend_v2/src/pages/ChatWorkspace.jsx`, `StorySandbox.jsx` |

### W2 — Duplication & shared logic cleanup

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 6 | Tavern-var substitution duplicated across 3 places (chats.py, context_builder.py, chat_utils.py) | Keep `chat_utils.substitute_tavern_vars` as canonical; remove inline copies | `backend_v2/api/routes/world_vault/chats.py`, `backend_v2/services/context_builder.py` |
| 7 | Context token resolution duplicated | Keep `chat_utils.resolve_context_tokens` as canonical; remove duplicates | `backend_v2/api/routes/world_vault/chats.py`, `backend_v2/services/world_integration_service.py` |
| 8 | LLM workflow + metadata assembly duplicated in `chats.py` (impersonate, suggest, narrate, regenerate) | Extract `build_chat_reply_workflow()` helper | `backend_v2/api/routes/world_vault/chats.py` |
| 9 | Image workflow + metadata assembly duplicated across `chats.py`, `stories.py`, `orchestrator_service.py`, `world_integration_service.py` | Extract `build_image_job_workflow()` helper with workspace/character/story scoping | Multiple backend files |
| 10 | Frontend `api.get` query param serialization was broken (fixed in recent commit) — verify no regressions in other routes | Audit all `api.get` calls for `params` usage | `frontend_v2/src/api/*.js` |

### W3 — Missing / incomplete integrations

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 11 | In-chat "Illustrate" UI button is wired backend-side (`POST /{chat_id}/illustrate`) but missing from `ChatWorkspace` toolbar | Add button to message input toolbar; wire to `useIllustrateChat` | `frontend_v2/src/pages/ChatWorkspace.jsx` |
| 12 | `SceneGallery` exists but is not rendered in `ChatWorkspace` (only in StorySandbox) | Add `SceneGallery` tab/panel to ChatWorkspace when chat has images | `frontend_v2/src/pages/ChatWorkspace.jsx` |
| 13 | Agentic tool-call transcript chips exist in backend (`Message.kind=TOOL`) but frontend doesn't render `kind=TOOL` messages in chat | Add tool-call chip rendering in `MessageItem` | `frontend_v2/src/pages/ChatWorkspace.jsx` |
| 14 | Story branching UI exists but `ChatWorkspace` lacks rollback/regenerate consistency for agentic depth | Ensure `orchestrator_depth` is persisted on `Message` so UI can show step count | `backend_v2/services/job_processing.py`, `frontend_v2/src/pages/ChatWorkspace.jsx` |
| 15 | `useLLMJobResult` polls `/api/jobs/{id}` even when WebSocket is connected (5s blind spot) | On WS connect, subscribe to job-specific events first; skip initial poll delay | `frontend_v2/src/hooks/useLLMJobResult.js` |

### W4 — Performance & reliability

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 16 | Asset migration scans entire `OUTPUT_DIR` on every startup | Make migration idempotent + skip if no legacy flat files detected; add `--force` flag via env | `backend_v2/services/asset_reconciler.py` |
| 17 | `load_balancer.py` does DB writes on every 5th job assignment (`save_state_to_db`) | Batch persistence (every 30s or 20 jobs) instead of per-5-jobs | `backend_v2/services/load_balancer.py` |
| 18 | `context_builder.py` builds lorebook query from recent messages by loading all messages into memory | Use keyset pagination + limit to last 20 messages for embedding query | `backend_v2/services/context_builder.py` |
| 19 | Frontend `useMessages` loads 100 messages by default with no virtualized list in ChatWorkspace | Wire `@tanstack/react-virtual` to message list (already imported, unused in ChatWorkspace) | `frontend_v2/src/pages/ChatWorkspace.jsx` |
| 20 | Provider health checks hit `/health` on every `get_next_provider` call with 5s TTL cache | Increase TTL to 15-30s; add circuit-breaker after N consecutive failures | `backend_v2/services/load_balancer.py` |

### W5 — Docker / deployment hygiene

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 21 | `.env` files are gitignored but `.env.example.*` templates are sparse | Expand `.env.example.backend` and `.env.example.provider` with all used vars | `.env.example.backend`, `.env.example.provider` |
| 22 | Beam provider is fully commented out in compose but env template `.env.beam` is empty | Either uncomment + test, or remove dead compose block to reduce confusion | `docker-compose.yml`, `.env.beam` |
| 23 | Backend rebuild requires manual `docker compose ... up --build -V -d` | Document exact rebuild command in `README.md` and `non_AGENTS.md` | `README.md` |
| 24 | `provider_containers/venv` is committed (huge) | Add to `.gitignore`; remove from repo | `.gitignore` |

### W6 — Frontend UX / QoL improvements (aligned with vision)

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| 25 | No in-chat quick-actions for narrator / impersonate / suggest | Add slash-command palette or quick-action buttons | `frontend_v2/src/pages/ChatWorkspace.jsx` |
| 26 | StorySandbox lacks character avatar/visual tags in context panel | Show active character cards + visual tags in story context sidebar | `frontend_v2/src/pages/StorySandbox.jsx` |
| 27 | No global "Fantasy Hub" landing page that explains the three pillars | Add a minimal landing `/` that routes to the three workspaces | `frontend_v2/src/App.jsx`, `frontend_v2/src/pages/Dashboard.jsx` |
| 28 | Mobile bottom tab bar exists but some pages don't respect it | Audit all workspace pages for mobile tab visibility | `frontend_v2/src/components/BottomTabBar.jsx` |

## Migration / rollout plan

1. **Week 1 (W1 + W2):** Backend bug fixes and code consolidation. Run existing container stack; verify with curl/UI smoke tests after each PR-sized batch.
2. **Week 2 (W3):** Frontend integration completions (Illustrate button, SceneGallery, tool chips). These are additive UI changes; no backend schema changes.
3. **Week 3 (W4 + W5):** Performance patches and Docker hygiene. Rebuild providers with `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d`.
4. **Week 4 (W6):** UX polish and vision-alignment features.

## Validation

- Backend: `docker compose ... up --build -V -d` succeeds; `curl http://localhost:8002/api/health` returns 200.
- Frontend: `http://localhost:5174` loads; React Query devtools show no stale cache errors.
- Workers: `provider-modal-zetsuke` and `provider-llm-local` health checks pass.
- E2E: Create chat → send message → trigger agentic image → verify image appears in chat + roleplay gallery.
- Story: Create story → continue → branch → illustrate → verify images appear in story gallery.

## Open decisions (need your call)

1. **Beam provider**: Keep commented-out compose block for future, or remove it to reduce noise?
2. **Asset migration strategy**: Auto-migrate on startup (current) vs. manual `POST /admin/migrate-assets` endpoint?
3. **Frontend framework**: Stay on plain React (JSX) or migrate to TypeScript? TS would catch more bugs but adds build complexity.
4. **Max agentic depth**: Currently 5. Increase for story sandbox (where longer chains make sense), or keep uniform?
