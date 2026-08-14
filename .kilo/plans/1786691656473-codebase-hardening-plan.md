# TNHComfy Codebase Hardening & Expansion Plan

## Goal
Refine existing systems, fix bugs, remove duplication, improve test coverage, and strengthen cross-pillar integration so the project reliably delivers the "AI Fantasy Engine" vision (Image Gen + Roleplay + Story Sandbox + World Vault).

---

## 1. Playwright E2E Test Coverage Expansion

### Problem
- Only **6 `@fullstack` tests** exist, all in `image-generation.spec.js`.
- Zero `@fullstack` tests for roleplay chat, story sandbox, agentic workflows, or cross-pillar flows.
- Test helpers (`selectModelFromDialog`, `pickSingleVersionModel`, `listModels`) are **duplicated** between `image-generation.spec.js` and `advanced-generation.spec.js`.

### Action
1. **Extract shared E2E helpers** into `e2e/helpers/` (model picker, image upload, job waiter).
2. **Add `@fullstack` tests**:
   - `roleplay.spec.js`: real LLM reply, agentic mode + `generate_image` tool, character with `visual_tags`/`lora_triggers`.
   - `story-sandbox.spec.js`: real `story_continue`, `illustrate`, branch-and-retry.
   - `world-vault.spec.js`: lorebook semantic search affecting LLM context, character CRUD with chat linkage.
   - `cross-pillar.spec.js`: asset created in chat appears in story gallery and vice versa.
3. **Add error-path tests**: provider down, no checkpoint installed, LLM timeout, agentic depth exceeded.
4. **Add mobile-responsive tests** for `/chat` and `/story` routes (only `/gallery` is covered today).

### Validation
- `cd frontend_v2 && npm run test:e2e:fullstack` passes on Docker stack.
- CI: new `.github/workflows/playwright-tests.yml` runs suite on push to `main`/`master` when `frontend_v2/e2e/**` or compose files change.

---

## 2. Session Management Hygiene

### Problem
Services manually call `get_session_sync()` and `session.close()` in 25+ places (`orchestrator_service.py`, `job_processing.py`, `provider_runtime.py`, `world_integration_service.py`). This is error-prone and bypasses the DI pattern mandated in `AGENTS.md`.

### Action
1. **Audit** all manual session creation in `backend_v2/services/`.
2. **Refactor** `orchestrator_service.py` tool functions (`_tool_narrate_scene`, `_tool_generate_image`, `_tool_update_world_state`) to accept an injected `Session` or use `get_session_context()` consistently.
3. **Refactor** `job_processing.py` `finalize_persisted_job_outputs` to use `get_session_context()` instead of `get_session_sync()`.
4. **Refactor** `provider_runtime.py` `monitor_provider_changes` to use `get_session_context()` + `asyncio.to_thread` only for blocking DB calls, not session creation.

### Validation
- `pytest tests` passes.
- No remaining `session.close()` calls in service layer (only in infrastructure/database).

---

## 3. Bug Fixes

### 3.1 Write-in-GET: `_ensure_beat_ids` commits inside a read endpoint
**File**: `backend_v2/api/routes/world_vault/stories.py:64-88`
**Risk**: Race condition when two requests read the same chapter; second commit overwrites first.
**Fix**: Move beat-ID backfill to a **migration step** or a **lazy write on update** (only backfill when chapter is saved).

### 3.2 Narrator inline execution leaves orphan job row on failure
**File**: `backend_v2/services/orchestrator_service.py:380-456`
**Risk**: Job row created with `status=PENDING`; if inline `call_llm_provider` fails, row stays `PENDING` forever.
**Fix**: On inline failure, update job status to `FAILED` with error detail (already partially done); ensure `release_job` is called in a `finally` block.

### 3.3 Tavern vars fallback uses `chat.name` when `persona_name` is empty
**File**: `backend_v2/api/routes/world_vault/chats.py:99-103`
**Risk**: `chat.name` defaults to `"New Chat"` — injected into prompts as the user's persona.
**Fix**: Only fall back to `"User"`; never inject the chat title as a persona name.

