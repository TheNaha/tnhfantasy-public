# TNHComfy Codebase Hardening & Feature Completion Plan

## Context
TNHComfy is evolving from an image-generation wrapper into a Comprehensive AI Fantasy Engine (Image Gen + Roleplay Chat + Story Sandbox). The new pillars are implemented but feel "demo-like" — functional skeletons missing production-grade features, test coverage, and integration polish. This plan addresses bugs, gaps, duplication, and missing features to make the app usable for casual and power users.

---

## 1. Stabilize Current Deltas (Uncommitted Changes)

The working tree contains ~18 modified files that fix real bugs but need validation before merge.

| File | Issue | Action |
|------|-------|--------|
| `backend_v2/api/routes/world_vault/chats.py` | Top-level imports added; inline imports removed. Risk: circular imports or unused imports. | Run `python3 -c "import backend_v2.api.routes.world_vault.chats"` to verify clean import. |
| `backend_v2/api/routes/world_vault/stories.py` | Batch-loads characters/lorebooks (2 queries instead of 2N). Good fix. | Add route tests for the new batch paths (see §4). |
| `backend_v2/services/context_builder.py` | `lru_cache` on `_load_encoding`; `get_tokenizer` simplified. | Verify tiktoken cache hit rate in tests. |
| `backend_v2/services/world_integration_service.py` | `_handle_story_parse` now links entities to story; `_handle_impersonation` passes `characters=[...]`. | Add tests for story-parse linking and impersonation with multiple chars. |
| `backend_v2/services/orchestrator_service.py` | Removed `_available_checkpoint/_available_lora` helpers; uses `ModelAvailabilityService` directly. | Verify no other modules import the removed helpers (`grep -r "_available_checkpoint"`). |
| `backend_v2/services/model_availability_service.py` | New `resolve_checkpoint()` consolidates fallback chain. | Update remaining callers (e.g. `image_submission.py` inline fallback) to use it. |
| `backend_v2/services/image_submission.py` | New `submit_image_job()` helper. Good consolidation. | Replace any remaining inline `build_image_job_workflow + create_job + enqueue` patterns. |
| `frontend_v2/src/hooks/useChats.js` | Optimistic update for `useSendMessage`. | Verify temp-IDs don't collide with real IDs on refetch. |
| `frontend_v2/src/hooks/useMessages.js` | Optimistic updates for edit/delete. | Add rollback on error for edit (currently only delete has `onError`). |
| `frontend_v2/src/hooks/useStories.js` | Optimistic updates for `useContinueChapter` and `useAddStoryBeat`. | Ensure `_isStreaming` flag is cleared on both success and error. |
| `frontend_v2/src/pages/ChatWorkspace.jsx` | Uses `useDeleteMessage`; added `aria-label`s. | Audit for missing keyboard shortcuts on new buttons. |
| `frontend_v2/src/pages/StorySandbox.jsx` | Removed manual frontend story-parse entity creation. | Verify backend `_handle_story_parse` correctly links all entity types. |

**Validation step:** Spin up containers (`docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d`), run Playwright `npm test` (frontend passes), and run backend pytest via `.venv/bin/pytest`.

---

## 2. Bug Fixes

### 2.1 Backend
- **`job_processing.py:_finalize_llm_job`**: The `is_scene_prompt` branch returns `finalize_persisted_job_outputs` with `outputs=outputs` (the original image outputs list), but the event_extra contains a text prompt. This can cause duplicate image processing. Fix: pass `outputs=[]` so only the chained text event is emitted.
- **`orchestrator_service.py:_tool_generate_image`**: `lora_name` is referenced before assignment when `source_job_id` is None and `character_id` is None. Initialize `lora_name = None` at the top.
- **`world_integration_service.py:_handle_chat_reply`**: Swipe alternates logic mutates `target_msg.content` directly, which can lose the original text if the swipe is rejected. Store original in `alternates[0]` before overwriting.
- **`context_builder.py:build_system_prompt_sections`**: Loads *all* lorebook entries for every lorebook_id before semantic/keyword filtering. For lorebooks with >500 entries this is a N+1-style perf hit. Fix: push the `LorebookEntry.lorebook_id.in_(lorebook_ids)` query into the `except` fallback only; in the happy path use pgvector top-K + keyword scan with a pre-filtered subquery.

