# TNHComfy — Comprehensive Hardening & Feature-Completeness Plan (2026-08-25)

> **Status**: Investigation complete. Awaiting user decisions on prioritization.
> **Baseline**: Backend 1522 tests pass, Frontend 561 tests pass, both linters clean.
> **Stack**: Running (containers up 38h, healthy).

---

## 0. Executive Summary

TNHComfy has evolved from an image generator into a **Comprehensive AI Fantasy Engine** with three pillars:
1. **Image Generation** (ComfyUI + Modal/Beam providers) — mature, production-ready
2. **Roleplay Chatbots** (SillyTavern-style) — implemented, needs runtime validation
3. **Story Sandbox** (AI Dungeon-style) — implemented, needs runtime validation

**The core architecture is sound.** Most issues found in earlier audits (ROADMAP §10) have already been fixed. The remaining work is:

- **Runtime validation** of Chat/Story/World Vault features (they exist but are unverified end-to-end)
- **Feature completeness** — eliminating the "demo feel" by adding missing affordances
- **E2E test gaps** — 7 pre-existing failures in Relationship Graph & Avatar Gallery
- **Performance polish** — minor N+1 queries, pagination
- **Code hygiene** — dead code removal, deduplication

---

## 1. Unstaged Changes Assessment

**Files modified** (working tree, not staged):
- `frontend_v2/src/components/dashboard/GroupedDashboardContent.jsx`
- `frontend_v2/src/components/dashboard/TimelineView.jsx`
- `frontend_v2/src/pages/Dashboard.jsx`

**What they do**: Fix infinite-scroll jump by saving/restoring `window.scrollY` via `useLayoutEffect` when new items load, plus `overflowAnchor: 'none'` to prevent browser scroll-anchoring interference.

**Verdict**: ✅ **Good fix.** Addresses a real UX issue. No bugs introduced. Recommend committing as:
```
fix: prevent infinite-scroll jump in dashboard timeline/grid views
```

---

## 2. Current State — What's Already Fixed

Earlier audits (ROADMAP §10, REMEDIATION_PLAN_v2, DEMO_GAPS_PLAN) flagged many issues. Investigation shows these are **already resolved**:

| Earlier claim | Actual state |
|---|---|
| `job_workflow` undefined crash | Uses `job.workflow.get("tools")` — valid field |
| StoryReader blob download broken | `data.blob()` works correctly |
| Duplicate `cleanup_orphaned_models` | Only one definition exists |
| Inline `import time` | Module-level import |
| `agent_simulation` loads ALL jobs | Already filters by `chat_id` |
| `reference_cleanup.py` dead code | Imported by 7 route files |
| `useVoices.js` enabled no-op | Removed |
| App.jsx double-subscribe | Derived value, not double-subscribe |
| Dead `moveAsset` | Already removed |
| Comic/webtoon gray placeholders | Real images wired |
| RAG gate + toggle | Implemented |
| Idle sim scheduler | Implemented |
| Orchestrator timeout | `asyncio.wait_for` at 120s |
| `useChatStreaming` missing WS handlers | All 7 event types handled |
| `world_hub` unbounded query | `.limit(200)` applied |

---

## 3. Genuine Remaining Issues (Verified)

### 3.1 E2E Test Failures (Pre-existing)

**7 failures in `new-pages.spec.js`** — Relationship Graph & Avatar Gallery pages.
- Not caused by recent changes
- Need investigation: likely missing data-testid attributes or async loading issues

### 3.2 Feature Completeness Gaps

| Feature | Current State | Missing for "Complete" |
|---|---|---|
| **Chat Workspace** | Send/receive, swipe, branches, agentic tools | Deep-linking to messages, message search, export conversation |
| **Story Sandbox** | Authoring, AI continue, chapters, beats | Collaborative editing hints, word count, reading time |
| **Characters** | CRUD, avatar, expressions, sort_order | Character card export/import (V1/V2/V3 PNG), duplicate character |
| **Lorebooks** | CRUD, entries, search, reindex | Entry testing/simulation, bulk import |
| **Locations** | CRUD, search | Location images, map view |
| **Campaigns** | CRUD, entity linking | Campaign timeline view, session notes |
| **Relationship Graph** | Force-directed visualization | Edit from graph, save layout |
| **World Timeline** | Chronological feed | Create events from timeline |
| **Batch Studio** | Batch generation | Preset management, queue management |

