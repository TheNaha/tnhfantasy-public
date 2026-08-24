# Pillar Hardening & Frontier Validation

> Single-user AI Fantasy Engine. Goal: every implemented feature is **complete, wired, and validated** — no "demo feel." Tests green (backend 1515, frontend 553); git tree clean. Stack runs via `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V`.

## Guiding principles

- **Casual-first, power-user-deep.** Every view must do something useful on a fresh stack; power tools behind affordances.
- **No silent errors.** Swallowed exceptions become toasts / error boundaries.
- **Wire before build.** No new feature until existing ones are fully connected.
- **Test-gated.** `pytest` + `npm test` must pass per phase before moving on.
- **Inline deletion.** Remove dead code, dead endpoints, dead store state as you touch files.

---

## Phase 0 — Critical "broken / missing" (P0)

These block basic usability. Nothing ships until done.

### 0.1 Lorebooks frontend (entity is fully orphaned)
- Backend complete: `lorebooks.py` (CRUD + entries + semantic search + reindex), repo, migrations. Zero frontend.
- Add `frontend_v2/src/pages/Lorebooks.jsx` — list/create/edit/delete + entry management + reindex button (mirror `Characters.jsx`/`Locations.jsx` patterns). Add `useLorebooks.js` barrel exports for the new actions.
- Add `LorebookModal.jsx` already exists for story linking — wire its entry management into the page, or build entry CRUD into the page directly.
- Add nav link in `Layout.jsx:242` (after `/voices`).
- Remove dead backend endpoints if truly unused, or wire them: `POST /api/v2/lorebooks/{id}/reindex`, `GET /api/v2/lorebooks/{id}/search`.

### 0.2 ComfyNode widgets uncontrolled (advanced generator is non-functional)
- `ComfyNode.jsx:58-70` uses `defaultValue` and never calls `setNodes` → `WorkflowCompiler.js:7` reads `node.data.widgets` (always `{}`).
- Make widgets controlled: wire `onChange` → `setNodes` with functional update merging into `node.data.widgets`. Update `WorkflowCompiler.compileReactFlowToComfy` to read real values.
- Visual presets (`presets.js`) have empty `widgets: {}` — populate with sane defaults so loading "Standard SDXL" actually configures prompt/seed/size.
- Verify: changing a widget value then compiling produces a prompt that includes the value.

### 0.3 Scenarios Apply uses raw `prompt()` dialogs
- `Scenarios.jsx:99-101` calls browser `prompt('Apply to (chat/story):')` and `prompt('Target ID:')`.
- Replace with an entity-picker modal (reuse the existing `EntityModal.jsx` or build a typed picker). Resolve chat/story by name with a dropdown.

### 0.4 Memories panel unreachable from ChatWorkspace
- `MemoriesPanel.jsx` is complete and tested, only mounted on `Characters.jsx:389`.
- Add a "Memories" tab/button in `ChatContextPanel.jsx` (alongside Lorebooks/Persona) or a toolbar button in `ChatWorkspace.jsx`. Memories are already injected into LLM context via `context_builder.py:519-540` — the UI must let the user manage what the model already sees.

---

## Phase 1 — Infrastructure & unification (cross-cutting)

These make every pillar better and reduce future friction.

### 1.1 API versioning unification
- Frontend mixes `/api/` (providers, jobs, generate, files, collections, prompts, nodes) and `/api/v2/` (world vault, models) hardcoded everywhere — no single helper.
- Add `API_V2_BASE` usage consistently; create the missing `api/settingsApi.js` module so `/api/settings/*` calls stop being inlined across `Settings.jsx`, `useBranding.js`, `useFavorites.js`, `ChatWorkspace.jsx`.
- Decide the canonical split: `/api/v2/` for World Vault + providers + collections + models; legacy `/api/generate`, `/api/files`, `/api/prompts` stay. Document the rule in one place. Update `client.js` if needed. Avoid per-call hard-coded versions going forward.

### 1.2 WebSocket event coverage
- `websocket.js` defines DOWNLOAD_* (4) and MODEL_SYNC_* (4) events with **zero** frontend handlers.
- Add handlers in `useJobsRealtime.jsx` / a new `useModelSync` path so download + model sync progress shows in the provider UI. Wire RECONCILIATION_FAILED (missing from frontend `EventTypes`, exists in backend `events.py:57`).

### 1.3 Error surfacing centralization
- `App.jsx:169-186` QueryClient has no global `onError`; `client.js` has no response interceptor; backend `code` field never reaches users.
- Add a global QueryClient `onError` that toasts unexpected errors, and make `client.js` surface `code` in `extractErrorMessage` (`client.js:31-62`). Ensure `ErrorBoundary` per route already in place (`App.jsx:65-67`) covers crash recovery.

### 1.4 Dependency-injection violations (services ↔ api layer)
- `services/provider_runtime.py:28` imports from `api.routes.worker_ws`; `orchestrator_service.py` + `agent_simulation.py` + `world_integration_service.py` import `api.deps` or `infrastructure.database` directly.
- Refactor to dependency inversion: move `get_session_sync`/`get_session_context` consumers to receive sessions via `api.deps` injection, or extract shared helpers into `infrastructure/deps.py` and have both `api.deps` and services depend on that. Eliminate `services → api.routes` imports.

