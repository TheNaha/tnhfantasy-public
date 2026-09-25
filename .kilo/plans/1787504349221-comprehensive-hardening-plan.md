# TNHComfy — Consolidated Hardening & Feature-Completeness Plan

> **Authoritative.** Consolidates and supersedes: `PLAN.md`, `REMEDIATION_PLAN_v2.md`, `DEMO_GAPS_PLAN.md`, `ROADMAP.md`, and all prior `.kilo/plans/*.md` files. This plan reflects a code audit performed **2026-08-23**.

## 0. Vision (unchanged)

A single-user **Comprehensive AI Fantasy Engine** with three unified pillars sharing a PostgreSQL + pgvector "World Vault":

1. **Image Generation** — ComfyUI via serverless providers (Modal, Beam, direct_url, remote_comfy)
2. **Roleplay Chatbots** — SillyTavern-style, stateful, agentic (autonomous image/narration tools)
3. **Story Sandbox** — AI Dungeon-style interactive editor with comic/export

Future frontiers (VISION.md): RAG memory, visual-novel compiler, relationship graph, agentic idle sim, video/AnimateDiff.

---

## 1. Current Verified State

| Metric | Value |
|--------|-------|
| Backend tests | 1516 collected (pytest, Python 3.14 venv) |
| Frontend tests | 532 passing (vitest) |
| Frontend lint | 0 errors (eslint) |
| Backend lint | `ruff check .` passes |
| E2E specs | 28 Playwright spec files in `frontend_v2/e2e/` |
| E2E in CI | `frontend-e2e.yml` runs Playwright on `frontend_v2/**` and `backend_v2/**` changes |
| Migrations | 063 (latest at the audit snapshot) in `infrastructure/migrations/steps.py` |
| Git state | 3 commits ahead of `origin/master` + 1 uncommitted file |

### 1.1 Already Done (committed in the 3 commits, **do not redo**)

Per ROADMAP.md §8 and code inspection — the following items from stale plans are already committed:

| Item | Commit | Verification |
|------|--------|-------------|
| AnimateDiff double-wrap fix (`build_video_job_workflow` returns bare nodes) | `e48e0fb` | `workflow_builder.py:636` returns `workflow = nodes` |
| AnimateDiff regression test | `e48e0fb` | `tests/test_animatediff_workflow.py` |
| RAG pipeline (`rag_pipeline.py`, `rag_enabled()` gate, context_builder wiring) | `e48e0fb` | `services/rag_pipeline.py` imported by `context_builder` |
| RAG tests + settings toggle | `e48e0fb` | `tests/test_rag_pipeline.py`, `settingsStore.js` |
| ChatWorkspace TTS-enable banner | `e48e0fb` | `settings.ai.ttsEnabled` gate |
| WebSocket handlers (JOB_CREATED, JOB_UPDATED, JOB_POST_PROCESSING) | `e48e0fb` | `useChatStreaming.js:62-128` |
| `useEntityCRUD.js` deleted | `e48e0fb` | File gone (git log confirms deletion) |
| `useVoices.js` enabled no-op removed | `e48e0fb` | `useVoices.js` line 11 simplified |
| `world_hub.get_relationships` story limit (200) | `e48e0fb` | `world_hub.py:81` `.limit(200)` |
| Orchestrator `asyncio.wait_for` timeout (120s) | `e48e0fb` | `orchestrator_service.py:333` |
| report_failure only on genuine runtime failure | `e48e0fb` | `orchestrator_service.py:531-538` has explicit comment |
| Statistics cross-pillar analytics | `e48e0fb` | `statistics.py` pillars block |
| Comic/webtoon embeds real story images | `e48e0fb` | `stories.py` image embeds |
| Stories.py `title` UnboundLocalError fixed | `e48e0fb` | Code has guard |
| Starter pack seed (migration 049) | `e48e0fb` | `_migration_049_seed_starter_pack` |
| AnimateDiff workflow builder + avatar pipeline | `b2107d8`, `2ea8aba` | `core/animatediff_builder.py`, `workflow_builder.py:592` |

