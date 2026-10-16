# Roleplay Cohesion Plan (Chat + Story + World Vault)

Goal: Make the Roleplay system ("World Vault") cohesive by consolidating entity overlap, unifying the context builder across chat and story, and making StoryBeat rows the source of truth for chapter prose — while keeping Chat and Story as separate transcript models (per user decision).

## Decisions (locked)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Persona → optional named reference on Chat/Story; Persona table/library page stays as a named shortcut to `persona_name`/`persona_description` strings | `Chat.persona_*` / `Story.persona_*` are already the source of truth; Persona row is a reusable template |
| D2 | Scenario → optional named reference (`scenario_id` FK) on Chat/Story; `scenario` free-text field on Character stays | `Character.scenario` duplicates `Scenario.prompt_template` concept; library page stays as template shortcut |
| D3 | Chat and Story stay separate transcript models; cohesion via shared context builder + shared worker pipeline | Different purposes (roleplay session vs AI Dungeon doc); unifying transcripts would be a large, risky rewrite |
| D4 | Unify `build_system_prompt_sections` + `build_chat_context_async` into one `build_context(session, workspace, ...)` with `chat`/`story` modes; eliminate dict-vs-ORM branching | Currently chat passes ORM Message rows, story passes dicts; parameter sprawl (~20 kwargs) spans both domains |
| D5 | `StoryBeat` rows are the source of truth within a chapter; `chapter.content` and `chapter.beats` JSON are derived renderings | `StoryChapter` currently holds 3 representations of the same text (`content`, `beats` JSON, `StoryBeat` rows) |

## Affected boundaries

Backend (`backend_v2/`):
- `core/entities.py` — Persona/Scenario FK nullability, StoryBeat/Chapter derived-fields, optional `scenario_id` on Chat/Story
- `services/context_builder.py` — unified `build_context(session, workspace, entity, ...)` replacing `build_system_prompt_sections` + `build_chat_context_async`
- `services/rag_pipeline.py` — shared precomputed query vector (already mostly done; keep symmetric)
- `services/world_ownership.py` — no structural change; Persona/Scenario may be added to MEMBER_TABLES if they get `world_id`
- `api/routes/world_vault/{chats,stories,personas,scenarios}.py` — route schemas adapted for optional Persona/Scenario references
- `services/world_integration_service.py` — unchanged (consumes JOB_COMPLETED; workspace-agnostic)
- `services/job_submission_service.py`, `services/llm_workflow.py`, `services/llm_router.py` — unchanged (already workspace-aware via `type`/`kind`)
- `services/engines/` — unchanged (LLM/TTS/Image engines already accept task_type/metadata)
- `infrastructure/migrations/steps.py` — new migration steps for optional FKs + derived-field backfill

Frontend (`frontend_v2/src/`):
- `pages/StorySandbox.jsx`, `components/story/` — chapter editor renders from StoryBeat rows; `content`/`beats` treated as derived
- `store/worldVaultStore.js`, `hooks/useStories.js`, `hooks/useMessages.js` — no schema change needed (optional FKs are additive)
- `api/client.js` — no change

## Data flow (unchanged at worker boundary)

```
User message / story action
  → build_context(session, workspace="chat"|"story", ...)  ← unified
    → sections: character/lorebook/world/location/persona/scenario/story_*
    → prune_context (shared)
  → llm_workflow.build_*_workflow (task_type="llm", kind=chat_reply|narrator|story_continue)
  → job_submission_service (validate → Job → enqueue; default LLM provider)
  → job_processing → engine_factory → LLM engine (streams TaskEvents via NDJSON/WebSocket)
  → frontend renders deltas (ChatWorkspace / StorySandbox)
  → JOB_COMPLETED → world_integration_service writes Message row (chat) or StoryBeat row (story)
    → submit_tts_job (TTS engine → audio_path)
    → memory_extraction (background LLM, util role)
    → orchestrator generate_image/narrate_scene (Image engine → assets)
```