### 1.5 Dead code cleanup
- `ModelSelector.jsx` (generator) vs `components/model-selector/` (model manager) naming collision — rename one.
- `AvatarGallery.jsx:173` "View all" no-op button — wire or remove.
- `useLLMJobResult.js` only used for auto-title — keep (generic, fine) but verify no dead branches.
- Verify `GeneratorTabs.jsx`, `GeneratorShell.jsx`, `VaeLoraSection.jsx`, `NoCheckpointCTA.jsx`, `PromptCard.jsx` — delete if truly unused.

---

## Phase 2 — Chat Workspace (Roleplay) completeness

### 2.1 Idle simulation actually runs
- Toggle in `ChatContextPanel.jsx:371-391` writes `idle_sim_enabled`, but scheduler only registers the tick when `COMFY_IDLE_SIM_ENABLED` env var is set (`lifecycle.py:258-267`) — no UI path to enable.
- Add a Settings toggle (or startup default) that controls scheduler registration without requiring a raw env var. Add a UI surface to view the offline summary when returning (idle-sim messages arrive as `source="idle_simulation"` with no special styling — add an indicator).

### 2.2 Inline image generation lands inline
- `ChatWorkspaceContext.jsx:696-708` "Illustrate" creates an image job but the result only appears in the Scenes modal, not attached to the message.
- Attach the generated image to the originating message (or show it inline in `MessageItem.jsx`) so the "Illustrate Message" button does what it promises. Keep the gallery copy too.

### 2.3 Branch switching persists
- `ChatWorkspaceContext.jsx:37` `activeBranch` resets to `null` on remount/refresh (`ChatWorkspaceContext.jsx:90`).
- Sync `activeBranch` to URL query param or `localStorage` so branch selection survives navigation and refresh.

### 2.4 Scene progress bar is real
- `ChatContextPanel.jsx:425-434` hardcodes `style={{ width: '60%' }}` with `animate-pulse`.
- Drive it from `sceneStream.jobData?.progress` (the live data already exists above it).

### 2.5 Agentic narration visible
- `orchestrator_service.py:925-927` documents that intermediate narration is NOT persisted as a message; `isNarrator` styling in `MessageItem.jsx:28,235` is unreachable via the narration path.
- Persist narration turns as visible messages (with narrator styling) so the user sees the scene being set, not just the character reply.

### 2.6 Chat-level TTS voice selector
- Per-message voice override exists (`MessageItem.jsx:319-357`); backend accepts `tts_voice_id` in `UpdateChatRequest` (`chats.py:57`). No chat-wide selector.
- Add a voice dropdown in `ChatContextPanel.jsx` that sets `tts_voice_id` for the whole chat.

### 2.7 Unbounded message loads
- `generate_swipe` (`chats.py:629-631`), `rollback_chat` (`chats.py:748-750`), `regenerate_reply` (`chats.py:775-777`), `suggest_reply` (`chats.py:966-968`), `impersonate` (`chats.py:884-886`) load all messages with no limit.
- Cap at a configurable limit (e.g. last N messages, or `MAX_CONTEXT_MESSAGES`-style) to bound memory on long campaigns.

---

## Phase 3 — Story Sandbox completeness

### 3.1 Illustrate → image embed works end-to-end
- `useIllustrateChapter` + `IllustrateModal.jsx` exist; verify the generated image is embedded in the chapter content (not just gallery). Wire the result back into the editor content / chapter body.

### 3.2 Export produces real images
- `stories.py:285-360` builds PDF/vertical strip; prior gray-placeholder fallback was fixed this session (`stories.py:131-157`). Validate on a live story: confirm panels render actual story art, not blanks. If the embed path still fails, harden the fallback and add a per-page illustration generation option.

### 3.3 Parse/import story extracts entities
- `ParseStoryModal.jsx` + `useParseStory` exist. Confirm the LLM extraction workflow runs and creates characters/locations/lorebooks from pasted text. Wire results into the World Vault.

### 3.4 @mention entity picker inserts + resolves
- `MentionPicker.jsx` exists. Verify inserting a mention into the editor resolves to the entity and that the story context panel injects mentioned characters/lore/locations into the continuation prompt.

### 3.5 Story context injection
- `StoryContextPanel.jsx` (genre, description, world state) — confirm these fields actually flow into the story continuation LLM context, not just sit in the UI.

---

## Phase 4 — World Vault completeness

### 4.1 Relationship Graph deep-links to entities
- `RelationshipGraph.jsx:177-182` navigates to the list page, not the specific entity. Add deep-link support (e.g. `#char-{id}` as `Characters.jsx:720-731` does) and make node clicks open the entity.

### 4.2 World Timeline entity pickers
- `WorldTimeline.jsx:90-130` filters are raw text inputs requiring UUIDs. Replace with entity pickups (character/location/story dropdowns) reusing existing picker components.

