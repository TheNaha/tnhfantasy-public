# TNHFantasy Codebase Hardening & Feature-Completion Plan

## Executive Summary

The codebase is functionally close to the expanded vision (Image Gen + Roleplay + Story Sandbox + World Vault), but the recent multi-character refactor left **build-breaking frontend errors**, **runtime backend crashes**, **missing endpoints**, and **significant code duplication**. The frontend cannot compile, and several backend endpoints are broken or incomplete. This plan fixes those defects first, then pays down technical debt to make the three pillars production-ready.

---

## Phase 1: Emergency Fixes (Unblock Build & Runtime)

### 1.1 Fix frontend build-breaking lint errors

| File | Issue | Fix |
|------|-------|-----|
| `frontend_v2/src/components/chat/MessageItem.jsx` | Duplicate declarations of `meta`, `alternates`, `activeIndex`, `altCount` (lines 16–19 and 24–28) | Remove the first dead block (lines 16–19) |
| `frontend_v2/src/pages/ChatWorkspace.jsx` | Duplicate `handleIllustrate` (lines 605 and 843) | Delete the first definition (line 605) and keep the `useCallback` version |
| `frontend_v2/src/components/story/StoryContextPanel.jsx` | `Edit2` not imported; `onEditCharacter` prop not declared | Import `Edit2` from `lucide-react`; add `onEditCharacter` to component props |

**Validation:** `cd frontend_v2 && npm run lint` must pass with 0 errors.

### 1.2 Fix backend runtime crashes in `chats.py`

| Endpoint | Issue | Fix |
|----------|-------|-----|
| `impersonate` (line 806) | References undefined `character` after multi-char refactor | Use `characters[0]` if available, else fallback to `"the AI"` |
| `suggest_reply` (line 887–902) | Not migrated to `characters` plural; ignores `additional_character_ids` | Load both `character_id` and `additional_character_ids` into `characters` list, pass to `_chat_context_kwargs` |
| `generate_scene` (line 1007) | Same — still uses singular `character` | Migrate to plural `characters` pattern |

**Validation:** Start backend, hit each endpoint with a test chat; confirm no 500s.

### 1.3 Add missing backend endpoints

| Missing Route | Frontend Caller | Required Action |
|---------------|-----------------|-----------------|
| `POST /api/v2/chats/{chat_id}/messages/{message_id}/tts` | `ChatWorkspace.jsx:832` | Add route handler that creates an LLM job with `type="chat_tts"` and routes through the LLM worker |
| `target_character_id` field | `ChatWorkspace.jsx:521` | Add to `SendMessageRequest`; persist to `Message.message_metadata` so the UI can track who "spoke" in group chats |

---

## Phase 2: Eliminate Duplication & N+1 Queries

### 2.1 Consolidate character loading in `chats.py`

Extract a single helper:

```python
def _load_chat_characters(session, chat):
    characters = []
    if chat.character_id:
        c = session.get(Character, chat.character_id)
        if c: characters.append(c)
    if chat.additional_character_ids:
        ids = [cid for cid in chat.additional_character_ids if cid not in {ch.id for ch in characters}]
        if ids:
            chars = session.exec(select(Character).where(Character.id.in_(ids))).all()
            characters.extend(chars)
    return characters
```

Replace all 7 inline character-loading blocks.

### 2.2 Consolidate message fetching

Extract:

```python
def _load_chat_messages(session, chat_id, limit=None):
    stmt = select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    if limit: stmt = stmt.limit(limit)
    return session.exec(stmt).all()
```

Replace all inline `select(Message).where(Message.chat_id == chat_id)` blocks.

### 2.3 Optimize `regenerate_reply`

Current code scans 200 recent LLM jobs to find the previous agentic flag. Replace with a targeted query:

```python
prev_job = session.exec(
    select(Job)
    .where(Job.metadata_["chat_id"].as_string() == chat_id)
    .where(Job.task_type == "llm")
    .order_by(Job.created_at.desc())
    .limit(1)
).first()
```

---

## Phase 3: Frontend State & Integration Gaps

### 3.1 Wire `target_character_id` through the backend

- Add `target_character_id: str | None = None` to `SendMessageRequest`.
- In `add_message`, when inserting the user `Message`, store `target_character_id` in `message_metadata`.
- In `build_chat_context`, use `target_character_id` to resolve which character's voice/style to prioritize in the system prompt.

### 3.2 Complete TTS integration

- Backend: add `POST /{chat_id}/messages/{message_id}/tts` that enqueues an LLM job with a TTS-oriented system prompt and returns `{job_id}`.
- Frontend: the `handleGenerateTTS` handler already exists; after this endpoint is added, wire it to the same `useStreamingJobs` pattern as `handleGenerateSwipe`.

### 3.3 Fix story-parse flow

`StorySandbox.jsx:155–159` does:
```js
await updateChapter.mutateAsync({
    storyId: newStory.id,
    chapterId: newStory.chapters?.[0]?.id || '1',
    updates: { content: text }
});
```
The `'1'` fallback is wrong (chapter IDs are UUIDs). Fix:
```js
const firstChapterId = newStory.chapters?.[0]?.id;
if (firstChapterId) {
    await updateChapter.mutateAsync({ storyId: newStory.id, chapterId: firstChapterId, updates: { content: text } });
}
```