### 2.2 Frontend
- **`useMessages.js:useEditMessage`**: `onError` does not rollback optimistic update (only `onMutate` saves `previous`). Add `onError` rollback mirroring `useDeleteMessage`.
- **`StorySandbox.jsx`**: `streamingRef` is set but `streamSafetyTimerRef` is declared yet never started in a `useEffect`. Add a safety timer that clears `_isStreaming` after 180s.
- **`ChatWorkspace.jsx`**: `handleSendMessage` optimistic temp-IDs use `Date.now()` — if the user sends two messages within the same millisecond, IDs collide. Use `crypto.randomUUID()` or a monotonic counter.

---

## 3. Missing Features (Closing the "Demo" Gap)

Priority order: features that unblock daily usage first.

### 3.1 Chat Workspace
- **Group chats / multi-character**: `Chat` entity has `character_id` (singular). Add `character_ids: list[str]` column + `character_settings: dict` for per-character overrides. Update `build_chat_context_async` to accept `characters=[...]` and merge their system prompts. Frontend: allow adding multiple characters to a chat.
- **Chat search**: Add `GET /api/v2/chats?q=...` full-text search on `Chat.name` and `Message.content`. Frontend: search bar in chat list.
- **Chat export**: `POST /api/v2/chats/:id/export` returning JSON/Markdown of messages. Frontend: export button in chat header.
- **Pin/unpin messages**: Backend already supports `pinned` bool and `_pinned` in context. Expose pin/unpin endpoints (`PATCH /messages/:id/pin`). Frontend: pin icon on messages.

### 3.2 Story Sandbox
- **Chapter reorder**: Add `PATCH /api/v2/stories/:storyId/chapters/reorder` with `chapter_ids: [...]`. Frontend: drag-and-drop in chapter sidebar.
- **Word count / reading time**: Compute in `StoryEditor.jsx` and show in header.
- **Story export**: `POST /api/v2/stories/:id/export` (Markdown + plain text). Frontend: export button.
- **Beat branching UI**: Beats exist in backend but frontend branching is limited. Add a "Fork from here" button on each beat in `StoryBeatsPanel`.

### 3.3 Characters
- **Character gallery**: List all images in a character's collection. Add `GET /api/v2/characters/:id/images`.
- **Bulk import/export**: Support ZIP of character cards + avatars.
- **Character relationships**: Add `related_character_ids: list[str]` to `Character`. Frontend: relationship picker in character modal.

### 3.4 World Vault
- **Global search**: `GET /api/v2/search?q=...` across characters, lorebooks, stories, chats.
- **Batch delete**: `POST /api/v2/batch/delete` accepting mixed entity types.
- **Tags/categories**: Add `tags: list[str]` to `Story`, `Character`, `Lorebook`. Frontend: tag filter pills.

---

## 4. Test Coverage Gaps

### 4.1 Backend (pytest)
Add or expand tests in `backend_v2/tests/`:

| Missing Test | File to Create/Update | Key Scenarios |
|-------------|----------------------|---------------|
| Story routes (CRUD + chapters + beats + branch + continue + illustrate) | `test_stories_routes.py` | Create story → add chapter → continue → branch → add beat → illustrate → parse |
| Lorebook routes (CRUD + search + embedding) | `test_lorebooks_routes.py` | Create lorebook + entries → semantic search → keyword fallback |
| Character routes (CRUD + avatar + card import/export) | `test_characters_routes.py` | Create → patch → upload avatar → import PNG/JSON card → export |
| Scenario routes | `test_scenarios_routes.py` | CRUD + assign to chat/story |
| `ModelAvailabilityService.resolve_checkpoint` chain | `test_model_availability_service.py` | Preferred available → preferred missing fallback → config default → hard fallback |
| `image_submission.submit_image_job` | `test_image_submission.py` | Enqueue + metadata correctness |
| `context_builder.build_system_prompt_sections` with multiple characters | `test_context_builder.py` | Multi-character system prompt assembly + tavern var substitution |

### 4.2 Frontend (Vitest)
Add unit tests for hooks currently lacking coverage:
- `useMessages.test.js` (edit/delete optimistic rollback)
- `useStories.test.js` (continue/beat optimistic + streaming flag cleanup)
- `useChats.test.js` (send optimistic + collision handling)
- `useCharacters.test.js` (CRUD + avatar)
- `useLorebooks.test.js` (CRUD + search)