### 4.3 World Vault search dead code paths
- `world_hub.py:214` search never returns `location`/`branch` types, but `WorldVaultHub.jsx:67-77` `openEntity` handles them. Either implement location/branch search or remove the dead handler branches.

### 4.4 Campaigns server-side search
- `Campaigns.jsx:48-55` search is client-side only. Add a server search endpoint (or confirm client-side is acceptable for single-user scale and document the decision).

### 4.5 Pagination / limits
- `characters.py:178-181` `character_repo.list()` returns all characters; `world_hub.py:68-73` char_chat_links has no limit; `world_hub.py:152-157` voice_links no limit. Add sensible caps + pagination for scale.

### 4.6 Wire unused-but-built endpoints
- `GET /api/v2/characters/{id}/expressions`, `POST /clone`, `GET /export` (`characters.py:259-494`) — add frontend buttons (Clone, Export card, Expressions) or remove if unwanted.

---

## Phase 5 — Generator completeness

### 5.1 ComfyNode widgets (carried from 0.2) — verify end-to-end
- After 0.2, run a primitive node through the full path: edit widget → compile → submit → confirm ComfyUI receives the value.

### 5.2 Batch generate workflow wiring
- `BatchGenerate.jsx:117-120` sends `{ nodes: {}, edges: [] }` relying on backend `WorkflowBuilder` to rebuild. Confirm this is intentional (document) or wire real node graphs.

### 5.3 Empty-model CTAs
- `NoCheckpointCTA.jsx` exists (verify it's imported). When no checkpoints, link to `/models/discover` from all generator variants (`Img2ImgGenerator.jsx`, `InpaintGenerator.jsx`).

---

## Phase 6 — Frontier validation (parallel with Phases 2–5)

These exist but are unverified. Validate and polish, don't rebuild.

### 6.1 RAG autobiographical memory
- Confirm embeddings generate (local SBERT, CPU — watch startup/latency). Confirm recall surfaces in chat/story context. Add a settings toggle + a "why this memory" debug affordance. Surface degradation (keyword fallback) to the user instead of silent.

### 6.2 Idle simulation (backend validation)
- Confirm `lifecycle.py` actually schedules `run_idle_simulation_tick`; verify a chat with `idle_sim_enabled` produces summarized offline activity. (UI side covered in Phase 2.1.)

### 6.3 Animatediff avatar display
- Confirm `VHS_VideoCombine` output path reaches `world_integration_service._handle_avatar_animate` with non-empty `result_paths` and the animated avatar renders in `Characters.jsx`. Needs a live worker run. Gate the "Animate Avatar" button until validated.

### 6.4 Comic/Webtoon export (live validation)
- Covered in Phase 3.2 — confirm on a real story with real images.

---

## Phase 7 — Polish & quality-of-life (ongoing, parallel)

- **Keyboard shortcuts**: Chat `Ctrl+Enter`/`Ctrl+N`, Story `Ctrl+S`/`Ctrl+Shift+C` (`useKeyboardShortcuts.js` exists — verify coverage).
- **Image gallery virtualization**: `@tanstack/react-virtual` for `Dashboard.jsx`.
- **Branding live reactivity**: poll/WS for branding updates without refresh.
- **Drag-and-drop sorting**: `@dnd-kit/sortable` for characters/stories/lorebooks/locations.
- **Prompt Library discoverability**: `/prompts` route exists — verify sidebar link + empty-state CTAs.
- **Statistics cross-pillar**: `Statistics.jsx` ALL/IMAGE/CHAT/STORY filter + World Vault panel (implemented this session — verify live via `curl /api/statistics/detailed | jq .pillars`).
- **E2E in CI**: `frontend-e2e.yml` exists and runs Playwright — confirm it's triggered correctly; remove any duplicate spec blocks.

---

## Verification gates (every phase)

```bash
cd backend_v2 && pytest -q          # must be green
cd frontend_v2 && npm test && npm run lint   # must be green, 0 errors
cd frontend_v2 && npx playwright test        # E2E green (requires stack)
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d   # stack boots
```

## Execution order

```
Phase 0 (P0 broken/missing)  ──→  Phase 1 (infra/unification)
                                        ├─ Phase 2 (Chat)
                                        ├─ Phase 3 (Story)
                                        ├─ Phase 4 (World Vault)
                                        ├─ Phase 5 (Generator)
                                        └─ Phase 6 (Frontiers, parallel)
                                               └─ Phase 7 (Polish, ongoing)
```

Phases 2–6 are largely independent and can run in parallel by different agents; Phase 1 should land first since it reduces friction for all of them.

## Open decisions (confirm during implementation)

1. **Lorebooks UI scope**: full page (like Characters) vs. modal-only? Recommend full page + entry CRUD.
2. **API versioning**: keep legacy `/api/generate` etc. and only standardize new code, or migrate everything to `/api/v2/`? Recommend grandfather legacy, standardize new.
3. **Idle-sim default**: keep scheduler off by default (env-gated) or enable by default? Recommend Settings toggle, default off.
4. **Campaigns search**: client-side acceptable for single-user? Recommend keep client-side, document the scale assumption.
