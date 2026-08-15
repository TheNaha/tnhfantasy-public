# TNHComfy Master Plan — Remediation + 8 Major Features

## Executive Summary

TNHComfy is architecturally solid with a massive implementation sprint already completed. This plan organizes the **remaining remediation work** alongside **8 major new features** into a coherent, dependency-aware roadmap. Work proceeds in phases; each phase produces a test-passed, reviewable increment.

---

## Guiding Principles

1. **Remediation and new features proceed in parallel**, not sequentially. Fix critical bugs while building foundations.
2. **Every phase must pass `pytest` and `npm test`** before moving to the next.
3. **Features are built behind feature flags** where appropriate, so incomplete work never breaks the UX.
4. **Component decomposition happens opportunistically** — extract abstractions when you touch a file, not as a separate chore.

---

## Phase 0: Critical Fixes (Week 1)

> Zero new features. Fix bugs and broken integrations first.

| # | Issue | Action |
|---|-------|--------|
| 0.1 | Blurhash test fails in CI (missing `blurhash` package) | Add `blurhash` to `requirements.txt` or skip test with `@pytest.mark.skipif` |
| 0.2 | TTS UI is visible but feature is deferred | Gate TTS buttons/audio behind `settings.ai.ttsEnabled` feature flag. Hide in `MessageItem.jsx`, `ChatWorkspace.jsx` |
| 0.3 | Provider config JSON blob anti-pattern | Migration step: extract `reconciliation_state` into `ProviderReconciliationState` table |
| 0.4 | `services/provider_runtime.py` imports from `api.deps` | Move `get_session_sync` / `get_container_manager` to `infrastructure/deps.py` |
| 0.5 | Duplicate `read_png_metadata` / `read_image_metadata` | Consolidate into single `read_image_metadata` in `infrastructure/image_processor.py` |

---

## Phase 1: Foundation (Week 2–3)

> Lay groundwork for Campaign, Timeline, RAG, and Graph features.

| # | Task | Action |
|---|------|--------|
| 1.1 | **Location Entity System** | Add `Location` table + CRUD routes + frontend page. This is the foundation for Campaign, Timeline, and World Graph. |
| 1.2 | Query key constants | Create `frontend_v2/src/constants/queryKeys.js` and migrate hooks |
| 1.3 | Error boundaries per page | Wrap each lazy-loaded page in `ErrorBoundary` |
| 1.4 | Settings Toggle/Slider components | Extract reusable UI primitives |
| 1.5 | Frontend logging bridge | Replace scattered `console.error`/`console.warn` with centralized logger |

---

## Phase 2: Batch A — Self-Contained Features (Week 4–5)

> Build features with minimal dependencies on other new work.

| # | Feature | Description | Dependencies |
|---|---------|-------------|--------------|
| 2.1 | **Character Avatar Gallery / Showcase** | Dedicated page showing all character avatars, generated scenes, expression sheets. Quick-jump to chat/story. | None — uses existing `Character`, `Collection`, `Asset` |
| 2.2 | **Enhanced Comic / Webtoon Export** | Add webtoon (vertical scroll) and comic PDF export formats to story export. Uses `img2pdf` + PIL on backend. | Existing story export infrastructure |
| 2.3 | **Batch Generation Studio** | UI for generating character sheets, scene variations, concept grids. Uses existing `POST /api/generate/batch`. | None — uses existing batch endpoint |

---

## Phase 3: Batch B — Connected Features (Week 6–7)

> Features that depend on Location entity and each other.

| # | Feature | Description | Dependencies |
|---|---------|-------------|--------------|
| 3.1 | **World Timeline** | Chronological aggregation of all events (messages, beats, images, memories). Filterable by character/location/story/chat. | Location entity (1.1) |
| 3.2 | **Campaign / Chronicle Mode** | `Campaign` entity linking stories, chats, characters, locations. Dashboard with campaign timeline, shared lore, resume view. | Location entity (1.1), World Timeline (3.1) |
| 3.3 | **Relationship Graph UI** | Interactive node graph of characters, locations, lorebooks, stories. Uses `reactflow` on frontend, existing `/relationships` endpoint. | World Vault Hub relationships endpoint (already exists) |

---

## Phase 4: Batch C — Deep Integration (Week 8–9)

> Feature requiring deep changes to core systems.

| # | Feature | Description | Dependencies |
|---|---------|-------------|--------------|
| 4.1 | **Autobiographical Memory (RAG)** | Auto-embed chat messages + story beats into pgvector. Retrieve relevant memories in `context_builder.py`. | Memories system (already exists), pgvector (already exists) |

---

## Phase 5: Ongoing Polish (Parallel to Phases 2–4)

| # | Task | Action |
|---|------|--------|
| 5.1 | Component decomposition | `ChatWorkspace.jsx` → `ChatSidebar` + `ChatStream` + `ChatInput`. `StorySandbox.jsx` → `StoryNavigation` + `StoryEditorContainer`. `Dashboard.jsx` → `DashboardGallery` + `DashboardFilters`. |
| 5.2 | Drag-and-drop sorting | Add `@dnd-kit/sortable` to characters, stories, lorebooks, locations lists |
| 5.3 | Playwright CI | GitHub Actions workflow for E2E tests on `frontend_v2/**` changes |
| 5.4 | Prompt Library discoverability | Add `/prompts` route + sidebar link |
| 5.5 | Statistics cross-pillar | Add workspace filter + chat/story/LLM analytics to Statistics page |
| 5.6 | Startup filesystem scan optimization | Persist cursor or async migration for `asset_reconciler.move_existing_assets` |
| 5.7 | Image gallery virtualization | `@tanstack/react-virtual` for `Dashboard.jsx` |
| 5.8 | Branding live reactivity | Poll/WS for branding updates without refresh |
| 5.9 | Keyboard shortcuts | Chat: `Ctrl+Enter`, `Ctrl+N`. Story: `Ctrl+S`, `Ctrl+Shift+C` |
| 5.10 | LoadBalancer refactor | Instance-based singleton with `asyncio.Lock` |