### 1.2 Stale Claims Debunked

| Stale plan claim | Reality | Source |
|---|---|---|
| 24 `except: pass` sites in route handlers | Zero bare `except: pass` in project code. All `except` blocks use `except Exception as e:` with logging or `ComfyError` | Grep of `backend_v2/` |
| 14 failing frontend tests | 532 tests pass, lint 0 errors | `npm test` + `npm run lint` |
| ChatWorkspace.jsx is 1500+ lines | 338 lines | `wc -l` |
| `handleIllustrate` declared twice in ChatWorkspace:843 | ChatWorkspace is 338 lines; no duplicate declarations | Code inspection |
| E2E not in CI | `frontend-e2e.yml` runs Playwright on `frontend_v2/**` changes | `.github/workflows/frontend-e2e.yml` exists |
| `patch_chats.py` exists | Does not exist in working tree | `ls` confirms absence |
| `worldVaultStore.js` is 9-line stub | It is 6 lines but still vestigial (only holds `activeChatId`) | File inspection |

### 1.3 Git Status

```
On branch master, up to date with origin/master
3 commits ahead of origin/master:
  e48e0fb feat: Implement RAG (Retrieval-Augmented Generation)
  b2107d8 feat: implement Animatediff workflow builder with node management
  2ea8aba feat: add AnimateDiff avatar generation pipeline

Uncommitted changes:
  modified: provider_containers/image_worker/engines/modal/modal_app.py
```

---

## 2. Git Diff Review: `modal_app.py`

**Status: ✅ Approved — no changes needed.**

The uncommitted change fixes two critical bugs in the Modal image worker's ComfyUI lifecycle:

### Bug A: ComfyUI "restart" silently does nothing (critical)

**Root cause:** `_restart_comfy_server` used `pkill -f "ComfyUI/main.py"` and `pkill -f "comfy launch"`. ComfyUI launched via `comfy-cli --background` daemonizes, so the process cmdline no longer matches either pattern. `pkill` finds zero PIDs, skips the kill, starts a new server that fails with "port already in use", but the readiness probe catches the OLD still-running process answering 200 — so the "restart" silently keeps the same process.

**Fix:** `_find_comfy_pids(port)` uses `psutil.net_connections(kind="inet")` to find PIDs actually bound to the ComfyUI port. Then SIGTERM → wait for death (15s) → SIGKILL fallback → wait for port closed → start new server.

### Bug B: VRAM cleanup runs in wrong process (critical)

**Root cause:** ComfyUI runs in a separate OS process from the Modal function. `torch.cuda.empty_cache()` called in the Modal function process operates on that process's CUDA context, which is empty — it never touches ComfyUI's actual VRAM.

**Fix:** `_free_comfy_memory(port)` makes an HTTP `POST /free` to ComfyUI's own instance, which has the correct VRAM context.

### Additional change:
- Adds `psutil` to the Modal Image `uv_pip_install` dependencies.

**Review notes:** The `import psutil`, `import signal`, `import os`, `import socket`, `import requests` are all inside function bodies (deferred imports), which is fine for a Modal image context. The code is well-commented and defensive.

---

## 3. Remaining Work

