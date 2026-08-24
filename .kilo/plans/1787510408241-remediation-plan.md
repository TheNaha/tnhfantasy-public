# TNHComfy Remediation Plan — Feature Completeness & Codebase Hardening

> **Status**: Ready for implementation
> **Scope**: Make the 3 pillars (Image Generation, Roleplay Chat, Story Sandbox) genuinely usable end-to-end; eliminate "demo feel"; unify architecture; fix all P0/P1 bugs.
> **Stack**: `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d`

---

## Executive Summary

TNHComfy is a **Comprehensive AI Fantasy Engine** — a ComfyUI wrapper with serverless providers (Modal, Beam), roleplay chatbots, and a story sandbox, all backed by PostgreSQL + pgvector. The current test count is healthy (backend 1523 pass, frontend 561 pass, lint 0 errors), but the working tree contains **56 modified + 5 untracked files** with several critical bugs, integration gaps, and architectural inconsistencies that prevent casual/power-user usability.

This plan prioritizes:
1. **P0 critical bugs** that crash at runtime
2. **P1 integration gaps** that make features feel "demo-like"
3. **P2 architectural unification** to reduce future friction
4. **P3 polish** for quality-of-life

---

## 0. Git Working Tree Review

### Current state
- **Branch**: `master` (up to date with `origin/master`)
- **Modified**: 56 files (980 insertions, 661 deletions)
- **Untracked**: 5 files (`.kilo/plans/`, `worker_registry.py`, `settingsApi.js`, `Lorebooks.jsx`, `Lorebooks.test.jsx`)
- **Stashed**: 0

### Issues in current changes
| # | Severity | File | Issue |
|---|----------|------|-------|
| 1 | **P0** | `chats.py:883` | `regenerate_reply` returns `len(trailing)` — `trailing` is never defined. Will crash at runtime. Should return `len(deleted)` from the SQL delete rowcount. |
| 2 | P1 | `frontend_v2/src/api/settingsApi.js` | New file is good — centralizes `/api/settings/*` calls. But `client.js` has no `API_V2_BASE` export used consistently. |
| 3 | P1 | `frontend_v2/src/api/providers.test.js` | CRLF→LF warning on save. Minor but should be consistent. |
| 4 | P2 | `frontend_v2/src/components/generator/VaeLoraSection.jsx` | Deleted. No remaining imports (verified). Safe to remove. |

### Recommended commit strategy
- Amend the previous AnimateDiff commits (`2ea8aba`, `b2107d8`) to include the P0 `regenerate_reply` fix so the feature ships correct.
- Commit remaining changes in logical chunks: API unification → frontend features → backend fixes.

---

## Phase 0 — Critical Bug Fixes (P0)

> Nothing ships until these are fixed. These block basic usability.

### 0.1 `regenerate_reply` undefined variable crash
**File**: `backend_v2/api/routes/world_vault/chats.py:883`

**Bug**: The function deletes trailing messages via SQL `delete()` but never captures the rowcount. It returns `len(trailing)` where `trailing` is never assigned.

**Fix**: Capture `result.rowcount` from the delete operation and return it.
```python
result = session.execute(
    delete(Message).where(
        Message.chat_id == chat_id,
        Message.created_at > anchor.created_at,
    )
)
deleted = result.rowcount
session.commit()
...
return {"job_id": job.id, "removed_messages": deleted}
```

### 0.2 `_handle_provider_failure` always returns `False`
**File**: `backend_v2/services/job_runner.py`

**Bug**: The function signals cancellation and reports failure but always returns `False`. The caller checks the return value to decide whether to stop, but it will never stop via this path.

**Fix**: Return `True` when cancellation succeeds, or let exceptions propagate instead.

### 0.3 Beam client test failure
**File**: `provider_containers/tests/test_beam_client.py::test_inference_streams_task_events`

**Bug**: Test expects `["node", "completed"]` but receives `["failed"]`. Likely a mock timing issue where the stream hits the error path before the success path.

**Fix**: Verify the mock setup; ensure the response stream yields `node` then `completed` events in sequence without hitting the `failed` fallback.

---

## Phase 1 — Infrastructure & Unification (P1/P2)