### 3.4 `worldVaultStore.js` is effectively dead code
**File**: `frontend_v2/src/store/worldVaultStore.js`
**Risk**: Only stores `activeChatId`; URL params already drive navigation. Misleads contributors into thinking global chat state lives here.
**Fix**: Either remove the store and rely on URL + React Query, or expand it to hold the **active story ID** and **active character ID** for cross-page navigation (e.g., clicking a character from a chat context panel).

---

## 4. Code Deduplication

### 4.1 GeneratorShell consolidation (deferred in VISION.md, but surface the duplication)
- `SimpleGenerator`, `Img2ImgGenerator`, `InpaintGenerator` share **70% identical shell** (sidebar, model picker, progress bar).
- **Action**: Extract a `useGeneratorShell` hook + shared `<GeneratorShell>` component. Keep only the variant-specific upload/preview logic in each page.

### 4.2 React Query hook families
- `useChats.js` and `useStories.js` share identical CRUD mutation patterns.
- **Action**: Extract a `useWorldVaultResource` factory hook: `useWorldVaultResource('chats', '/api/v2/chats')`.

### 4.3 Workflow builder call sites
- `build_image_job_workflow` is imported in 4 files (`chats.py`, `stories.py`, `world_integration_service.py`, `orchestrator_service.py`).
- **Action**: Add a thin `services/image_submission.py` helper that wraps checkpoint resolution + workflow building + job creation + enqueue, so callers don't repeat the same 20 lines.

---

## 5. Integration & Missing Implementations

### 5.1 Character visual-tag → image generation pipeline
**Current state**: Character card stores `visual_tags` and `lora_triggers`, but `_tool_generate_image` only resolves checkpoint + LoRA by name. It never injects `visual_tags` into the prompt.
**Fix**: Append `visual_tags` to the agentic `prompt` in `_tool_generate_image` (e.g., `"a wizard casting a spell, 1boy, male focus, glowing staff"`).

### 5.2 Story `character_ids`/`lorebook_ids` → context builder
**Current state**: `Story` entity stores `character_ids` and `lorebook_ids`, but `build_system_prompt_sections` only receives them when called from chat paths.
**Fix**: Ensure `story_continue` and `story_illustrate` flows pass `story_character_ids` and `lorebook_ids` into the LLM context builder.

### 5.3 Asset cross-pollination UI
**Current state**: Assets are tagged with `workspace` + `character_id` + `story_id`, but the frontend has no "Move to workspace" action.
**Fix**: Add a context-menu action on gallery images: "Add to collection / Move to workspace". Backend endpoint: `POST /api/v2/assets/{id}/move`.

### 5.4 Character card import/export (V2/V3 PNG + Tavern JSON)
**Current state**: Character CRUD exists, but import/export of PNG character cards (with embedded metadata) is not implemented.
**Fix**: Implement PNG chunk parsing + JSON export in `backend_v2/services/character_service.py` (or a new `character_io.py`).

---

## 6. Performance Improvements

### 6.1 SBERT embedding offload
**File**: `backend_v2/services/context_builder.py:349`
**Current**: `_svc.generate_embedding()` runs inside `build_system_prompt_sections_async`, which already uses `asyncio.to_thread`. Verify all callers use the async variant.
**Fix**: Grep for `build_system_prompt_sections(` (non-async) and replace with `build_system_prompt_sections_async` in all route handlers.

### 6.2 Beat-ID backfill N+1
**File**: `backend_v2/api/routes/world_vault/stories.py:153-158`
**Current**: `_ensure_beat_ids` is called for every chapter in list + get.
**Fix**: Remove from `list_chapters`; only backfill on `get_chapter` or `update_chapter`.

### 6.3 Gallery pagination
**File**: `backend_v2/services/asset_reconciler.py`
**Current**: `_query_gallery_files` uses keyset pagination, but the frontend `SceneGallery` fetches all pages at once.
**Fix**: Implement cursor-based infinite scroll in frontend; limit to 50 assets per request.

---

## 7. Frontend Cleanup

### 7.1 Remove dead store or expand it
**File**: `frontend_v2/src/store/worldVaultStore.js`
**Action**: Expand to track `activeStoryId` and `activeCharacterId` so cross-page navigation (e.g., "View character" from chat) works without URL parsing hacks.

