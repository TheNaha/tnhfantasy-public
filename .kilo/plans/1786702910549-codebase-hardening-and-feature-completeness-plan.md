# TNHFantasy Codebase Hardening & Feature Completeness Plan

## Current State Summary

TNHFantasy is a **Comprehensive AI Fantasy Engine** with three pillars: Image Generation, Roleplay Chat, and Story Sandbox. The working tree contains substantial recent changes (~1500 insertions across 25 files) adding group chat support, TTS, swipe generation, workflow builder consolidation, and story parsing. However, these additions are currently **broken or incomplete**, with 14 failing frontend tests and multiple blocking bugs.

## Phase 1: Fix Blocking Bugs (Do First)

### 1.1 Fix Build-Breaking Frontend Errors
- **`frontend_v2/src/pages/ChatWorkspace.jsx:843`** — `handleIllustrate` is declared twice. Remove the duplicate declaration.
- **`frontend_v2/src/components/chat/MessageItem.jsx:16,24`** — `const meta` is declared twice. Remove the first declaration block (lines 15-19) and keep the second (lines 24-28), or consolidate.
- **`frontend_v2/src/hooks/useWorldVault.js`** — Add missing `useUpdateCharacter` export (it exists in `useCharacters.js` but is not re-exported). This is causing 6 StorySandbox test failures and a runtime mock error.

### 1.2 Fix Backend Test Environment
- Backend tests fail with `ModuleNotFoundError: No module named 'fastapi.testclient'`. The project venv at `.venv` is not activated when running `python -m pytest`. Update `AGENTS.md` test commands to use `.venv/bin/python -m pytest` or `pip install fastapi[standard]` into the venv.

## Phase 2: Complete Half-Built Integrations

### 2.1 Group Chat (additional_character_ids)
**Status**: DB column + migration + UI exist, but LLM context and reply routing are incomplete.
- **Backend**: In `chats.py` `add_message`, the new `target_character_id` field is accepted in `SendMessageRequest` but **never used**. Implement logic so that when `target_character_id` is set, the LLM is prompted to reply as that specific character.
- **Backend**: In `context_builder.py`, `build_system_prompt_sections` appends each character's prompt, but the LLM receives no turn-order or speaker-identification instructions. Add a `GroupChatContext` section that enumerates present characters and their speaking styles.
- **Frontend**: The "Reply as" selector in `ChatWorkspace.jsx` sends `target_character_id` but the backend ignores it. Wire it up.

### 2.2 TTS (Text-to-Speech)
**Status**: Backend endpoint + workflow exist, but provider support is unverified and dispatch is semantically wrong.
- **Backend**: `build_tts_workflow` uses hardcoded node IDs (`3`, `4`) and class types (`XTTS_v2`, `SaveAudio`). Make the workflow configurable via provider capabilities or a provider capability discovery mechanism.
- **Backend**: `narrate_message` endpoint dispatches TTS as `task_type="image"`. Either add `audio` as a valid `task_type` in `VALID_TASK_TYPES` and update provider routing, or create a dedicated audio worker path.
- **Frontend**: Replace raw `fetch` in `handleGenerateTTS` with a proper React Query mutation hook (`useNarrateMessage`). Add an audio player that appears inline when `meta.audio_path` is present.

### 2.3 Swipe Generation
**Status**: Backend endpoint exists, frontend hook exists, but streaming/handling may be incomplete.
- **Backend**: `generate_swipe` builds LLM workflow with `is_swipe: true` metadata. Verify `world_integration_service._handle_chat_reply` correctly appends alternates when `is_swipe` is true. It does, but the `target_msg.content` overwrite happens before the message is reloaded by the frontend — ensure React Query cache invalidation brings back the updated message with alternates.
- **Frontend**: `MessageItem.jsx` renders swipe arrows when `altCount > 1`. Verify the swipe state is correctly maintained after regeneration.