> Makes every pillar better and reduces future friction. Should land first.

### 1.1 API versioning unification
**Current state**: Frontend mixes `/api/` (jobs, generate, settings, prompts, files) and `/api/v2/` (world vault, models, providers, collections) with no single helper.

**Fix**:
- Create `frontend_v2/src/api/jobsApi.js`, `frontend_v2/src/api/generateApi.js`, `frontend_v2/src/api/promptsApi.js` (already partially done via `settingsApi.js`)
- Add `API_BASE` / `API_V2_BASE` constants in `client.js`
- Migrate all frontend API calls to use the new modules
- Document the canonical split: `/api/v2/` for World Vault + providers + collections + models; legacy `/api/generate`, `/api/files`, `/api/prompts` stay

**Files**: `client.js`, all `src/api/*.js` files, all hooks importing `api` directly

### 1.2 Dependency-injection violations
**Current state**: Services import from `api.routes` and `api.deps`:
- `services/provider_runtime.py` → `api.routes.worker_ws`
- `services/orchestrator_service.py` → `infrastructure.database` + `api.deps`
- `services/agent_simulation.py` → `api.deps` (fixed in uncommitted)
- `services/world_integration_service.py` → `infrastructure.database` (fixed in uncommitted)

**Fix**:
- Extract shared session helpers into `infrastructure/deps.py`
- Move `get_session_context` / `get_session_sync` there
- Have both `api.deps` and services depend on `infrastructure/deps.py`
- Move worker registry to `infrastructure/worker_registry.py` (already done in uncommitted)
- Eliminate all `services → api.routes` imports

**Files**: `infrastructure/deps.py`, `services/*.py`, `api/deps.py`

### 1.3 Repository pattern enforcement
**Current state**: `ChatRepository` is a stub (only `get()`). `characters.py` and `chats.py` bypass repositories for writes and complex reads.

**Fix**:
- Expand `ChatRepository` with methods used by routes: `list`, `create`, `update`, `delete`, `get_recent_messages`, `count`
- Add `MessageRepository` methods for branch queries, swipe queries
- Update routes to use repositories instead of inline `session.exec()`
- Export all repositories from `infrastructure/repositories/__init__.py`

**Files**: `infrastructure/repositories/chat_repo.py`, `infrastructure/repositories/message_repo.py`, `infrastructure/repositories/__init__.py`, `api/routes/world_vault/chats.py`

### 1.4 Session management chaos
**Current state**: Three session access patterns coexist:
- `get_session()` — generator for FastAPI `Depends()`
- `get_session_context()` — async context manager for internal async code
- `get_session_sync()` — synchronous session for sync code

**Fix**:
- Document the canonical use case for each
- Add a `SessionManager` class that wraps all three with clear method names
- Migrate services to use `SessionManager`

### 1.5 Global mutable state audit
**Current state**:
- `event_bus = EventBus()` — global singleton
- `queue_manager = QueueManager()` — global singleton
- `LoadBalancer._runtime_states` — class-level dict with threading.Lock
- `connected_workers` — module-level dict in `worker_registry.py`

**Fix**:
- Document each global with its justification
- For `LoadBalancer`, convert to instance-based with `asyncio.Lock` (already noted in ROADMAP)
- Add thread-safety tests for concurrent access patterns

---

## Phase 2 — Chat Workspace (Roleplay) Completeness

### 2.1 Idle simulation toggle wired to scheduler
**Current state**: `ChatContextPanel.jsx` writes `idle_sim_enabled`, but scheduler only registers the tick when `COMFY_IDLE_SIM_ENABLED` env var is set. No UI path.

**Fix**:
- Add `idleSimEnabled` / `idleSimIntervalSeconds` to `config.py` `DEFAULT_CONFIG.ai` with env override (`COMFY_IDLE_SIM_ENABLED` / `COMFY_IDLE_SIM_INTERVAL_SECONDS`)
- Read these in `lifecycle.py` to conditionally register the scheduler
- Add idle-sim message styling in `MessageItem.jsx` (already partially done)
- Add a "View idle summary" affordance in ChatWorkspace

### 2.2 Inline illustration lands inline
**Current state**: `ChatWorkspaceContext.jsx` "Illustrate" creates an image job but the result only appears in the Scenes modal.