### 3.3 Performance & Scalability

| Issue | Impact | Effort |
|---|---|---|
| `list_chats` / `list_messages` no pagination | Slow with 1000+ chats | Low — add limit/offset |
| `context_builder` N+1 on lorebook entries | Extra DB queries per chat | Low — batch load |
| `RelationshipGraph` 300-iteration physics on main thread | Jank on low-end devices | Medium — web worker or reactflow |
| Gallery loads all assets at once | Memory pressure | Medium — virtualization |

### 3.4 Code Hygiene

| Issue | Location | Action |
|---|---|---|
| Dead `normalizeModalStats`/`mergeModalStats` exports | `useProviderModels.js` | Remove exports (keep for tests) |
| Large monolithic route files | `chats.py` (1249 lines), `stories.py` (1168 lines) | Split into sub-routers |
| Mixed data-access patterns | World vault routes bypass repos | Standardize on repositories |
| `ChatWorkspaceContext.jsx` 944 lines | Context provider | Split into smaller contexts |

---

## 4. Prioritized Implementation Plan

### Phase 0 — Commit & Stabilize (Do First)

**Goal**: Capture current good state, establish clean baseline.

| # | Task | Files | Acceptance |
|---|---|---|---|
| 0.1 | Commit unstaged scroll fix | 3 frontend files | `git commit` with descriptive message |
| 0.2 | Mark ROADMAP.md, DEMO_GAPS_PLAN.md as superseded | 2 docs | Add "SUPERSEDED" header |
| 0.3 | Verify stack health | — | `curl /api/health` → ok, all containers healthy |

### Phase 1 — Runtime Validation (P0, This Week)

**Goal**: Verify every feature works end-to-end, not just in code.

| # | Task | Method | Acceptance |
|---|---|---|---|
| 1.1 | Chat: send message → LLM reply | Manual via UI or API | Reply streams, message persists |
| 1.2 | Chat: swipe, branch, agentic tools | Manual | All flows work |
| 1.3 | Story: author + AI continue | Manual | Chapter grows, context injected |
| 1.4 | Story: export (md/json/epub/comic) | Manual | Files download correctly |
| 1.5 | Characters: CRUD + avatar + expressions | Manual + E2E | All CRUD works |
| 1.6 | Lorebooks: CRUD + search + reindex | Manual + E2E | Entries inject into chat context |
| 1.7 | World Vault: cross-linking | Manual | Campaign ↔ Character ↔ Story links work |
| 1.8 | RAG: embeddings + recall | API check | Embeddings generate, recall surfaces |
| 1.9 | Idle simulation: tick + summary | API check | Offline activity summarized |

### Phase 2 — Feature Completeness (P1, Week 2-3)

**Goal**: Eliminate "demo feel" — make every feature genuinely usable.

| # | Task | Files | Acceptance |
|---|---|---|---|
| 2.1 | **Chat message search** | `chats.py`, `MessageTimeline.jsx` | Search box filters messages by content |
| 2.2 | **Chat export conversation** | `chats.js`, `ChatWorkspaceHeader.jsx` | Export as JSON/MD/PDF button |
| 2.3 | **Character card export/import** | `characters.js`, `Characters.jsx` | Export as PNG (V2/V3), import from PNG |
| 2.4 | **Character duplicate** | `useCharacters.js` | "Duplicate" button clones character |
| 2.5 | **Lorebook entry test/simulate** | `Lorebooks.jsx` | Test entry against sample text |
| 2.6 | **Lorebook bulk import** | `lorebooks.js` | Import entries from JSON/CSV |
| 2.7 | **Story word count + reading time** | `StoryHeader.jsx` | Display word count, estimated reading time |
| 2.8 | **Relationship Graph: edit from graph** | `RelationshipGraph.jsx` | Click node → edit entity, save layout |
| 2.9 | **World Timeline: create events** | `WorldTimeline.jsx` | "Add event" button creates timeline entry |
| 2.10 | **Batch Studio: preset management** | `PresetManager.jsx` | Save/load/delete named batch presets |

### Phase 3 — Performance & Scalability (P1, Week 2-3, parallel with Phase 2)

