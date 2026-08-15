# TNHComfy Remediation Plan — Refining the AI Fantasy Engine

Investigation date: 2026-08-15. Source: full-stack audit of `backend_v2/`, `frontend_v2/`, `provider_containers/`, e2e suite, and git working tree.

Status of the app: architecture is sound and RAG/agentic-tier features are genuinely implemented (not stubs), but the **working tree contains a P0 regression that breaks the chat entirely**, several new features are "demo-grade" (no CRUD depth, disconnected UI), and there are ~30 verified bugs + large untested surfaces.

---

## Batch 0 — Critical Regressions (fix first, zero new features)

| # | Severity | Issue | Evidence | Fix |
|---|----------|-------|----------|-----|
| 0.1 | **P0** | ChatWorkspace renders `ChatTimeline` (a *branch tree* expecting `{chatId, activeBranch, onBranchChange, onNewBranch}`) with 13 message-list props — all silently ignored. No message list renders on `/chat` at all. `MessageItem.jsx` has zero importers; `timelineVisible` is set by `ChatWorkspaceHeader.jsx:87` but never read (the GitBranch modal that used `ChatTimeline` is gone). | `frontend_v2/src/pages/ChatWorkspace.jsx:66-80` vs `frontend_v2/src/components/chat/ChatTimeline.jsx:13` | Extract new `components/chat/MessageTimeline.jsx` from the pre-refactor virtualized list (`git show HEAD:frontend_v2/src/pages/ChatWorkspace.jsx` — used `@tanstack/react-virtual` + `MessageItem`), wire the 13 props into it, and restore a branch-tree modal fed by `timelineVisible`. |
| 0.2 | P1 | Chat e2e suite silently broken by 0.1 (`roleplay.spec.js`, `chat-nuances.spec.js` are message-heavy) | | Re-run after 0.1; fix fallout. |

## Batch 1 — Verified Backend Bugs (~10 lines each)

| # | Severity | Issue | Evidence | Fix |
|---|----------|-------|----------|-----|
| 1.1 | bug | `POST /chats/{id}/impersonate` → `NameError` on every call: `char_name = character.name if character else "the AI"` — `character` never assigned; `characters` list computed but unused. 500 error. No test covers it. | `backend_v2/api/routes/world_vault/chats.py:883` (cf. `suggest_reply` at :963-965) | `character = session.get(Character, chat.character_id) if chat.character_id else None` + add test. |
| 1.2 | bug | `GET /locations/search` shadowed by `GET /{location_id}` — FastAPI matches in registration order, `"search"` hits `get_location` → 404. Dead endpoint. | `locations.py:52` vs `:105` | Move `/search` route above `/{location_id}` + add test. |
| 1.3 | bug | `generate_swipe` creates an LLM job but enqueues without `task_type` → typed `"image"` → ComfyUI worker picks up an LLM job. | `chats.py:670` create vs `:678` `enqueue(job.id)` (default `"image"`, `job_queue.py:476`) | `enqueue(job.id, task_type="llm")` + test. |
| 1.4 | bug | `generate_scene` sets `workflow["tools"] = AGENTIC_TOOLS` unfiltered, bypassing `chat.allow_image_generation`/`allow_narration`. Every other caller uses `filter_agentic_tools`. | `chats.py:1118` | Apply `filter_agentic_tools` for parity. |
| 1.5 | bug | Agentic follow-up hops (depth ≥2) bypass tool filtering: `process_tool_calls_and_chain` always sets `followup_workflow["tools"] = AGENTIC_TOOLS`, even for chats with image/narration disabled. First hop filters correctly. | `orchestrator_service.py:955` | Thread the filtered toolset (from parent job metadata or re-resolve chat row). |
| 1.6 | bug | Branch copies keep stale `parent_id` (original ids, not remapped) and reset `created_at=now()` (ordering by insertion, not original). Legacy-chat fallback produces an **empty branch** silently. | `branches.py:99-125` | Remap `parent_id` through `old_to_new`, preserve `created_at`; implement parent-chain walk instead of empty fallback. Add tests (branches currently untested). |
| 1.7 | bug | Timeline route double-`join(Chat)` when both character + location filters set (cartesian/error); `Asset` imported but never queried so image events are missing; `story_id` filter only applies to chapters. | `timeline.py:38-40` | Single conditional join; add Asset events; drop unused imports. |
| 1.8 | bug | `build_chat_context_async` discards the passed `session` and opens a fresh connection every call. | `context_builder.py:697-717` | Use the provided session (or document). |

## Batch 2 — Detached / Incomplete Systems (feature-completeness)