**Fix**:
- Attach generated images to the originating message via `world_integration_service`
- Show inline thumbnails in `MessageItem.jsx` for messages with `illustration` metadata
- Keep gallery copy in Scenes modal

### 2.3 Branch switching persists
**Current state**: `activeBranch` resets to `null` on remount/refresh.

**Fix**:
- Sync `activeBranch` to URL query param (`?branch=...`) or `localStorage`
- Read on mount to restore selection

### 2.4 Scene progress bar is real
**Current state**: `ChatContextPanel.jsx` hardcodes `style={{ width: '60%' }}` with `animate-pulse`.

**Fix**:
- Drive from `sceneStream.jobData?.progress` (live data already exists)

### 2.5 Agentic narration visible
**Current state**: Intermediate narration is NOT persisted as a message; `isNarrator` styling in `MessageItem.jsx` is unreachable.

**Fix**:
- Persist narration turns as visible messages (with narrator styling) in `world_integration_service`
- User sees the scene being set, not just the character reply

### 2.6 Chat-level TTS voice selector
**Current state**: Per-message voice override exists; no chat-wide selector.

**Fix**:
- Add voice dropdown in `ChatContextPanel.jsx` that sets `tts_voice_id` for the whole chat

### 2.7 Unbounded message loads
**Current state**: `generate_swipe`, `rollback_chat`, `regenerate_reply`, `suggest_reply`, `impersonate` load all messages with no limit.

**Fix**:
- Cap at `CHAT_HISTORY_HARD_CAP` (5000) or `MAX_CONTEXT_MESSAGES`
- Add configurable limit in chat settings

---

## Phase 3 — Story Sandbox Completeness

### 3.1 Illustrate → image embed works end-to-end
**Current state**: `useIllustrateChapter` + `IllustrateModal.jsx` exist; verify generated image embeds in chapter content.

**Fix**:
- Wire result back into editor content / chapter body via `world_integration_service`
- Show inline thumbnail in chapter editor

### 3.2 Export produces real images
**Current state**: `stories.py:285-360` builds PDF/vertical strip; gray-placeholder fallback was fixed. Validate on a live story.

**Fix**:
- Confirm panels render actual story art, not blanks
- Harden fallback and add per-page illustration generation option

### 3.3 Parse/import story extracts entities
**Current state**: `ParseStoryModal.jsx` + `useParseStory` exist. Confirm LLM extraction workflow runs.

**Fix**:
- Wire results into World Vault (create characters/locations/lorebooks from extracted entities)

### 3.4 @mention entity picker inserts + resolves
**Current state**: `MentionPicker.jsx` exists. Verify inserting a mention resolves to entity.

**Fix**:
- Confirm story context panel injects mentioned characters/lore/locations into continuation prompt

---

## Phase 4 — World Vault Completeness

### 4.1 Relationship Graph deep-links to entities
**Current state**: `RelationshipGraph.jsx` navigates to list page, not specific entity.

**Fix**:
- Add deep-link support (`#char-{id}`, `#story-{id}`, etc.)
- Make node clicks open the entity detail page

### 4.2 World Timeline entity pickers
**Current state**: Filters are raw text inputs requiring UUIDs.

**Fix**:
- Replace with entity pickups (character/location/story dropdowns) reusing existing picker components

### 4.3 World Vault search dead code paths
**Current state**: `world_hub.py:214` search never returns `location`/`branch` types, but `WorldVaultHub.jsx` handles them.

**Fix**:
- Implement location/branch search or remove dead handler branches

### 4.4 Pagination / limits
**Current state**: `world_hub.get_relationships` loads all stories into memory with no limit.

**Fix**:
- Add pagination/limit + surface dangling links
- Apply to `characters.py`, `world_hub.py` character/chat links

---

## Phase 5 — Generator Completeness

### 5.1 ComfyNode widgets end-to-end (carried from uncommitted)
**Current state**: Widgets are now wired to `setWidget` via `setNodes`. Presets have empty `widgets: {}`.

**Fix**:
- Populate `presets.js` with sane defaults so loading "Standard SDXL" configures prompt/seed/size
- Verify: changing a widget value then compiling produces a prompt that includes the value