| # | Task | Files | Acceptance |
|---|---|---|---|
| 3.1 | **Paginate list_chats/list_messages** | `chats.py`, `chat_repo.py` | Add limit/offset, default 50/100 |
| 3.2 | **Batch load lorebook entries** | `context_builder.py` | Single query for all entries |
| 3.3 | **Relationship Graph: web worker** | `RelationshipGraph.jsx` | Physics off main thread |
| 3.4 | **Gallery virtualization** | `DashboardGalleryGrid.jsx` | Virtualize with @tanstack/react-virtual |

### Phase 4 — Code Hygiene (P2, Week 4)

| # | Task | Files | Acceptance |
|---|---|---|---|
| 4.1 | **Remove dead exports** | `useProviderModels.js` | Remove unused exports |
| 4.2 | **Split chats.py** | `chats.py` → `chats/send.py`, `chats/history.py`, `chats/branches.py` | Smaller files, same functionality |
| 4.3 | **Split stories.py** | `stories.py` → `stories/chapters.py`, `stories/export.py` | Smaller files, same functionality |
| 4.4 | **Standardize data access** | World vault routes | All go through repositories |
| 4.5 | **Split ChatWorkspaceContext** | `ChatWorkspaceContext.jsx` | Separate into MessageContext, StreamingContext, UIContext |

### Phase 5 — E2E Test Coverage (P2, Week 4)

| # | Task | Files | Acceptance |
|---|---|---|---|
| 5.1 | **Fix 7 E2E failures** | `new-pages.spec.js` | All pass |
| 5.2 | **Add Chat E2E tests** | `e2e/chat-workspace.spec.js` | Send, swipe, branch tests |
| 5.3 | **Add Story E2E tests** | `e2e/story-workspace.spec.js` | Author, continue, export tests |
| 5.4 | **Add World Vault E2E tests** | `e2e/world-vault-crud.spec.js` | CRUD for all entities |

---

## 5. Decisions Needed

Before implementation begins, I need your input on:

### 5.1 Priority
Which phase matters most to you right now?
- **Option A**: Phase 1 (validation) first — confirm everything works before adding features
- **Option B**: Phase 2 (features) first — add missing features immediately
- **Option C**: Parallel — validation + features simultaneously

### 5.2 Scope
Should we focus on one pillar at a time, or work across all three?
- **Option A**: Chat first → Story → World Vault
- **Option B**: All pillars in parallel

### 5.3 Feature Priorities
Which features would most improve your daily use?
- Chat message search?
- Character card export/import?
- Story export (epub/comic)?
- Relationship Graph interactivity?
- Something else?

### 5.4 Performance
Is performance a current pain point, or can it wait?
- Gallery virtualization (for large image collections)
- Chat/message pagination (for long campaigns)
- Relationship Graph smoothness

---

## 6. Verification Gates (Every Phase)

```bash
# Backend
cd backend_v2 && pytest -q && ruff check .

# Frontend
cd frontend_v2 && npm test && npm run lint

# E2E (stack running)
cd frontend_v2 && npx playwright test --project=chromium

# Full stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V
```

---

## 7. Out of Scope (Confirmed)

- **Audio/TTS**: Fully wired but gated by `ttsEnabled=false`. Keep off by default.
- **Multi-tenancy/Auth**: Single-user by design. Deferred.
- **Video/Animation**: AnimateDiff implemented but unverified. Deferred to Phase 1 validation.
- **Visual Novel Mode**: Future frontier. Not now.

---

## 8. Risk Assessment

| Risk | Likelihood | Mitigation |
|---|---|---|
| Runtime validation reveals major bugs | Medium | Phase 0 establishes clean baseline first |
| Feature scope creep | High | Strict phase boundaries, user decisions at each gate |
| E2E test flakiness | Medium | Use data-testid, explicit waits, retry logic |
| Performance regressions | Low | Benchmark before/after, pagination is safe |

---

## 9. Recommended Starting Point

1. **Commit the unstaged scroll fix** (5 minutes, clean win)
2. **Run Phase 1.1** (Chat validation) — if Chat works, the LLM pipeline is healthy
3. **Based on results**, proceed to Phase 2 features or fix issues first

Awaiting your decisions on priority, scope, and feature preferences before proceeding.