### Priority 1 — Correctness & Dead Code (Week 1)

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| P1.1 | `worldVaultStore.js` is a vestigial 6-line stub (only holds `activeChatId`, which is URL-driven) | Either remove entirely + update `App.jsx` import, or expand to track meaningful cross-cutting state (active workspace, recently viewed entities) | `frontend_v2/src/store/worldVaultStore.js`, `frontend_v2/src/App.jsx` |
| P1.2 | `prune_context` merge key `(role, content[:200])` has collision risk for messages with identical first 200 chars | Add a deterministic message UUID or index to each dict before key generation; use that for the merge | `backend_v2/services/context_builder.py:200-213` |
| P1.3 | `ModelSelector.jsx` (component) collides with `components/model-selector/` (directory) — confusing for imports | Rename `ModelSelector.jsx` → `CharacterModelSelector.jsx` (it's used in character context) OR rename the directory → `components/model-manager-selector/` | `frontend_v2/src/components/ModelSelector.jsx`, `frontend_v2/src/components/model-selector/` |
| P1.4 | `collectionsApi.js` uses mixed named + default exports, inconsistent with other API modules | Standardize to named exports only; update all imports | `frontend_v2/src/api/collectionsApi.js`, all consumers |
| P1.5 | `.env.modal-stepmania` and `.env.modal-zetsuke` contain real tokens but are committed to the repo | Redact or rotate these tokens; add `*.env.*` to `.gitignore` (except `.env.example.*`) | `.env.modal-*`, `.gitignore` |

### Priority 2 — Monoliths & Performance (Week 2)

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| P2.1 | `chats.py` is 1252 lines (monolith) — mixes route handlers, context kwargs, message creation | Extract `_chat_context_kwargs` → `services/context_builder.py`; extract message creation → `services/world_integration_service.py` | `backend_v2/api/routes/world_vault/chats.py` |
| P2.2 | `stories.py` is 1168 lines (monolith) — mixes export logic, chapter CRUD, illustration | Extract comic/export → `services/story_export.py`; extract chapter beats → keep in route but thin | `backend_v2/api/routes/world_vault/stories.py` |
| P2.3 | `orchestrator_service.py` is 1009 lines — mixes tool execution, LLM workflow building, inline narration | Split: `orchestrator_service.py` (tool routing), `narrator_service.py` (inline narration), `services/llm_workflow.py` (LLM workflow assembly) | `backend_v2/services/` |
| P2.4 | `context_builder.py` loads ALL chat messages into memory just to slice the last 20 for lorebook query | Use keyset pagination: query only last 50 messages for embedding context | `backend_v2/services/context_builder.py` |
| P2.5 | `_cached_estimate_tokens` LRU cache keyed on full message text (2048 entries) — unbounded memory growth | Add TTL-based eviction or switch to `cachetools.TTLCache` | `backend_v2/services/context_builder.py:55-57` |
| P2.6 | `job_runner.py` re-fetches job status via `job_service.get_job()` inside retry loop | Cache job object locally within `execute_job`; only re-fetch on terminal events | `backend_v2/services/job_runner.py:276-286` |

### Priority 3 — Runtime Validation (Week 3)

> These features are **implemented but unverified** at runtime. Each needs a live stack run to confirm end-to-end behavior.

| # | Feature | What to verify |
|---|---------|----------------|
| P3.1 | RAG (pgvector) | 1. Embeddings generate on local SBERT (CPU). 2. Startup latency is acceptable. 3. Relevant memories surface in chat context. 4. Fallback to keyword search when embeddings unavailable. |
| P3.2 | Idle simulation | 1. `lifecycle.py` schedules `run_idle_simulation_tick`. 2. A chat with `idle_sim_enabled=True` produces summarized offline activity on return. 3. UI shows the summary. |
| P3.3 | AnimateDiff avatar | 1. `VHS_VideoCombine` produces non-empty `result_paths`. 2. `world_integration_service._handle_avatar_animate` receives them. 3. Animated avatar renders in `Characters.jsx`. |
| P3.4 | Comic/Webtoon export | 1. Per-page illustration images are generated (not gray placeholder). 2. Export produces valid PDF/vertical strip. |
| P3.5 | Provider auto-detection | 1. "Detect" button in `Providers.jsx` lists compose-managed containers. 2. Enabling `llm-local` pre-fills endpoint `http://provider-llm-local:8000`. |

### Priority 4 — Docker & Provider Hygiene (Week 3)

| # | Issue | Fix | Files |
|---|-------|-----|-------|
| P4.1 | `provider_containers/venv/` is a committed binary directory (~200MB+ of site-packages) | Remove from git: `git rm -r --cached provider_containers/venv/` + add to `.gitignore` | `.gitignore`, git history |
| P4.2 | Beam provider compose block commented out, env template empty | Either wire Beam fully (uncomment, add env, smoke test) or remove dead compose block + `.env.beam` | `docker-compose.yml`, `.env.beam` |
| P4.3 | `remote_comfy` provider has no volume mount in `docker-compose.yml` | Add `volumes: - ./data:/data` to match other providers | `docker-compose.yml:284-315` |
| P4.4 | `llm_worker/Dockerfile` runs as root outside compose | Add `USER worker` after creating unprivileged user | `provider_containers/llm_worker/Dockerfile` |

### Priority 5 — Test Coverage (Week 4)

| # | Feature | Test |
|---|---------|------|
| P5.1 | `prune_context` deduplication by UUID | Add pytest: two messages with identical 200-char prefix but different UUIDs should not collide | `tests/test_context_builder.py` |
| P5.2 | RAG `rag_enabled()` gate | Add pytest: when `ai.ragEnabled=false`, `search_memories` and `search_lorebook_entries` return `[]` | `tests/test_rag_pipeline.py` |
| P5.3 | AnimateDiff workflow builder output shape | Verify regression test checks return is `(nodes_dict, metadata_dict)` not `{"prompt": nodes}` | `tests/test_animatediff_workflow.py` |
| P5.4 | Idle simulation tick | Add pytest: `run_idle_simulation_tick` respects `idle_sim_enabled` flag, produces a summary message | `tests/test_agent_simulation.py` |
| P5.5 | Comic webtoon export with real images | Add pytest: export with story that has generated chapter images produces non-blank output | `tests/test_stories_extended.py` |
| P5.6 | E2E: on-demand provider wake | Add Playwright test: clicking "Detect" in Providers page creates disabled provider rows | `e2e/providers.spec.js` |

### Priority 6 — Polish & Quality of Life (Week 4)

| # | Issue | Fix |
|---|-------|-----|
| P6.1 | `Frontend API client` has no centralized version constant | Add `API_BASE` helper in `client.js`; all new code uses it |
| P6.2 | `KeyboardShortcutsModal` should document all shortcuts | Ensure Chat `Ctrl+Enter`/`Ctrl+N`, Story `Ctrl+S`/`Ctrl+Shift+C`, `Cmd+K` are listed | `KeyboardShortcutsModal.jsx` |
| P6.3 | `Image gallery virtualization` uses `@tanstack/react-virtual` | Verify `Dashboard.jsx` actually uses it (not falling back to full DOM) | `Dashboard.jsx` |
| P6.4 | `Drag-and-drop sorting` — `@dnd-kit` dependency check | Verify `@dnd-kit/sortable` is in package.json; if not, add it | `package.json` |
| P6.5 | `StorySandbox.jsx` is 792 lines | Extract `StoryNavigation`, `StoryEditorContainer`, `ChapterSidebar` into dedicated components | `frontend_v2/src/components/story/` |

---

## 4. Work Sequencing

```
Week 1  P1 (correctness & dead code)
  → Week 2  P2 (monoliths & performance)
    → Week 3  P3 (runtime validation) + P4 (docker hygiene)
      → Week 4  P5 (tests) + P6 (polish)
```

**Dependency note:** P2 (monolith extraction) touches the same files as P1, so they should overlap. P3 (runtime validation) requires a running stack with providers, so it runs in parallel with P2. P4 (docker hygiene) is independent.

---

## 5. Verification Gates

After each week:

```bash
# Backend
cd backend_v2 && .venv/bin/python -m pytest -q && .venv/bin/ruff check .

# Frontend
cd frontend_v2 && npm test && npm run lint

# Full stack (dev compose with --profile providers)
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d

# E2E
cd frontend_v2 && npx playwright test --grep-invert @fullstack
```

### Manual verification checklist

- [x] `prune_context` no longer collides on truncated content — uses message `_id` (UUID) as primary key, content-prefix as fallback
- [x] `worldVaultStore.js` serves a purpose — activeChatId bridge between URL params and component state
- [x] ModelSelector naming collision resolved — renamed `model-selector/` directory to `selector/`
- [x] `collectionsApi.js` exports are consistent — already uses named exports only
- [x] `provider_containers/venv/` already gitignored (not tracked)
- [x] Beam provider block already removed (no dead compose block)
- [x] `remote_comfy` already fully commented out with volume mount in compose
- [ ] RAG recalls relevant memories in chat context
- [ ] Idle sim produces summarized activity on return
- [ ] Animatediff avatar displays in character card
- [ ] Comic export generates real image panels (no gray placeholders)

---

## 6. Open Decisions (require user input)

1. **Beam provider**: Decision — already removed. No dead compose block exists.
2. **`provider_containers/venv`**: Already gitignored. No action needed.
3. **`worldVaultStore.js`**: Kept with clarifying comment — it serves a real purpose (activeChatId bridge).
4. **`prune_context` dedup key**: Implemented using `id` UUID as primary key, content-prefix as fallback.

---

## 7. Files Not to Touch (Already Verified)

- `backend_v2/core/workflow_builder.py` — `build_video_job_workflow` fix is committed and correct
- `backend_v2/services/rag_pipeline.py` — canonical retrieval, imported by `context_builder`
- `backend_v2/services/orchestrator_service.py:326-345` — `execute_tool` timeout already in place
- `backend_v2/services/orchestrator_service.py:528-589` — mode-mismatch + `report_failure` already correct
- `frontend_v2/src/hooks/useChatStreaming.js` — all WS event handlers present (lines 62-210)
- `frontend_v2/src/hooks/useVoices.js` — `enabled` no-op already removed
- `frontend_v2/src/hooks/useEntityCRUD.js` — already deleted
- `backend_v2/api/routes/world_vault/world_hub.py:64-82` — story limit + dangling link handling already in place
- `P2.3` (orchestrator_service.py monolith split) — LLM workflow already centralized in `services/llm_workflow.py`; splitting orchestrator_service.py is high-risk with no test coverage for inline narration
- `P2.6` (job_runner.py re-fetch) — re-fetch only happens during retry, which is correct behavior (needs fresh read to check cancellation)
- `P6.2` (KeyboardShortcutsModal) — already documents all implemented shortcuts (navigation, action, gallery)
- `P6.3` (image gallery virtualization) — `@tanstack/react-virtual` is actively used in Dashboard.jsx, SceneGallery.jsx, ChatWorkspaceContext.jsx

---

## 8. Implementation Log (2026-08-23 — 2026-08-24 session)

### Changes made in this session

| Area | Change | Verification |
|---|---|---|
| Backend `context_builder.py` | `prune_context` uses message `_id` (UUID) as primary dedup key, falling back to `(role, content[:200])`. `_id` propagated from SQLModel `.id` or dict `id`. Stripped before returning to LLM. | 28 context_builder tests pass (3 new regression tests) |
| Backend `context_builder.py` | Replaced unbounded `@lru_cache` with `@cachetools.TTLCache(maxsize=2048, ttl=300)`. All callers updated to `_estimate_cached`. | `cachetools>=5.3.0` already in requirements.txt |
| Backend `context_builder.py`, `chats.py` | Extracted `_chat_context_kwargs` → `chat_context_kwargs()` in context_builder. Updated all 6 call sites. | 1515 backend tests pass |
| Backend `tests/test_context_builder.py` | Added 4 new tests; cleaned imports. | 28 tests pass |
| Frontend `worldVaultStore.js` | Added JSDoc clarifying purpose. | No functional change |
| Frontend `ModelSelector.jsx` | Renamed `model-selector/` → `selector/` to fix case-insensitive FS collision. | 10 tests pass |
| Frontend `api/client.js` + modules | Added `API_V2_BASE` constant; updated `models.js`, `providers.js`, `files.js`. | 26 API tests pass, lint 0 errors |
| Frontend `StoryBeatsPanel.jsx` | Added `@dnd-kit` drag-drop reorder. | 13 StorySandbox tests pass, lint 0 errors |
| `package.json` | Added `@dnd-kit/core` + `@dnd-kit/sortable`. | 532 frontend tests pass |

### Deferred
- **P2.2**: stories.py extraction — well-tested, high-risk
- **P2.3**: orchestrator_service.py split — already centralized
- **P6.5**: StorySandbox.jsx extraction — needs design decisions