### 3.4 Clean up `MessageItem.jsx` dead prop

`onIllustrate` is passed to `MessageItem` but never used inside the component. Remove it from the prop list and from `ChatWorkspace.jsx` render call to avoid confusion.

---

## Phase 4: Testing & CI

### 4.1 Fix backend test environment

`backend_v2/tests/conftest.py` fails with `ModuleNotFoundError: No module named 'fastapi.testclient'`. The actual package is `httpx` (FastAPI re-exports from it). Ensure `httpx` is installed in the test environment and add it to `requirements.txt` if missing.

### 4.2 Add unit tests for new/regressed endpoints

| Endpoint | Test Priority |
|----------|---------------|
| `POST /{chat_id}/messages/{message_id}/generate-swipe` | High — fresh code, no tests |
| `POST /{chat_id}/messages/{message_id}/tts` (after implementation) | High |
| `POST /{chat_id}/impersonate` | High — currently broken |
| `POST /{chat_id}/suggest` | Medium |
| `additional_character_ids` context assembly | Medium |

### 4.3 Expand Playwright E2E coverage

Existing E2E files are solid (`roleplay.spec.js`, `story-sandbox.spec.js`). Add:
- Group chat: create chat with 2+ characters, verify both appear in context.
- Swipe generation: verify `generate-swipe` produces a new alternate.
- TTS button: verify the endpoint exists and returns a job (mock LLM if needed).
- Story parse: verify importing a story creates characters + lorebooks.

---

## Phase 5: Performance & Debt

### 5.1 Cache-heavy queries

- `list_chat_jobs` and `list_chat_images` are polled by React Query. Add DB indexes if missing:
  - `messages(chat_id, created_at)` — already indexed.
  - `jobs(metadata_['chat_id'], created_at)` — consider a GIN index on `metadata_` for JSONB if not present.

### 5.2 `build_chat_context_async` session hygiene

The function signature accepts a `session` but immediately discards it for `asyncio.to_thread`. This is confusing and risks detached ORM objects if callers pass loaded entities. Options:
- **Preferred:** Remove the unused `session` parameter and document that callers should pass scalar data only.
- **Alternative:** Accept the request-scoped session and do NOT spawn a thread; move only the embedding call off-thread.

### 5.3 `image_submission.py` deduplication

The recent commit message says "Refactor image job submission logic". Verify all call sites now use `submit_image_job` instead of inline `build_image_job_workflow` + `JobService.create_job` + `queue_manager.enqueue`. Remaining inline paths should be migrated.

---

## Phase 6: Vision Alignment — From Demo to Pro

### 6.1 Chat Workspace QoL (Phase 8 items)

- **Message editing UX:** The edit button appears but the inline textarea is basic — add auto-resize and keyboard shortcuts.
- **Group chat UI:** `additional_character_ids` exists in the DB and context panel, but the message list does not show which character "spoke" in group replies. Add a character badge/tag to assistant messages when `target_character_id` is set.
- **Chat branching:** Not yet implemented. Consider a "fork chat" button that clones the chat and its messages.

### 6.2 Story Sandbox QoL

- **Rich text:** The editor is a plain `<textarea>`. Upgrade to a lightweight rich-text editor (e.g., TipTap) with bold/italic/headers so users can format chapters.
- **Inline lorebook linking:** Allow `@lorebook` mentions in the editor that auto-insert lore entry references.
- **Chapter reordering:** Drag-and-drop chapters in the sidebar.

### 6.3 World Vault QoL

- **Folders/tags:** Characters and Lorebooks are flat lists. Add tag-based filtering and folder grouping.
- **Batch actions:** Select multiple entities and delete/export/assign to story in bulk.

---

## Rollout Order

1. **Week 1:** Phase 1 (emergency fixes) + Phase 2 (dedup/N+1). This unblocks the frontend and stops backend crashes.
2. **Week 2:** Phase 3 (integration gaps: TTS, target_character_id, story-parse fix).
3. **Week 3:** Phase 4 (testing) + Phase 5 (performance).
4. **Week 4+:** Phase 6 (vision-alignment QoL), then revisit deferred items (Audio/TTS full modality, multi-tenancy).

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Multi-character context assembly changes LLM behavior | Test with 2+ characters in a chat before merging; verify system prompt output in `/system-prompt` endpoint |
| TTS endpoint requires new worker capability | Start with a simple `openai_compat` TTS route (e.g., `/v1/audio/speech`) in the LLM worker; defer ComfyUI audio nodes to Phase 9 |
| Frontend lint rules are strict | Run `npm run lint` in CI on every PR to prevent regressions |
| Backend test dependency missing | Pin `httpx` in `requirements.txt` and verify `pytest` runs in Docker |

---

## Out of Scope (Deferred per VISION.md)

- Audio/TTS full modality (ComfyUI XTTS/Bark) — deferred to Phase 9
- Multi-tenancy/auth — deferred
- Video/Animation support — post-core
- Visual Novel exporter — post-core