| # | Severity | Issue | Evidence | Fix |
|---|----------|-------|----------|-----|
| 2.1 | P1 | **Frontend dead hooks (15):** `useExportChat`, `useScenario`, `usePatchScenario`, `useVoice`, `useCharacterMemories`, `useCreateMemory`, `useUpdateMemory`, `useDeleteMemory`, `useSearchMemories`, `useMemories`, `useAlternates`, `useCampaign`, `useWorldVaultRelationships`, `useRefreshLLMStatus`, `useExportStory`, `useSearchLocations` — zero callers. | `src/hooks/useWorldVault.js` + rg sweep | Either wire them into pages (memories on character page, campaign detail on campaigns page, export via story reader) or delete. **RelationshipGraph bypasses its hook** with raw `api.get` in `useEffect([])` + silent catch → move it into a proper React Query hook with refetch + error UI. |
| 2.2 | P1 | **WorldVaultHub debounce broken:** `handleSearch` returns the `clearTimeout` from an `onChange` handler — the debounce never fires, timer leaks each keystroke. Search results not clickable. | `src/pages/WorldVaultHub.jsx:39-44` | Proper `useCallback` + ref-based debounce; make results navigate. |
| 2.3 | P1 | **Optimistic update never lands:** `useMessages` key `['world_vault','messages',chatId,limit,offset]` vs `useEditMessage` `setQueryData` on 3-part key. | `useMessages.js` / queryKeys.js | Unify all vault keys through `buildQueryKey()` (`['world_vault', ...]`); singular `'story'`/`'chat'` keys in useStoryImages/useChatImages → plural. |
| 2.4 | P1 | **AvatarGallery chat deep-link broken:** `CharacterCard` calls `onChat()` with no args → `navigate('/chat/undefined')`. Also `e2e/characters.spec.js:63` deep-links `/characters/{id}` — **no such route** in App.jsx (falls through `*` → FantasyHub). | `AvatarGallery.jsx:185`, `App.jsx:87` | Pass `character.id`; add `/characters/:id` route (opens detail modal / prefetches) and align the spec. |
| 2.5 | P2 | **LorebookModal** is edit-only (no create path despite route existing), uses raw `fetch()`, no error toast. | | Use `useLorebooks` mutations, add create mode, error handling. |
| 2.6 | P2 | **Campaigns form** collects only name/description — `character_ids/story_ids/chat_ids/location_ids` can never be set from UI, so campaigns are bare shells. Location entity likewise lacks UI linkage into stories/chats (context panel can't show location). | `src/pages/Campaigns.jsx:21-28` | Add entity-picker multi-selects; show location in chat context + story editor. |
| 2.7 | P2 | **World hub counts** omit locations & campaigns; recent activity covers only 3 of 8 entity kinds. | `world_hub.py:19-60` | Extend both. |
| 2.8 | P2 | **Scenario application is asymmetric:** chat target overwrites `system_prompt_override`; story target only sets `scenario_id`, template unused for stories; `target_type` is a raw string. | `scenarios.py:75-108` | Enforce a `ScenarioTarget` enum; story apply should use template via context builder. |
| 2.9 | P2 | **Story export response shapes differ per format** (dict for JSON/markdown vs bytes for epub/comic/webtoon); `format` shadows builtin. | `stories.py:30-35` | Unify on `Response` + content-type; single serializer module. |
| 2.10 | P2 | **No embedding backfill migration:** memories/lorebook entries created before step 041 have NULL embeddings (silent keyword fallback). No reindex endpoint exists. | `infrastructure/migrations/steps.py` | Add a reindex step/endpoint (`POST /api/v2/memories/reindex`). |
| 2.11 | P2 | **Dead state/hooks in stores:** `worldVaultStore` 5/8 keys dead (`activeStoryId`, `activeCharacterId`, setters, `reset`); `ChatWorkspaceContext` 923 lines with routing+virtualization+streaming+modals+TTS all in one context; exposes dead `timelineVisible` state. | | Purge dead keys; after 0.1, extract TTS/modal state into the extracted components. `MessageItem.jsx` + `TavernMessage.jsx` orphans resolved by 0.1. |
| 2.12 | P2 | **Entity JSON-array FKs** (`Story.character_ids`/`lorebook_ids`, `Chat.additional_character_ids`, `Campaign.*_ids`) have no referential integrity: deleting a character leaves dangling ids; world_hub matching uses `cast(JSON, String).contains` (substring false-positives + N+1 — up to 100 queries). | `core/entities.py:977-978,825,1040-1043`; `world_hub.py:63-117` | Move to join tables OR add post-delete cleanup + single-query JSON matching (`json_each`). Prefer join tables for campaign/location; cheapest fix for story/chats is cleanup-on-delete. |
| 2.13 | P3 | **No image generation integration in Story Sandbox reader/vault beyond illustrate modal** — chained image endpoints exist (illustrate_chapter/chat, generate_scene) and are real, not stubs. Casual flow works; power flow (choose model/LoRA, batch contexts) needs the Batch Studio (PLAN.md 2.3). | | Track as follow-up feature. |

## Batch 3 — Duplication & Unification

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 3.1 | P2 | Narrator voice-resolution logic duplicated ×3 (`chats.py:513-526`, `stories.py:968-981`, `orchestrator_service.py:426-447`). `chat_utils.py` exists for exactly this. | Extract `resolve_voice_for_character(session, char)`. |
| 3.2 | P2 | First-text extraction from LLM output duplicated (`world_integration_service._first_text` vs `job_processing.py`). | Consolidate in one util. |
| 3.3 | P3 | Provider progress semantics drift: `comfy_status_to_task_event` emits 0–100 percent but `TaskEvent.value` docstring says fraction 0..1; backend works around with heuristic `int(val*100) if val<=1 else int(val)` (`provider_client.py:179`). | Pick percent as canonical, update `provider_core/models.py:61` docstring, drop heuristic. |
| 3.4 | P3 | Modal vs Beam apps duplicate download/validate logic (`beam_app.py:246-338` vs `modal_app.py:765-869`); 4 client `inference()` loops repeat cancel/timeout/stream-error handling; 4 LLM engine clients near-identical; two transports (Beta9 WebSocket vs modal generator) for one logical stream. | Extract shared `inference_loop()` helper in provider_core; docker workers reuse in both apps. Low priority — works today. |
| 3.5 | P3 | `worker_ws.py` defines a *second* progress protocol (`job_progress` with raw progress fields) separate from TaskEvent NDJSON contract. | Route external workers through `translate_task_events`. |
| 3.6 | P3 | `runtime.py` hardcodes Docker-DNS container names + port 8000 → health paths break for serverless-only deploys; `provider_deploy_service.py` + `provider_deploy_orchestrator.py` overlap; LoadBalancer imports `get_container_manager` from `api.deps` (api→service inversion). | Resolve health URL from Provider row `worker_url` first; document single-process LB assumption. |
| 3.7 | P3 | Backend dead code sweep: ~30 unused imports (branches.py, campaigns.py, chats.py:440/1062/1150, stories.py:13, timeline.py, memories.py:135, voices.py, world_hub.py:10/14, context_builder.py:362/392-393, orchestrator/world_integration/job_processing/asset_reconciler, `services/__init__.py` re-export block) + `inject_lorebooks_into_system_prompt` defined-never-called + `build_image_workflow` unused imports ×4 + `scenarios.py` dead no-op + `voices.py:38-39` dead `if`. `read_png_metadata` alias is intentional — keep. | Remove/use. Also unify `cosine_distance` idiom (function form at `orchestrator_service.py:702` vs method form at `context_builder.py:402`). |
| 3.8 | P3 | `characters.py` response shapes inconsistent: clone/import/export return raw `Character` (no `has_avatar`/enrichment) while list/get return `_character_to_dict`. | Unify through `_character_to_dict`. |
| 3.9 | P3 | e2e helper duplication: `readPersisted`/sort helpers (model-manager vs settings), provider seeding (providers.spec local), `expandEnhancements`, `openSeededChat`, `uploadSourceImage`, mobile helpers duplicated per spec. | Move into `fixtures.js`. |

## Batch 4 — Test Coverage & CI

| # | Add |
|---|-----|
| 4.1 | Backend unit tests for: impersonate (1.1), locations search (1.2), generate-swipe task type (1.3), branches (1.6), timeline, campaigns, locations CRUD, world_hub relationships shape, characters clone/import/export/avatar, parse/continue/illustrate story routes, agentic follow-up tool gating (1.5). ~10 test files, cheap, run in docker: `docker exec tnhcomfy-backend python -m pytest -q`. |
| 4.2 | Unit tests for untested hooks: useChats, useMessages, useBranches, useCharacters, useStories, useScenarios, useWorldVaultSearch, useChatStreaming (new), useStreamingJobs, useLLMProviderStatus; pages: WorldVaultHub, AvatarGallery, RelationshipGraph, Locations, Campaigns, WorldTimeline, BatchGenerate, StoryReader, FantasyHub. |
| 4.3 | e2e specs for 8 uncovered routes: `/world-vault`, `/world-timeline`, `/locations`, `/campaigns`, `/scenarios`, `/voices`, `/story-reader`, `/batch-generate` (new-pages.spec.js currently covers only /world-graph + /avatar-gallery). |
| 4.4 | **Playwright in CI** — currently `frontend-tests.yml` runs only vitest+lint; e2e/ changes trigger nothing; no `webServer` block in playwright.config.js. (Decision needed — see questions.) |

## Batch 5 — Vision-aligned polish (after stability)

- Batch Generation Studio UI (PLAN.md 2.3) — real power-user flow for character sheets / scene variations.
- Agentic idle simulation cron + Autobiographical memory reindex (VISION frontiers 1 & 4) build on Batch 2/1 fixes.
- StoryReader page: wire `useExportStory` + publish token flow (dead hook today).
- Chat: restore command palette + swipe/branch UX lost in the 0.1 refactor; wire `MessageItem` action props end-to-end.

---

## Verification strategy

- After each batch: `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V` (note: `-V` wipes volumes — **remove when not desired**), then:
  - Backend: `docker exec tnhcomfy-backend python -m pytest -q`
  - Frontend: `cd frontend_v2 && npm test && npm run lint`
  - E2E: `npx playwright test --grep-invert @fullstack --reporter=line`
- Batch 0 must pass the three chat specs before anything else ships.

## Pre-existing PLAN.md note

The old `PLAN.md` phases are mostly **done** (locations/timeline/campaigns/graph/avatar-gallery/RAG-exists): treat as historical. This document supersedes its Phase 0–1 items.