> **SUPERSEDED** by `.kilo/plans/1787583794283-tnhcomfy-hardening-plan.md` (2026-08-24 audit). This document contained many false-positive line items that have been debunked — see Appendix A. Use the new plan as the authoritative source for all remaining work.

# TNHComfy Roadmap — Consolidated Plan

> **Authoritative plan.** Supersedes `PLAN.md` and `REMEDIATION_PLAN_v2.md` (both are now stale and contain many false-positive line items — see Appendix A). This document reflects a thorough code audit performed 2026-08-22.

## 0. Vision (unchanged)

A **Comprehensive AI Fantasy Engine** for a single power user:
1. **Image Generation** — ComfyUI wrapped via serverless providers (Modal, Beam, direct_url, remote_comfy).
2. **Roleplay Chatbots** — SillyTavern-style, stateful, agentic (autonomous scene narration / image generation).
3. **Story Sandbox** — AI Dungeon-style interactive editor, with image/comic export.
4. (Frontier) **RAG autobiographical memory**, **agentic idle simulation**, **video/AnimateDiff avatars**, **visual-novel/comic compiler**, **relationship graph**, **world timeline**, **campaigns**.

## 1. Current verified state

- **Backend:** ~1506 tests, green. AnimateDiff `build_video_job_workflow` double-wrap bug **fixed this session** (see §2.1) with regression test added.
- **Frontend:** tests green, lint 0 errors. Chat/Story/World-Vault features are **implemented and wired**, not stubbed (verified: swipe, branches, inline image/TTS, sidebar CRUD, Cmd+K palette, MDEditor, export modal, mention picker).
- **Vision frontiers: largely implemented**, not missing:
  - RAG: `services/rag_pipeline.py` is imported by `context_builder.py` (lorebook + memory search).
  - Idle sim: `services/agent_simulation.py` + `api/lifecycle.py` scheduler runner exists.
  - Comic/Webtoon: `api/routes/world_vault/stories.py:285-360` builds PDF/vertical strip.
  - Relationship Graph, World Timeline, Campaigns, Avatar Gallery: present.
- **Real gaps** are mostly **unvalidation, rough edges, and non-unification** — see §2.

## 2. Track A — Pillar hardening & validation (parallel)

Goal: make the 3 pillars genuinely usable end-to-end for a casual/power user, and unify the codebase.

### 2.1 Critical correctness (P1) — DONE this session
- [x] **AnimateDiff double-wrap**: `build_video_job_workflow` returned `{"prompt": nodes, "type":"video"}` but the worker posts `{"prompt": <workflow>}` to ComfyUI → nested prompt rejected. Fixed to return bare nodes (`core/workflow_builder.py:636`). Metadata still carries `"type":"video"`, so `chats.py:492` job-type resolution is unaffected. Regression test: `tests/test_animatediff_workflow.py`.
- [ ] **Verify video output path on worker**: `VHS_VideoCombine` writes a `.webp`/`.mp4`; confirm `world_integration_service._handle_avatar_animate` receives a non-empty `result_paths` and the animated avatar renders in `Characters.jsx`. Needs a live worker run.

### 2.2 TTS / narration affordance (P1, decided: keep OFF by default + in-chat prompt)
- TTS is fully wired but gated by `settings.ai.ttsEnabled` (default `false`), so a casual user sees no voice feature.
- [ ] Add a one-click **"Enable narration" affordance inside Chat** (e.g. a banner/button in `MessageTimeline`/`ChatWorkspace` when `ttsEnabled` is false) that flips the setting via the existing Settings endpoint. Keep default off.

### 2.3 API versioning unification (P2)
- Mix of `/api/`, `/api/v2/`, `/api/settings/`, `/api/providers`, `/api/jobs`, `/api/collections`.
- [ ] Standardize on `/api/v2/` for the World Vault + providers + collections; add a single `API_BASE`/version helper in `frontend_v2/src/api/client.js`. Legacy `/api/generate`, `/api/files`, `/api/prompts`, `/api/view`, `/api/thumbnail` can stay (pre-V2). Avoid per-call hard-coded versions.
- Files: `collectionsApi.js`, `providers.js`, `useLLMProviderStatus.js`, `useFavorites.js`, `useBranding.js`, `useLLMJobResult.js`.