### 5.2 Batch generate workflow wiring
**Current state**: `BatchGenerate.jsx` sends `{ nodes: {}, edges: [] }` relying on backend `WorkflowBuilder` to rebuild.

**Fix**:
- Confirm this is intentional (document) or wire real node graphs

### 5.3 Empty-model CTAs
**Current state**: `NoCheckpointCTA.jsx` exists; verify it's imported in all generator variants.

**Fix**:
- When no checkpoints, link to `/models/discover` from all generator variants

---

## Phase 6 — Frontier Validation (parallel)

### 6.1 RAG autobiographical memory
- Confirm embeddings generate (local SBERT, CPU)
- Confirm recall surfaces in chat/story context
- Add settings toggle + "why this memory" debug
- Surface degradation (keyword fallback) to user

### 6.2 Animatediff avatar display
- Confirm `VHS_VideoCombine` output path reaches `world_integration_service._handle_avatar_animate` with non-empty `result_paths`
- Verify animated avatar renders in `Characters.jsx`
- Gate "Animate Avatar" button until validated

### 6.3 Idle simulation (backend validation)
- Confirm `lifecycle.py` schedules `run_idle_simulation_tick`
- Verify a chat with `idle_sim_enabled` produces summarized offline activity

### 6.4 Comic/Webtoon export (live validation)
- Confirm on a real story with real images
- Panels render actual story art, not blanks

---

## Phase 7 — Polish & Quality-of-Life (ongoing)

| # | Task | Status |
|---|------|--------|
| 7.1 | Keyboard shortcuts verified | Partially done |
| 7.2 | Image gallery virtualization (`@tanstack/react-virtual`) | Partially done |
| 7.3 | Branding live reactivity | Partially done |
| 7.4 | Drag-and-drop sorting for characters/stories/lorebooks/locations | Done for characters |
| 7.5 | Prompt Library discoverability | Needs sidebar link |
| 7.6 | Statistics cross-pillar filter | Done |
| 7.7 | E2E in CI | `.github/workflows/frontend-e2e.yml` exists, needs verification |
| 7.8 | Error boundaries per lazy page | Done at app level, verify per-page |

---

## Verification Gates

### Per-phase
```bash
# Backend
cd backend_v2 && pytest -q

# Frontend
cd frontend_v2 && npm test && npm run lint

# E2E (requires running stack)
cd frontend_v2 && npx playwright test
```

### Full stack spin-up
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d
```

### Manual verification checklist
- [ ] `regenerate_reply` returns correct `removed_messages` count without crash
- [ ] ChatWorkspace: idle sim toggle enables scheduler
- [ ] ChatWorkspace: inline illustrations appear in messages
- [ ] ChatWorkspace: branch selection persists across refresh
- [ ] ChatWorkspace: narration turns visible as styled messages
- [ ] StorySandbox: export produces real images in comic/webtoon
- [ ] Lorebooks: page CRUD + entry management + search works
- [ ] ComfyNode: widget edits propagate to compiled workflow
- [ ] WorldTimeline: entity pickers replace raw UUID inputs
- [ ] API: all frontend calls use centralized modules
- [ ] No `services → api.routes` imports remain
- [ ] All repositories used by their routes
- [ ] Beam client test passes

---

## Risk Register

| Risk | Mitigation |
|------|-----------|
| Scope too large | Strict phase gating; each phase is independently shippable |
| Database migrations fail | Test migrations on SQLite before merging (already done) |
| Frontend bundle bloat | Lazy-load new pages; monitor bundle size |
| Provider code duplication | Extract shared base class in Phase 1 |
| Global mutable state | Document each; convert LoadBalancer to instance-based |
| Silent errors | Replace all `except Exception: pass` with `ComfyError` or toast |

---

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Fix `regenerate_reply` first | P0 crash; blocks chat usability |
| Grandfather legacy `/api/*` | Migration cost > benefit for single-user app |
| Keep LoadBalancer class-level state | Documented in AGENTS.md; refactor in Phase 1 |
| Lorebooks as full page | Matches Characters/Locations pattern |
| Idle sim default OFF | Preserves existing behavior; user opts in |