### 7.2 Shared `clsx` utility
**File**: `frontend_v2/src/pages/FantasyHub.jsx:130-132`
**Action**: Move `clsx` to `src/utils/clsx.js` and import it everywhere.

### 7.3 QueryClient stability
**File**: `frontend_v2/src/App.jsx:147-169`
**Current**: `useEffect` updates QueryClient defaults on every settings change, which can cause cache flushes.
**Fix**: Only update `staleTime` and `gcTime` when they actually change; compare before calling `setDefaultOptions`.

---

## 8. CI/CD: Add Playwright Workflow

### Problem
- `.github/workflows/` has `backend-tests.yml`, `frontend-tests.yml`, and `provider-tests.yml`, but **no Playwright workflow**.
- The latest session digest mentions `.github/workflows/playwright-tests.yml` was added, but it does not exist in the repo.

### Action
1. **Create** `.github/workflows/playwright-tests.yml`:
   - Triggers on push/PR to `main`/`master` when `frontend_v2/e2e/**`, `frontend_v2/Dockerfile`, or `docker-compose*.yml` change.
   - Spins up the full Docker stack (`docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d`).
   - Runs `npm run test:e2e:ui` (skips real generations by default) and `npm run test:e2e:fullstack` as a separate manual/job matrix step.
2. **Cache** Playwright browsers and npm dependencies.
3. **Export** artifacts on failure (`playwright-report/`, `test-results/`).

### Validation
- Workflow appears in GitHub Actions tab.
- `frontend-tests.yml` still passes unit tests; Playwright workflow only runs on relevant path changes.

---

## 9. Rollout Order & Dependencies

| Phase | Tasks | Risk |
|-------|-------|------|
| **1. Safety** | Fix bugs 3.1, 3.2, 3.3, 3.4 | Low — isolated patches |
| **2. Hygiene** | Session audit + refactor (Task 2) | Medium — touch many service files; run full pytest |
| **3. Dedup** | Extract E2E helpers, GeneratorShell, hook factory (Tasks 4.1, 4.2, 4.3) | Medium — refactor shared boundaries |
| **4. Tests** | Add E2E coverage + CI workflow (Task 1 + 8) | Medium — requires Docker stack running |
| **5. Integration** | Character visual-tags, story context, asset move, character I/O (Task 5) | Medium — new endpoints + frontend wiring |
| **6. Perf** | SBERT offload, beat backfill, gallery pagination (Task 6) | Low — mostly code moves |
| **7. Cleanup** | Frontend store expansion, clsx, QueryClient (Task 7) | Low — UI-only |

### Validation Gates
- **After Phase 1**: `pytest tests` passes, no new ruff errors.
- **After Phase 2**: `pytest tests` passes, zero `session.close()` in `backend_v2/services/`.
- **After Phase 3**: `npm run lint` passes, no duplicated helper blocks >10 lines.
- **After Phase 4**: `npm run test:e2e:ui` passes locally; Playwright workflow green in CI.
- **After Phase 5**: Manual smoke test: create character → chat → agentic illustrate → image appears in character gallery.
- **After Phase 6**: Gallery load time < 500ms for 500 assets (measured via React DevTools profiler).
- **After Phase 7**: `npm run lint` passes, `worldVaultStore` has >1 key or is removed.

---

## 10. Open Questions for User

1. **Playwright runner**: Should the new workflow run on every push to `main`/`master`, or only on PRs? (Recommended: PRs + manual dispatch for full-stack runs, since `@fullstack` tests bill provider credits.)

2. **Character card I/O format**: Do you want V2 PNG spec only, or also Tavern JSON import/export? (Recommended: V2 PNG first, JSON as a stretch goal.)

3. **Asset cross-pollination scope**: Should "Move to workspace" support copying (duplicate) or only moving (transfer ownership)? (Recommended: copy, so the original isn't lost.)

4. **GeneratorShell refactor**: The VISION.md defers this, but the duplication is real. Should we do a minimal extraction now, or mark it explicitly post-v2.0? (Recommended: minimal extraction now, since it unblocks cleaner variant pages.)

5. **Session refactor approach**: Should we batch the session changes into one PR, or file one PR per service file? (Recommended: one PR per service file for easier review, since the changes are mechanical.)