Worker pipeline (LLM/TTS/Image engines) needs **no changes** — it already routes on `task_type` and `kind`, not on entity type.

## Failure modes & risks

- **Derived-field drift**: `chapter.content` / `chapter.beats` JSON must be regenerated whenever StoryBeat rows change (create/edit/delete/reorder/alternate-switch). Need a single `rebuild_chapter_renderings(chapter)` called from every write path.
- **Optional FK backfill**: Making `persona_id`/`scenario_id` nullable on existing Chat/Story rows requires a migration step that sets them from existing `persona_name`/`scenario` strings where a match exists, else null.
- **Context builder mode split**: `chat` mode uses `Chat.location_id`, `active_lorebook_ids`, `Message` rows; `story` mode uses `Story.location_ids`, `Story.lorebook_ids`, `StoryBeat` rows. Must not mix.
- **Persona/Scenario library pages**: keep working as named shortcuts; UI must write the string fields (not just the FK) so existing behavior is preserved when no match exists.

## Rollout / migration path

1. Add migration steps in `infrastructure/migrations/steps.py`:
   - `ALTER TABLE chats ADD COLUMN scenario_id FK NULL` (and `persona_id` already exists; make optional if not)
   - `ALTER TABLE stories ADD COLUMN scenario_id FK NULL` (persona_id already exists)
   - Backfill: set `scenario_id`/`persona_id` where name matches an existing row; else null
   - No `NOT NULL` enforcement (nullable = inherit)
2. Implement unified `build_context` in `context_builder.py`; keep old functions as thin wrappers deprecated (do not delete in this plan; routes migrate one at a time)
3. Implement `rebuild_chapter_renderings(chapter)` deriving `content` + `beats` JSON from `StoryBeat` rows; call from all StoryBeat write paths
4. Migrate `chats.py` and `stories.py` route context assembly to the unified builder
5. Frontend: StorySandbox editor reads/writes StoryBeat rows; `content`/`beats` treated as read-only derived
6. Run backend + frontend test suites; lint + typecheck

## Validation plan

- Backend: `cd backend_v2 && pytest` — all existing roleplay tests green; new tests for `build_context` chat/story mode equivalence and `rebuild_chapter_renderings` correctness
- Frontend: `cd frontend_v2 && npm test` + `npm run lint`
- Lint/typecheck: `cd backend_v2 && ruff check .`; `cd frontend_v2 && npm run lint`
- Scenario: editing a StoryBeat row updates `chapter.content` and `chapter.beats` JSON consistently; chat context and story context produce identical section format for shared fields (character, lorebook, world)

## Open questions (deferred, not blocking)

- Whether Persona/Scenario library pages should be removed entirely or kept as named shortcuts (kept for now, D1/D2)
- Whether `GraphLayout` becomes a real relationship graph (out of scope; currently a UI layout store)
- Whether Activity/Timeline gets write integration (out of scope; read-only projection)

## Ordered task list

1. Add migration steps: optional `scenario_id` FK on chats/stories + backfill from name match
2. Refactor `context_builder.py`: single `build_context(session, workspace, ...)` with chat/story modes; remove dict-vs-ORM branching
3. Add `rebuild_chapter_renderings(chapter)` deriving `content` + `beats` JSON from StoryBeat rows
4. Wire `rebuild_chapter_renderings` into all StoryBeat write paths (create/edit/delete/reorder/alternate-switch)
5. Migrate `chats.py` and `stories.py` context assembly to unified builder
6. Frontend StorySandbox: editor reads/writes StoryBeat rows; `content`/`beats` treated as derived
7. Run backend tests + frontend tests + lint + typecheck; fix regressions

## Note on implementation

This plan is implementation-ready but I cannot mutate files. To execute, switch to an implementation-capable agent (e.g. the code agent) and point it at this plan file.
