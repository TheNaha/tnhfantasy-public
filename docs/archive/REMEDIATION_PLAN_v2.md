> **ARCHIVED** — historical, kept for provenance only. This document was
> stale or superseded when archived and may contradict current code.
> **Archived. See docs/STATUS.md and docs/archive/README.md.**

> **SUPERSEDED** by `ROADMAP.md` (2026-08-22 audit). The "Unstaged Changes — 68 files" section is stale (tree was clean at audit) and several P0 items are false positives — see `ROADMAP.md` Appendix A.

# TNHFantasy Remediation & Feature-Completeness Plan

## Executive Summary

TNHFantasy has a solid architectural foundation but rapid feature additions have introduced **5 P0 production bugs**, **significant performance issues**, **integration gaps**, and **incomplete implementations** that make the new workspaces feel "demo-like." This plan prioritizes fixes and feature-completeness work to make the site usable out-of-box for casual users while adding depth for power users.

**Current state:**
- Backend: 1466 tests passing, 2 skipped
- Frontend: 532 tests passing, lint 0 errors
- E2E: 24 spec files, but **not wired into CI**; duplicate test blocks in `world-vault.spec.js` and `world-vault-hub.spec.js`
- Unstaged changes: 68 modified files, 3 new untracked (mostly coherent, with a few broken patterns)

---

## Phase 0 — Critical Bug Fixes (Week 1)

> Zero new features. Fix bugs that break core functionality.

| # | Severity | Issue | File | Fix |
|---|----------|-------|------|-----|
| 0.1 | **P0** | `substitute_tavern_vars` double-substitutes `{{...}}` tokens | `services/chat_utils.py:101-107` | Remove the final `_DOUBLE_BRACE_PATTERN.sub()` call; masked tokens are already restored in the loop |
| 0.2 | **P0** | `build_chat_context` skips `world_state` only for SQLModel objects, not dicts | `services/context_builder.py:614-651` | Add `if meta.get("source") == "world_state": continue` in the dict branch |
| 0.3 | **P0** | `prune_context` uses `id(m)` which breaks with fresh DB objects | `services/context_builder.py:196-208` | Use message UUID or index-based matching instead of Python object identity |
| 0.4 | **P0** | `list_chat_jobs` uses PostgreSQL-only `.as_string()` JSONB syntax | `api/routes/world_vault/chats.py:482` | Use SQLAlchemy `JSONExtract` or Python-side filter for SQLite compatibility |
| 0.5 | **P0** | `_tool_narrate_scene` corrupts load-balancer counters (inline execution bypasses queue) | `services/orchestrator_service.py:517-519` | Either claim provider through normal queue path, or skip `report_success`/`release_job` for inline execution |

**Verification:** `pytest -q` green; `npm test` green.

---

## Phase 1 — Stabilization & Integration (Week 2)

> Fix correctness issues, dead code, and integration gaps.

| # | Issue | Action | Files |
|---|-------|--------|-------|
| 1.1 | `job_service.get_job` returns stale object on concurrent deletion | Catch `DetachedInstanceError`/`ObjectDeletedError` and raise `NotFoundError` | `services/job_service.py:75-79` |
| 1.2 | `queue_position` excluded from API responses | Remove `exclude=True` from `Job.queue_position` entity field | `core/entities.py:96` |
| 1.3 | Frontend `useVoicePreview` hook broken (undefined `voiceId`) | Redesign hook to accept `voiceId` via `mutationFn` variables | `frontend_v2/src/hooks/useVoices.js` |
| 1.4 | `LorebookEntry` entity missing `updated_at` (migration 052 adds it) | Add `updated_at` field to entity | `core/entities.py` |
| 1.5 | Dead `StoryRepository` import in `stories.py` | Remove unused import | `api/routes/world_vault/stories.py:12` |
| 1.6 | API URL versioning inconsistency (`/api/` vs `/api/v2/`) | Standardize all frontend API calls to `/api/v2/` | `frontend_v2/src/api/client.js`, all hooks |
| 1.7 | WebSocket events not fully typed (`JOB_POST_PROCESSING`, `JOB_CREATED` missing) | Add handlers in `useChatStreaming.js` | `frontend_v2/src/hooks/useChatStreaming.js` |
| 1.8 | `worldVaultStore.js` is essentially empty stub | Either implement properly or remove to avoid confusion | `frontend_v2/src/store/worldVaultStore.js` |