### 4.3 E2E (Playwright)
New specs:
- `lorebook-crud.spec.js`: create/edit/delete lorebook + entries + semantic search
- `story-branching.spec.js`: create story → chapter → beat → fork → continue both branches
- `character-relationships.spec.js`: create characters → link → verify context injection
- `chat-export.spec.js`: export chat → verify JSON structure
- `group-chat.spec.js`: create chat with 2 characters → send message → verify both char prompts

---

## 5. Code Consolidation & Deduplication

| Duplicate Pattern | Current State | Target |
|-------------------|---------------|--------|
| Checkpoint resolution | `chats.py`, `stories.py`, `orchestrator_service.py`, `image_submission.py` each resolve fallback | All callers use `ModelAvailabilityService.resolve_checkpoint()` |
| Lorebook/character batch loading | `stories.py` fixed; `context_builder.py` still loads all entries | `build_system_prompt_sections` should accept pre-fetched entries or use top-K queries |
| Image job creation | `chats.py:generate_scene`, `chats.py:illustrate_chat`, `stories.py:illustrate_chapter`, `orchestrator_service.py:_tool_generate_image` | All route handlers call `submit_image_job()` |
| LLM workflow building | `llm_workflow.py` exists but some routes still inline-build dicts | Enforce `build_llm_workflow` / `build_chat_llm_workflow` as the only construction path |
| System prompt blocks | `orchestrator_service.py:NARRATOR_SYSTEM_PROMPT` hardcoded; also in `config.py` blocks | Single source: `config.py` `system_prompt_blocks.narrator` |

---

## 6. Performance Improvements

- **Token estimation cache**: `estimate_tokens()` calls `get_tokenizer().encode()` on every message in `prune_context`. Cache results per-text-hash in `context_builder.py` (LRU cache on `estimate_tokens`).
- **Lorebook query**: In `build_system_prompt_sections`, replace `select(LorebookEntry).where(LorebookEntry.lorebook_id.in_(lorebook_ids))` with a single query + in-memory groupby (already done in `stories.py` diff). Apply the same pattern to `context_builder.py`.
- **Chat list pagination**: `list_chats` loads 50 rows with no count. Add `?limit=&offset=` + `X-Total-Count` header.
- **Story chapter content**: `chapter.content` is concatenated plain text; loading a chapter with 50k words blocks the response. Return content lazily or paginate beats.

---

## 7. Integration Gaps

| Gap | Description | Fix |
|-----|-------------|-----|
| Story parse → World Vault sync | Backend creates entities but frontend `worldVaultStore` is not invalidated for characters/lorebooks lists | Emit `EventType.STORY_PARSED` with entity IDs; frontend WebSocket handler invalidates specific queries |
| Agentic image → collection | `_handle_chat_image` adds to `Collection` if one exists for the character, but `submit_image_job` doesn't set `character_id` consistently | Ensure `submit_image_job` always receives `character_id` from parent job metadata |
| LLM streaming → chat | `useLLMJobResult` polls for completion; streaming via WebSocket exists but isn't used for LLM text chunks | Route LLM provider streaming through Socket.IO to `useLLMJobResult` for real-time token rendering |
| Narration → chat | Narrator inserts a SYSTEM message but `ChatWorkspace` may not render it distinctly | Ensure `MessageKind.NARRATOR` renders with a distinct visual style (already has icon, verify CSS) |

---

## 8. Rollout & Validation

1. **Commit current deltas** after running:
   ```bash
   cd backend_v2 && .venv/bin/pytest -q
   cd frontend_v2 && npm test -- --run && npm run lint
   ```
2. **Implement §2 bug fixes** in a single follow-up commit.
3. **Add §4 tests** in batches (backend first, then frontend, then e2e).
4. **Implement §3 features** by pillar: Chat Workspace → Story Sandbox → Characters → World Vault.
5. **Apply §5 consolidation** as a refactor pass after feature work stabilizes.
6. **Validate in Docker**:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d
   npx playwright test
   ```

---

## Open Decisions

1. **Multi-character chat model**: Should `character_ids` replace `character_id` or coexist during migration? **Recommendation**: Add `character_ids`, keep `character_id` as primary for backward compatibility, deprecate after 1 release.
2. **Search implementation**: Use PostgreSQL `tsvector` or pgvector hybrid search? **Recommendation**: pgvector for lorebook entries (already embedded), `tsvector` for character/story names.
3. **Export format**: Markdown only, or also JSON/HTML? **Recommendation**: JSON (full fidelity) + Markdown (human readable).
