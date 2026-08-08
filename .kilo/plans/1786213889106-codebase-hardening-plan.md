# Codebase Hardening & Vision Alignment

## Current State
TNHComfy has a working multimodal foundation: PostgreSQL + pgvector, FastAPI backend, React frontend, Modal provider containers, and a complete World Vault schema. The agentic orchestrator, context builder, and streaming infrastructure are functional. There are critical bugs, missing integrations, code duplication, and performance issues blocking the VISION.

---

## Implementation Tasks

### Phase 1: Critical Bug Fixes

1. **Fix `chat_type` default mismatch** (`backend_v2/api/routes/world_vault/chats.py:33`)
   - Change `CreateChatRequest.chat_type` default from `"roleplay"` to `"chat"`
   - Add migration to update existing rows where `chat_type = 'roleplay'` to `'chat'`

2. **Use constant for agentic depth limit** (`backend_v2/services/job_processing.py:540`)
   - Import `MAX_AGENTIC_DEPTH` from `services.orchestrator_service`
   - Replace hardcoded `5` with the constant

3. **Invalidate messages after send** (`frontend_v2/src/hooks/useWorldVault.js:170-178`)
   - In `useSendMessage` onSuccess, also invalidate `['world_vault', 'messages', chatId]`

4. **Fix sync `build_chat_context` blocking event loop** (`backend_v2/api/routes/world_vault/chats.py:190`)
   - In `get_chat_system_prompt`, switch from `build_chat_context` to `build_chat_context_async`

5. **Enforce `allow_image_generation` / `allow_narration` gates** (`backend_v2/api/routes/world_vault/chats.py:315-382`)
   - In `add_message` and `regenerate_reply`, filter out `generate_image` / `narrate_scene` from agentic tools when the chat has them disabled

### Phase 2: Missing Integrations

6. **Story continuation must use `context_builder`** (`backend_v2/api/routes/world_vault/stories.py:138-224`)
   - Replace inline system prompt/context assembly with `build_chat_context_async`
   - Pass story-level parameters: genre, memory, character_ids, lorebook_ids

7. **Workspace-scoped collections** (`backend_v2/api/routes/collections.py:64`)
   - Add optional `workspace` filter param to `list_collections`
   - Filter in repository layer

8. **Add missing ORM relationships** (`backend_v2/core/entities.py:180-207`)
   - `Collection`: add `character: Optional["Character"] = Relationship(back_populates="collections")`
   - `CollectionImage`: add `collection: Optional["Collection"] = Relationship(back_populates="images")`
   - Add `collections: list["Collection"] = Relationship(back_populates="character")` to `Character`

### Phase 3: Performance

9. **Eliminate N+1 in story continuation** (`backend_v2/api/routes/world_vault/stories.py:138-224`)
   - Batch load characters: `session.exec(select(Character).where(Character.id.in_(story.character_ids)))`
   - Batch load lorebook entries: `session.exec(select(LorebookEntry).where(LorebookEntry.lorebook_id.in_(story.lorebook_ids)))`

10. **Optimize `list_chat_jobs`** (`backend_v2/api/routes/world_vault/chats.py:411-452`)
    - Replace Python-side filtering with SQLAlchemy JSONB expression: `Job.metadata_['chat_id'].as_string() == chat_id`

11. **Reduce context builder DB queries** (`backend_v2/services/context_builder.py:303-398`)
    - Single `select(LorebookEntry).where(LorebookEntry.lorebook_id.in_(lorebook_ids))`, group in Python

12. **Paginate `list_chats` and `list_messages`** (`backend_v2/api/routes/world_vault/chats.py:52-54`, `152-154`)
    - Add `limit`/`offset` params with defaults (50/100)

### Phase 4: Code Deduplication

13. **Extract shared LLM workflow builder**
    - Create `backend_v2/services/llm_job_builder.py` with helpers:
      - `build_chat_reply_workflow(messages, system_prompt, model, chat_id, ...)`
      - `build_story_continue_workflow(messages, system_prompt, model, story_id, chapter_id, ...)`
      - `build_narrator_workflow(messages, system_prompt, model, chat_id, ...)`
    - Update `chats.py`, `stories.py`, `orchestrator_service.py` to use these helpers

14. **Extract shared system prompt assembly for stories** (`backend_v2/api/routes/world_vault/stories.py:156-223`)
    - Replace inline assembly with `build_system_prompt_sections_async` + `build_chat_context_async`

15. **Break up massive frontend components**
    - `ChatWorkspace.jsx` → `ChatSidebar`, `MessageList`, `MessageInput`, `ContextPanel`, `SystemPromptPanel`
    - `StorySandbox.jsx` → `StorySidebar`, `ChapterSidebar`, `StoryEditor`, `StoryContextPanel`

### Phase 5: Architectural Alignment

16. **Rename `chat_type` to `workspace`** (`backend_v2/core/entities.py:716`)
    - Rename field + column to `workspace`
    - Update all references in backend and frontend
    - Add migration

17. **Frontend-assembled prompts (VISION §7)**
    - Add `/api/v2/chats/{id}/context-parts` endpoint returning raw sections without merging
    - Frontend merges sections, applies substitutions, sends assembled payload to `/api/v2/chats/{id}/messages`
    - Backend validates but does not re-assemble

18. **Standardize event shapes**
    - Ensure all LLM finalization paths emit consistent `event_extra = {type, metadata, ...}`
    - Remove duplicate side-effect logic from `job_processing.py` that `world_integration_service` already handles

### Phase 6: Database Migrations

- Migration 1: Rename `chat_type` → `workspace`, migrate existing `roleplay` → `chat`
- No schema changes needed for missing relationships (ORM-only fix)

### Phase 7: Testing & Validation

**Unit tests:**
- `test_chat_type_default`: Verify `CreateChatRequest` and `Chat` default match
- `test_agentic_depth_uses_constant`: Verify `MAX_AGENTIC_DEPTH` is imported
- `test_allow_image_generation_gate`: Verify tool is blocked when disabled
- `test_story_continuation_uses_context_builder`: Verify `build_chat_context_async` is called

**Integration tests:**
- Create chat → send message → streaming reply → message inserted
- Create story → continue chapter → lorebook injection verified
- Chat scene generation → image job chains → `chat_image` event fires

**Manual validation:**
1. `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V`
2. Create chat via UI, verify `workspace` is `"chat"`
3. Send message with active lorebooks, verify entries in system prompt
4. Continue story, verify context builder usage (logs)
5. Trigger agentic `generate_image`, verify image appears in chat
6. Trigger story illustration, verify `StoryChapter.image_paths` updates

---

## Open Questions

**Should `Story` and `Chat` share `build_chat_context_async`?**
- Stories need long-form prose context, world bible, chapter memory, genre, author's note
- Chats need short conversational turns, character voice, pinned messages, example dialogue
- **Recommended:** Start with shared `build_chat_context_async` but add story-specific kwargs (`include_memory`, `include_genre`, `include_chapter_content`). If story context quality suffers, extract `build_story_context_async` later.

---

## Execution Order

1. Phase 1 (Bugs) — smallest, highest impact
2. Phase 3 (Performance) — quick wins
3. Phase 2 (Missing integrations) — fixes broken features
4. Phase 4 (Deduplication) — reduces maintenance burden
5. Phase 5 (Architecture) — larger changes, do last
6. Phase 6 (Migrations) — paired with 5.2
7. Phase 7 (Testing) — ongoing

---

## Out of Scope (Deferred)
- Audio / TTS
- Multi-tenancy
- Video / Animation
- Visual Novel Mode