### 2.4 WebSocket event coverage (P2)
- `useChatStreaming.js` handles only `JOB_PROGRESS`, `JOB_COMPLETED`, `JOB_FAILED`, `JOB_CANCELLED`. Missing `JOB_CREATED`, `JOB_UPDATED`, `JOB_POST_PROCESSING` (defined in `websocket.js`).
- [ ] Handle `JOB_POST_PROCESSING` so image gen shows real "saving/uploading" progress instead of hanging on "Preparing generation…". Handle `JOB_CREATED`/`JOB_UPDATED` for queue-position/status enrichment.

### 2.5 Performance & scaling (P2)
- [ ] `world_hub.get_relationships` (`api/routes/world_vault/world_hub.py:64-177`) does `select(Story).all()` with no limit, then in-memory joins; silently drops links to deleted entities. Add pagination/limit + surface dangling links.
- [ ] `list_chat_jobs` / `regenerate_reply` use `meta["chat_id"].as_string()` (Postgres-flavored, unindexed). Portable but not indexable — acceptable for single-user; optional rewrite to `JSONExtract`/Python-side filter.
- [ ] `orchestrator_service.execute_tool` has no top-level `asyncio.wait_for` (only inner per-call timeouts) → a misbehaving tool can hang the agentic loop. Add a configurable top-level timeout.
- [ ] `orchestrator_service` calls `report_failure` on provider `mode` config mismatch before any job runs → inflates failure counters. Only report on genuine runtime failure.

### 2.6 Dead code / cleanup (P2/P3)
- [ ] Remove dead `frontend_v2/src/hooks/useEntityCRUD.js` (never imported).
- [ ] Resolve `ModelSelector.jsx` (generator) vs `components/model-selector/` (model manager) naming collision — rename one.
- [ ] `useVoices.js:11` `enabled: characterId === null || !!characterId` is always-true no-op — simplify.
- [ ] `context_builder.prune_context` keyed on `(role, content[:200])` — rare collision risk; consider message UUID.

## 3. Track B — Vision frontier validation (parallel)

These exist but are **unverified**; validate and polish rather than rebuild.

- [ ] **RAG**: confirm embeddings generate (local SBERT, CPU — watch startup/latency), recall surfaces in chat/story context. Add a settings toggle + a "why this memory" debug.
- [ ] **Idle simulation**: confirm `lifecycle.py` actually schedules `run_idle_simulation_tick`; verify a chat with `idle_sim_enabled` produces summarized offline activity. Add UI to view the summary on return.
- [ ] **Comic/Webtoon export**: confirm image panels are generated (currently falls back to gray placeholder if image embed fails — `stories.py:330`). Wire per-page illustration generation so comics aren't blank.
- [ ] **Animatediff avatar display** (see §2.1) — show the resulting animated avatar in the character card/gallery.
- [ ] **Relationship Graph / World Timeline / Campaigns**: click-through validation; ensure filters persist (Timeline URL filters already implemented) and entity links resolve.

## 4. Track C — QA & quality-of-life (parallel, ongoing)

- [x] **E2E in CI**: Playwright runs in `frontend-e2e.yml` against the PostgreSQL/pgvector service; fullstack-tagged provider billing tests remain opt-in.
- [ ] **Keybindings** (already partially present): verify Chat `Ctrl+Enter`/`Ctrl+N`, Story `Ctrl+S`/`Ctrl+Shift+C`.
- [ ] **Image gallery virtualization** (`@tanstack/react-virtual`) for `Dashboard.jsx`.
- [ ] **Branding live reactivity** (poll/WS) without refresh.
- [ ] **Statistics cross-pillar**: workspace filter + chat/story/LLM analytics.
- [ ] **Drag-and-drop sorting** (`@dnd-kit/sortable`) for characters/stories/lorebooks/locations.
- [ ] **Prompt Library** discoverability (`/prompts` route + sidebar link).

## 5. Verification gates (every phase)

```bash
# Backend (run inside container: docker exec tnhcomfy-backend python -m pytest -q)
cd backend_v2 && pytest

# Frontend
cd frontend_v2 && npm test && npm run lint

# E2E (backend running)
cd frontend_v2 && npx playwright test

# Full stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d
```

## 6. Git note