**Verification:** `pytest -q` green; `npm test` green; `npm run lint` 0 errors.

---

## Phase 2 — Performance & Scalability (Week 3)

> Fix O(n*m) queries and unbounded caches.

| # | Issue | Action | Files |
|---|-------|--------|-------|
| 2.1 | `world_hub.get_relationships` loads all stories into memory + N+1 queries | Use SQLAlchemy JSON containment operators or normalize to junction table | `api/routes/world_vault/world_hub.py:80-128` |
| 2.2 | `regenerate_reply` scans 200 jobs in memory | Use indexed query on `(task_type, metadata_->>'chat_id')` | `api/routes/world_vault/chats.py:823-832` |
| 2.3 | Unbounded `_cached_estimate_tokens` LRU cache (keys on full message text) | Add TTL or switch to UUID-based caching | `services/context_builder.py:55` |
| 2.4 | No per-tool timeout in orchestrator | Wrap `execute_tool` with configurable timeout (e.g., 60s image, 30s narration) | `services/orchestrator_service.py` |

**Verification:** Add performance tests for `build_chat_context` with 500+ messages.

---

## Phase 3 — Test Coverage & CI (Week 4)

> Close testing gaps and wire E2E into CI.

| # | Task | Action | Files |
|---|------|--------|-------|
| 3.1 | E2E CI | Add Playwright execution to `.github/workflows/frontend-tests.yml` (install browsers, start backend, run `npx playwright test`) | `.github/workflows/frontend-tests.yml` |
| 3.2 | Duplicate E2E tests | Remove `world-vault-hub.spec.js` (duplicate of block in `world-vault.spec.js`) | `frontend_v2/e2e/world-vault-hub.spec.js` |
| 3.3 | Flaky timeout waits | Replace `page.waitForTimeout()` with `waitForResponse` in search tests | `e2e/world-vault-hub.spec.js`, `e2e/new-pages.spec.js` |
| 3.4 | Backend unit tests for P0 fixes | Add tests for `substitute_tavern_vars`, `prune_context`, `list_chat_jobs` SQLite compat | `backend_v2/tests/` |
| 3.5 | Frontend unit tests for broken hooks | Test `useVoicePreview`, `useWorldVaultStore` (if kept) | `frontend_v2/src/hooks/` |
| 3.6 | E2E coverage gaps | Add tests for `/statistics`, command palette, WebSocket realtime updates, agentic tool flow | `frontend_v2/e2e/` |

**Verification:** CI green on push; `npx playwright test` passes locally.

---

## Phase 4 — Feature Completeness (Week 5–8)

> Make new workspaces feel complete, not demo-like.

### 4.1 Chat Workspace (Roleplay)
| # | Feature | Action |
|---|---------|--------|
| 4.1.1 | Swipe UX polish | Wire `MessageItem` swipe actions end-to-end (currently stubbed) |
| 4.1.2 | Branch management UI | Add branch creation/switching in `MessageTimeline` |
| 4.1.3 | Inline generation | Add manual trigger buttons for image/audio per message |
| 4.1.4 | Chat sidebar CRUD | Add create/switch/delete chats from sidebar (only direct URL nav exists today) |
| 4.1.5 | Agentic idle simulation backend | Implement cron job for `Chat.idle_sim_enabled` (entity + UI exist, no backend runner) |

### 4.2 Story Sandbox
| # | Feature | Action |
|---|---------|--------|
| 4.2.1 | Scene-chain authoring | Wire `illustrate → batch variations` flow from story editor |
| 4.2.2 | Export modal wiring | Wire `useExportStory` in `StoryReader` (currently dead hook) |
| 4.2.3 | Rich text formatting | Upgrade editor beyond plain textarea |
| 4.2.4 | Inline entity referencing | View/edit Character/Lorebook entries without leaving editor |