### 2.4 Story Parsing
**Status**: Backend endpoint `/stories/parse` exists, but result is a raw LLM job with no structured extraction.
- **Backend**: The parse endpoint returns `job_id`. The LLM is instructed to return JSON, but `job_processing` does not have a handler for `story_parse` type. Add `_handle_story_parse` in `world_integration_service.py` that parses the LLM JSON response and creates `Character`, `Lorebook`, and `LorebookEntry` records.
- **Frontend**: `ParseStoryModal.jsx` exists but is untracked. Integrate it into `StorySandbox.jsx` and wire it to the parse endpoint. After job completion, show the extracted entities in a review modal before saving.

## Phase 3: Eliminate Duplication & Strengthen Architecture

### 3.1 Centralize Generator Payload Assembly
**Status**: `useWorkflowBuilder` is created but generator pages still duplicate store extraction.
- **Frontend**: Refactor `SimpleGenerator.jsx`, `Img2ImgGenerator.jsx`, and `InpaintGenerator.jsx` to only extract `prompt` and `randomizeSeed` from `useGeneratorCore`. All other parameters should come from `useWorkflowBuilder.store`.
- **Backend**: `workflow_builder.py` is the single source of truth for ComfyUI payload assembly. Ensure all three generator pages call `buildPayload` + `runWithPreflight` from the hook without local overrides.

### 3.2 Remove Ad-Hoc Patch Scripts
- **Delete `patch_chats.py`** — it is an untracked ad-hoc patch script. The changes it documents have already been applied to `chats.py`.

### 3.3 Fix N+1 Queries in Chat Routes
- **Backend**: `chats.py` loads characters in loops: `session.get(Character, cid)` for each `additional_character_ids`. Replace with a single `select(Character).where(Character.id.in_(ids)).all()` query in `_chat_context_kwargs` or a helper.

### 3.4 Unify Frontend Data Fetching
- **Frontend**: `handleGenerateTTS` and `handleIllustrate` in `ChatWorkspace.jsx` use raw `fetch`. Replace with React Query mutations (`useNarrateMessage`, `useIllustrateChat` already exists for illustrate, but TTS needs a new hook).

## Phase 4: Test Coverage & Quality Gates

### 4.1 Fix Existing Test Failures
- Fix the 14 failing frontend tests (ChatWorkspace transform error, StorySandbox missing mock, generator pages, ImageLightbox timeout, NumberInput).
- Ensure `npm test` passes cleanly before adding new tests.

### 4.2 Add Tests for New Features
- **Backend**: Add pytest for `generate_swipe`, `narrate_message`, `parse_story`, and group chat context building.
- **Frontend**: Add vitest for `useWorkflowBuilder`, `MessageItem` swipe/alternates rendering, and the "Reply as" selector.
- **E2E**: Add Playwright tests for group chat creation, swipe generation, TTS playback, and story parsing flow.

### 4.3 CI Integration
- Ensure tests run in CI for all changed directories.

## Phase 5: Performance & Polish

### 5.1 Caching
- Add a short-lived cache for character lookups in `context_builder.py` since the same characters are fetched repeatedly across messages in a chat.
- Add Redis or in-memory cache for provider model listings if not already present.

### 5.2 Frontend Virtualization
- `ChatWorkspace.jsx` uses `@tanstack/react-virtual` for messages. Verify it is actually used and not falling back to full DOM rendering. If not, implement virtualization for chats with >500 messages.

### 5.3 Error Boundaries
- Add React error boundaries around `StorySandbox` and `ChatWorkspace` so a component crash doesn't blank the entire app.

## Validation Plan

1. `npm run lint` passes with zero errors.
2. `npm test` passes (frontend).
3. `.venv/bin/python -m pytest` passes (backend).
4. Manual verification: create group chat, send messages as different characters, generate swipe, trigger TTS, parse a story, branch a story.
5. E2E tests cover the new flows.

## Out of Scope (Deferred)
- Audio/TTS provider deployment and custom node setup (depends on provider infrastructure).
- Multi-tenancy / auth (explicitly deferred per project.md).
- Video / Animation / AnimateDiff (future frontier).
- RAG / pgvector memory indexing (future frontier).