- Working tree was clean at audit time; branch is **2 commits ahead of `origin/master`** (`2ea8aba`, `b2107d8` — the AnimateDiff feature). The §2.1 fix is currently an **uncommitted working-tree change**. Before pushing, amend `2ea8aba` (or rebase) to include the fix so the feature ships correct.
- Do **not** push without confirming the video output path (§2.1) works on a live worker, or gate the Animate Avatar button until validated.

## 8. Session 2026-08-22 log (implemented & verified locally)

All changes verified locally: backend `pytest` 1510 pass / 6 skip; frontend `npm test` 532 pass; `npm run lint` 0 errors. Changes applied to working tree (`backend_v2/`, `frontend_v2/`, repo `ROADMAP.md`); nothing committed.

- Animatediff double-wrap fix + `tests/test_animatediff_workflow.py`.
- ChatWorkspace TTS-enable banner + `Settings.jsx` toggle + `settingsStore.ragEnabled` default + save payload.
- RAG gate (`services/rag_pipeline.rag_enabled()`) + `tests/test_rag_pipeline.py`.
- `useEntityCRUD.js` deleted; `useVoices.js` enabled no-op removed.
- `useChatStreaming.js`: `JOB_CREATED`/`JOB_UPDATED`/`JOB_POST_PROCESSING` handlers.
- `world_hub.py`: story limit 200 + dangling link flag + test.
- `orchestrator_service.py`: 120s `execute_tool` timeout; removed `report_failure` on mode mismatch.
- `stories.py`: comic/webtoon embeds real story images; fixed `title` UnboundLocalError; tests.
- `Statistics.jsx`: ALL/IMAGE/CHAT/STORY filter + World Vault pillars panel; backend `statistics.py` `pillars` block.
- `Characters.test.jsx`: fixed broken mock (missing `useAnimateCharacterAvatar` from commit 2ea8aba).

## 9. Runtime validation (needs stack refresh — not yet executed)

The running `tnhcomfy-backend`/`tnhcomfy-frontend` containers serve stale, **image-embedded** code (source is bind-mounted only via `docker-compose.dev.yml`, not the base compose currently used). To reflect this session's edits live, refresh **without wiping dev data**:

```bash
# dev compose bind-mounts ./backend_v2->/app (uvicorn --reload) and ./frontend_v2/src->/app/src (vite polling)
docker compose -f docker-compose.yml -f docker-compose.dev.yml --build -d
# (omit -V so the dev DB volume is preserved; migrations auto-run at boot)
```
Then:
- `curl http://localhost:8002/api/statistics/detailed | jq .pillars` → confirm cross-pillar counts.
- Validate RAG recall, idle-sim tick, and Animatediff video avatar end-to-end (providers require Modal/Beam credentials; if absent, image jobs fall back to none — verify via logs).

| Decision | Choice |
|----------|--------|
| AnimateDiff commits (P1 bug) | Fix now, keep feature |
| TTS default | Keep OFF, add in-chat enable affordance |
| Focus | Parallel: pillars + frontiers together |
| Planning docs | Consolidate into this ROADMAP.md; old PLAN.md / REMEDIATION_PLAN_v2.md are stale |

## Appendix A — Debunked stale-plan items (DO NOT re-do)

These were listed as bugs in `REMEDIATION_PLAN_v2.md` but are **already fixed or false positives**:
- 0.1 `substitute_tavern_vars` double-substitute — works; removing the masked-restore would regress `{{char}}`/`{{user}}`.
- 0.2 `build_chat_context` skips `world_state` — already skipped for both dict and SQLModel.
- 0.3 `prune_context` uses `id(m)` — now uses `(role, content[:200])`.
- 0.4 `list_chat_jobs` SQLite break — portable under SQLAlchemy 2.0.52 (unindexed only).
- 1.2 `queue_position` `exclude=True` — not excluded; returned in responses.
- 1.4 `LorebookEntry.updated_at` — present; migration 052 adds columns.
- 1.5 dead `StoryRepository` import — used as `Depends` type.
- 1.3 `useVoicePreview` undefined `voiceId` — works; destructures from args.
- 1.8 `worldVaultStore` empty stub — holds `activeChatId` (UI state, correct).

## 10. Session 2026-08-24 audit — Codebase hardening & feature completeness

> Deep audit performed 2026-08-24. Focus: correctness, dead code, duplication, performance, missing integration, feature completeness.