---

## Implementation Order (Recommended)

```
Phase 0 (Week 1)
  └─ Phase 1 (Week 2-3)
       ├─ Phase 2.1 Avatar Gallery (Week 4)
       ├─ Phase 2.2 Comic Export   (Week 4)
       ├─ Phase 2.3 Batch Gen      (Week 5)
       ├─ Phase 3.1 World Timeline (Week 6)
       ├─ Phase 3.2 Campaign       (Week 6-7)
       ├─ Phase 3.3 Relationship Graph (Week 7)
       ├─ Phase 4.1 RAG            (Week 8-9)
       └─ Phase 5 polish           (ongoing)
```

---

## File Impact Map

### New Files (Major Features)
| Feature | New Backend Files | New Frontend Files |
|---------|-------------------|-------------------|
| Location Entity | `api/routes/world_vault/locations.py`, `core/entities.py` additions, migration steps | `src/pages/Locations.jsx`, `src/hooks/useLocations.js` |
| Avatar Gallery | None (reuses existing) | `src/pages/AvatarGallery.jsx`, `src/components/character/AvatarShowcase.jsx` |
| Comic/Webtoon Export | `api/routes/world_vault/stories.py` additions | `src/components/story/ExportModal.jsx` expansions |
| Batch Generation | `api/routes/batch_generation.py` or extend `generation.py` | `src/pages/BatchGenerate.jsx`, `src/components/generator/BatchStudio.jsx` |
| World Timeline | `api/routes/world_vault/timeline.py` | `src/pages/WorldTimeline.jsx`, `src/components/timeline/TimelineView.jsx` |
| Campaign Mode | `api/routes/world_vault/campaigns.py`, `core/entities.py` additions | `src/pages/Campaigns.jsx`, `src/components/campaign/CampaignDashboard.jsx` |
| Relationship Graph | None (reuses `/relationships`) | `src/pages/WorldGraph.jsx`, `src/components/graph/RelationshipGraph.jsx` |
| RAG Memory | `services/rag_pipeline.py`, `services/context_builder.py` additions | None (backend-only feature) |

### Modified Files (Major)
| File | Why |
|------|-----|
| `backend_v2/core/entities.py` | Add `Location`, `Campaign`, `CampaignMember`, `CharacterStats`, `InventoryItem` |
| `backend_v2/infrastructure/migrations/steps.py` | New migration steps for all new entities |
| `backend_v2/api/routes/world_vault/__init__.py` | Register new routers (locations, campaigns, timeline) |
| `backend_v2/services/context_builder.py` | RAG retrieval, location-aware context |
| `backend_v2/services/orchestrator_service.py` | Location-aware tool calls, campaign context |
| `frontend_v2/src/App.jsx` | New routes |
| `frontend_v2/src/components/Layout.jsx` | New sidebar nav items |
| `frontend_v2/src/hooks/useWorldVault.js` | Barrel exports for new hooks |

---

## Verification Plan

### Per-Phase Gates
- **Backend**: `cd backend_v2 && pytest` — all tests pass
- **Frontend**: `cd frontend_v2 && npm test` — all tests pass
- **Lint**: `ruff check .` + `npm run lint`
- **E2E**: `npx playwright test` — existing tests pass + new tests for feature

### Manual Verification Checklist
- [ ] Location CRUD works; locations appear in chat context panel
- [ ] Avatar Gallery shows all characters with avatars/scenes
- [ ] Comic/Webtoon export produces valid files
- [ ] Batch Generation produces multiple images in one job
- [ ] World Timeline shows events across all entity types
- [ ] Campaign links stories/chats/characters correctly
- [ ] Relationship Graph is interactive and accurate
- [ ] RAG memories surface in chat context when relevant

---

## Quick Reference: Commands

```bash
# Full stack spin-up
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d

# Backend only
cd backend_v2 && .venv/bin/pip install -r requirements.txt && .venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8002 --reload

# Frontend only
cd frontend_v2 && npm install && npm run dev -- --host 0.0.0.0 --port 5174

# Tests
cd backend_v2 && pytest
cd frontend_v2 && npm test
cd frontend_v2 && npx playwright test
```

---

## Risk Register

| Risk | Mitigation |
|------|-----------|
| Scope too large | Strict phase gating. Each phase is independently shippable. |
| Database migrations fail | Test migrations on both SQLite and PostgreSQL before merging |
| Frontend bundle bloat | Lazy-load new pages. Monitor bundle size in CI. |
| RAG embedding costs | Optional/cached embeddings. Graceful SQLite fallback. |
| Comic export performance | Async generation with progress indicator. Stream large exports. |

---

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Build Location entity first | Foundational for Campaign, Timeline, and future features |
| Relationship Graph reuses existing `/relationships` endpoint | Avoids duplicating backend work; frontend-only feature |
| RAG in Phase 4 (last) | Deeply integrated; benefit is highest when other features are stable |
| Comic export uses backend generation | Keeps frontend light; backend already has PIL + image processing |
| Campaign uses join tables, not JSON arrays | Proper relational modeling; easier queries and migrations |
| All new features gated behind routes/nav | No unused code paths; discoverable but not intrusive |