### 4.3 World Vault
| # | Feature | Action |
|---|---------|--------|
| 4.3.1 | Locations page polish | Ensure CRUD + search + tags work end-to-end |
| 4.3.2 | Relationship Graph interactivity | Add pan/zoom, node click → open entity, hover tooltips |
| 4.3.3 | Campaign entity linking | Ensure all 4 entity pickers work + dashboard modal functional |
| 4.3.4 | World Timeline filters | Persist filters in URL query, sticky date-group headers |

### 4.4 Generator
| # | Feature | Action |
|---|---------|--------|
| 4.4.1 | Primitive node inputs | Render string/number/boolean/ENUM widgets in `ComfyNode.jsx` |
| 4.4.2 | Checkpoint CTA | When no checkpoints, link to `/models/discover` |
| 4.4.3 | Batch Studio presets v2 | Save/load named batch configs to Settings |

### 4.5 Onboarding & UX
| # | Feature | Action |
|---|---------|--------|
| 4.5.1 | First-run wizard | Already implemented; verify it auto-opens on fresh stack |
| 4.5.2 | Provider auto-detection | Already implemented; verify Detect button works |
| 4.5.3 | Starter pack seed | Already implemented (migration 049); verify demo character + scenario appear |
| 4.5.4 | Error boundaries per page | Wrap each lazy-loaded page in `ErrorBoundary` |
| 4.5.5 | Keyboard shortcuts | Chat: `Ctrl+Enter`, `Ctrl+N`. Story: `Ctrl+S`, `Ctrl+Shift+C` |

**Verification:** `pytest` green; `npm test` green; `npx playwright test` green.

---

## Phase 5 — Vision Frontiers (Parallel, After Stability)

> Massive future capabilities from VISION.md.

| # | Frontier | Action |
|---|----------|--------|
| 5.1 | Autobiographical Memory (RAG) | `rag_pipeline.py` already exists; wire into `context_builder` for long-campaign recall |
| 5.2 | Visual Novel / Comic Compiler | Backend exporter using PIL + `img2pdf`; frontend export modal |
| 5.3 | Agentic Idle Simulation | Cron service for offline character activity (prereq: Group Chats) |
| 5.4 | Video / Animation | AnimateDiff support in ComfyUI payload |
| 5.5 | AI Story Parsing & Import | LLM tool workflow to extract entities from pasted text |

---

## Unstaged Changes — Immediate Issues

The current working tree has **68 modified files + 3 new untracked** with these issues:

| # | Issue | Severity | Action |
|---|-------|----------|--------|
| 1 | `useVoicePreview` hook broken (undefined `voiceId`) | P0 | Fix hook to accept `voiceId` via `mutationFn` variables |
| 2 | `LorebookEntry` entity missing `updated_at` (migration 052 adds it) | P1 | Add `updated_at` field to entity |
| 3 | Dead `StoryRepository` import in `stories.py` | P2 | Remove unused import |
| 4 | Trailing whitespace in `chats.py:96` | P2 | Trim whitespace |
| 5 | Changes are large and uncommitted | P2 | Review and commit in logical chunks once fixes are applied |

Otherwise the changes are **coherent**: RAG centralization, voice preview/TTS dispatch, provider aliases, retry handling, repository cleanup (dead methods removed), load-balancer health-cache improvement, and query-key normalization.

---

## Recommended Execution Order

```
Phase 0 (Week 1) — P0 bug fixes
  └─ Phase 1 (Week 2) — Stabilization & integration
       └─ Phase 2 (Week 3) — Performance
            └─ Phase 3 (Week 4) — Tests & CI
                 └─ Phase 4 (Week 5–8) — Feature completeness
                      └─ Phase 5 (Parallel) — Vision frontiers
```

**Start with Phase 0.1 (substitute_tavern_vars)** — it's a pure correctness fix with no side effects.

---

## Commands

```bash
# Full stack spin-up
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d

# Backend only
cd backend_v2 && .venv/bin/pytest

# Frontend only
cd frontend_v2 && npm test && npm run lint

# E2E (requires backend running)
cd frontend_v2 && npx playwright test
```