### 10.1 Critical correctness (P0) — Must fix before next deploy

| # | Issue | File | Action |
|---|-------|------|--------|
| 10.1.1 | **Undefined `job_workflow`** in `_finalize_llm_job` agentic branch — crashes when a chat reply contains tool_calls | `services/job_processing.py:405` | Replace `job_workflow.get("tools")` with `job.metadata_.get("tools")` (or `job.workflow`); add test |
| 10.1.2 | **CI E2E uses plain Postgres 16** — resolved by using `pgvector/pgvector:pg16` in `frontend-e2e.yml` | `.github/workflows/frontend-e2e.yml` | Completed; keep the pgvector service image |

### 10.2 High priority (P1) — Fix in current sprint

| # | Issue | File | Action |
|---|-------|------|--------|
| 10.2.1 | **StoryReader blob download broken** — `api.get(..., { responseType: 'blob' })` returns a `Response`, not a `Blob`; `URL.createObjectURL` receives a Response | `frontend_v2/src/pages/StoryReader.jsx:44` | Use `await data.blob()`; fix `client.js` to handle `responseType` or document that callers must call `.blob()` |
| 10.2.2 | **Duplicate `cleanup_orphaned_models`** — method defined twice (lines 1249 and 1314); second shadows first, confusing maintenance | `infrastructure/repositories/model_repo_v2.py:1314` | Remove the second definition (line 1314); keep the more complete first version (line 1249) |
| 10.2.3 | **`import time` inside async `__call__`** — redundant; `time` already imported at module top | `services/provider_client.py:249` | Remove the inline import |

### 10.3 Medium priority (P2) — Fix in parallel

| # | Issue | File | Action |
|---|-------|------|--------|
| 10.3.1 | **`agent_simulation` busy check loads ALL recent LLM jobs** — should filter by `chat_id` in query | `services/agent_simulation.py:85` | Add `.where(Job.meta["chat_id"].as_string() == chat_id)` or pass chat_id into the check |
| 10.3.2 | **`model_reconciliation.py` path normalization assumes `models/` prefix** — fails for custom paths | `services/model_reconciliation.py:102` | Use `os.path` or `pathlib` to strip only a leading `models/` if present |
| 10.3.3 | **`reference_cleanup.py` is dead code** — defined but never imported/called | `services/reference_cleanup.py` | Delete file or wire into entity deletion flows |
| 10.3.4 | **Dead exports in `useProviderModels.js`** — `normalizeModalStats`/`mergeModalStats` unused | `frontend_v2/src/hooks/useProviderModels.js` | Remove unused exports |
| 10.3.5 | **Dead `moveAsset` re-export** — redundant wrapper around `assetsApi.move` | `frontend_v2/src/api/files.js:88` | Remove `moveAsset` export |
| 10.3.6 | **App.jsx double-subscribes to settingsStore** — `queryUiSettings` + `useSettings()` both read the same store | `frontend_v2/src/App.jsx:168-169` | Keep only `useSettings()` and derive `ui` from it |

### 10.4 Feature completeness gaps (Track B — Frontier validation)

These features **exist** but are unverified or rough-edged:

| # | Feature | Status | Action |
|---|---------|--------|--------|
| 10.4.1 | **RAG embeddings** | Implemented but unverified | Verify `embedding_service.py` lazy-loads SBERT, test recall quality, add debug UI ("why this memory?") |
| 10.4.2 | **Idle simulation** | Implemented but unverified | Confirm `lifecycle.py` schedules ticks; verify summaries appear; add UI to view offline activity |
| 10.4.3 | **Comic/Webtoon export** | Implemented but fallback to gray placeholders | Wire per-page illustration generation so comics aren't blank |
| 10.4.4 | **Animatediff avatar display** | Fixed backend; frontend display unverified | Show animated avatar in character card/gallery |
| 10.4.5 | **Relationship Graph / World Timeline / Campaigns** | Implemented but click-through validation needed | Ensure filters persist and entity links resolve |

### 10.5 Verification gates

```bash
# Backend
cd backend_v2 && pytest -q

# Frontend
cd frontend_v2 && npm test && npm run lint

# E2E (requires stack running)
cd frontend_v2 && npx playwright test

# Full stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d
```
