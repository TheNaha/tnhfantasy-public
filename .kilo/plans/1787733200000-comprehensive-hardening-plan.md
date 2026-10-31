# TNHFantasy Comprehensive Hardening & Feature Completeness Plan

> Created: 2026-08-27
> Supersedes: All prior plans (PLAN.md, ROADMAP.md, REMEDIATION_PLAN*.md, existing .kilo/plans/*)
> Authority: This document is the single source of truth for remaining work.

---

## 1. Git Status Assessment

**Branch:** `master`, 3 commits ahead of `origin/master`

| Commit | Description | Verdict |
|--------|-------------|---------|
| `7b2e844` | Shared Modal shell + migrate collection modals | ✅ Clean — well-structured extraction |
| `b7de898` | Split ChatWorkspace god-context into data + mutations sub-hooks | ✅ Clean — good decomposition |
| `04fcc59` | Timeline click-through to source entities + load-more pagination | ✅ Clean — useful UX improvement |

**No unstaged/staged changes.** Working tree clean.

**Untracked files:** `list-models-full.txt`, `list-models.txt`, `test.py` — personal utility scripts, not project code. No action needed.

**Recommendation:** These 3 commits are ready to push. No issues found.

---

## 2. Test & Lint Status

| Check | Status | Notes |
|-------|--------|-------|
| Frontend `npm test` | ✅ 603 pass / 77 files | Clean |
| Frontend `npm run lint` | ✅ 0 errors | Clean |
| Backend `ruff check` | ✅ All checks passed | Clean |
| Backend `pytest` | ❌ Collection error | `PermissionError: data/pgdata` — Docker-owned directory, not a code issue |

---

## 3. Investigation Summary

### Methodology
- Parallel exploration agents examined: backend services, frontend components/hooks, World Vault entities/routes
- Verified imports across the codebase to confirm dead code vs. actually-used code
- Cross-referenced ROADMAP.md claims against actual code state

### What's Working Well
- Context builder is canonical — all LLM calls route through it consistently
- SillyTavern compatibility (PNG import/export, JSONL, lorebook JSON)
- Agentic tool use wired and gated by feature flags
- RAG pipeline with pgvector + keyword fallback
- Branching (chat + story beats) fully implemented
- Chat swipe regeneration, group chat, personas, author's note
- Story chapter/beat/revision/AI-action system
- Relationship graph with zoom/pan/drag/save layout
- Timeline with filtering and click-through
- All lazy-loaded pages wrapped in ErrorBoundary
- TTS properly gated behind settings flag

---

## 4. Prioritized Remediation Plan

### Phase 0 — Critical Fixes (P0) — Do First

| # | Issue | File | Fix |
|---|-------|------|-----|
| 0.1 | **StoryReader markdown export crashes** — `api.get()` returns raw `Response` for non-JSON content types; `data.content` is `undefined`, producing empty Markdown download | `frontend_v2/src/pages/StoryReader.jsx:45-48` | For `md`/`markdown` format, call `await data.text()` and build the Blob from the text body. Verify `client.js` `responseType` handling. |

---

### Phase 1 — High Priority (P1) — Current Sprint

#### 1.1 Backend Correctness & Performance

| # | Issue | File | Fix |
|---|-------|------|-----|
| 1.1.1 | **`job.workflow` None-dereference** — agentic branch crashes if workflow is null | `backend_v2/services/job_processing.py:413` | Change to `(job.workflow or {}).get("tools")` |
| 1.1.2 | **Unbounded `list_active()` stories** — no pagination, loads all non-archived stories | `backend_v2/api/routes/world_vault/stories.py:191`, `infrastructure/repositories/story_repo.py:10` | Add `limit`/`offset` params; cap at 100 default |
| 1.1.3 | **Unbounded full-table scans on entity delete** — `reference_cleanup.py` loads every Story/Chat/Campaign/Message/Character row | `backend_v2/services/reference_cleanup.py:21-58` | Replace with SQL-level `UPDATE ... WHERE id = ANY(character_ids)` or `array_remove()` |
| 1.1.4 | **Duplicate `get_file_priority`** — copy-pasted scoring logic | `infrastructure/repositories/model_repo_v2.py:158,274` | Extract to module-level function |
| 1.1.5 | **Duplicate 3-table join** — `get_all_storage_paths` / `get_file_ids_by_storage_paths` | `infrastructure/repositories/model_repo_v2.py:1325,1345` | Factor join into `_iter_file_model_paths` helper |

#### 1.2 Entity Relationship Gaps (Schema + Migrations)

| # | Issue | File | Fix |
|---|-------|------|-----|
| 1.2.1 | **`Story.scenario_id` has no FK** — deleting scenario orphans stories | `backend_v2/core/entities.py:1014` | Add `ForeignKey("scenarios.id")` + migration |
| 1.2.2 | **`Story` uses JSON arrays** for character_ids/lorebook_ids/location_ids — no relational integrity | `backend_v2/core/entities.py:1011-1013` | Consider join tables for Story↔Character, Story↔Lorebook (or document acceptance of JSON arrays for single-user scope) |
| 1.2.3 | **`Campaign` uses JSON arrays** — same integrity issue | `backend_v2/core/entities.py:1097-1100` | Same approach as Story |
| 1.2.4 | **`Scenario` missing columns** — frontend sends `default_checkpoint`/`default_voice_profile`, backend drops them | `backend_v2/core/entities.py:986-993`, `frontend_v2/src/pages/Scenarios.jsx:22` | Add columns to entity + migration |

#### 1.3 Feature Completeness — Backend

| # | Issue | File | Fix |
|---|-------|------|-----|
| 1.3.1 | **No expression CRUD routes** — `ExpressionSelector` sends unsupported `active_expression` field, no way to add/remove expressions | `backend_v2/api/routes/world_vault/characters.py`, `frontend_v2/src/components/chat/ExpressionSelector.jsx:29` | Add `POST/PUT/DELETE /{id}/expressions` routes; wire frontend to real CRUD |
| 1.3.2 | **LorebookEntry lacks category/tags/depth** — only trigger keys exist, no taxonomy | `backend_v2/core/entities.py:970-984` | Add `category`, `tags`, `depth` columns + migration; update frontend Lorebooks.jsx |
| 1.3.3 | **No auto-memory generation** — CharacterMemory rows only created manually, no extraction from chat/story | `backend_v2/services/rag_pipeline.py`, `backend_v2/core/entities.py:937` | Implement background job: after N messages or chat end, run LLM summarization → create CharacterMemory entries |

#### 1.4 Frontend Correctness & Performance

| # | Issue | File | Fix |
|---|-------|------|-----|
| 1.4.1 | **Over-broad `useSettings()` subscription** — App re-renders on every settings change globally | `frontend_v2/src/App.jsx:169` | Use granular selectors: `useSettingsStore((s) => s.settings.ui)` |
| 1.4.2 | **Dead exports bloat bundle** — `normalizeModalStats`/`mergeModalStats` only used in tests | `frontend_v2/src/hooks/useProviderModels.js:101,114` | Remove exports; move to test utils if needed |
| 1.4.3 | **20+ modals duplicate backdrop/animation code** — despite shared `Modal.jsx` existing | Multiple files | Migrate remaining modals to shared `Modal`/`EntityModal` components |
| 1.4.4 | **Timeline memory events navigate to `/characters` list** instead of specific character | `frontend_v2/src/pages/WorldTimeline.jsx:94` | Navigate to `/characters#char-{character_id}` |

---

### Phase 2 — Medium Priority (P2) — Parallel Track

#### 2.1 Frontend Polish & UX

| # | Issue | File | Fix |
|---|-------|------|-----|
| 2.1.1 | **No message-content search in chat workspace** — `useMessages` accepts search param but no UI input | `frontend_v2/src/pages/ChatWorkspace.jsx`, `useMessages.js:13` | Add message search input to chat sidebar |
| 2.1.2 | **No auto-save indicator in StorySandbox** — auto-save happens but no visual feedback | `frontend_v2/src/pages/StorySandbox.jsx:296` | Add "Saving…" / "Saved" status indicator |
| 2.1.3 | **No word count goal enforcement** — goal displayed but never warns or blocks | `frontend_v2/src/pages/StorySandbox.jsx:92` | Add visual warning when exceeding goal, optional hard block |
| 2.1.4 | **Campaign dashboard read-only** — cannot add/remove linked entities from modal | `frontend_v2/src/pages/Campaigns.jsx:400` | Add inline add/remove controls for linked entities |
| 2.1.5 | **No relationship creation UI in graph** — read-only visualization | `frontend_v2/src/pages/RelationshipGraph.jsx` | Add "link entities" mode or drag-to-connect |
| 2.1.6 | **World hub caps stories at 200** — large vaults get incomplete graphs | `backend_v2/api/routes/world_vault/world_hub.py:81` | Increase to 500 or make configurable |
| 2.1.7 | **Chat JSONL import drops swipe metadata** — alternates lost on re-import | `backend_v2/api/routes/world_vault/chats.py:334` | Map `swipes`/`swipe_id` fields in import handler |

#### 2.2 Code Cleanup

| # | Issue | File | Fix |
|---|-------|------|-----|
| 2.2.1 | **`useVoices` `characterId` param never used** — all call sites pass default `null` | `frontend_v2/src/hooks/useVoices.js:4` | Remove parameter, simplify to parameterless query |
| 2.2.2 | **`useGenerationPreflight` dead placeholder query** — `enabled: false` no-op | `frontend_v2/src/hooks/useGenerationPreflight.js:20` | Remove dead `useQuery` block |
| 2.2.3 | **`useLLMJobResult` claims cache sharing but never writes** — doc/behavior mismatch | `frontend_v2/src/hooks/useLLMJobResult.js:76` | Write final job state to cache or fix documentation |
| 2.2.4 | **`refetchOnWindowFocus: true` override** — contradicts global `false` default | `frontend_v2/src/hooks/useProvidersPageData.js:306` | Remove override or justify with comment |
| 2.2.5 | **Dead `extractProviderId` re-export** — consumers import from `providerUtils.js` directly | `frontend_v2/src/hooks/useProviderModels.js:6` | Remove re-export |

#### 2.3 Performance

| # | Issue | File | Fix |
|---|-------|------|-----|
| 2.3.1 | **Unbounded Message fetch** — loads all chat messages with no cap | `backend_v2/services/world_integration_service.py:64` | Add `.limit(200)` |
| 2.3.2 | **Unbounded Message fetch in narrator tool** | `backend_v2/services/orchestrator_service.py:458` | Add `.limit(200)` |
| 2.3.3 | **Unbounded Job query on startup** — loads all active jobs into memory | `backend_v2/services/load_balancer.py:199` | Add `.limit(1000)` or count-only query |
| 2.3.4 | **O(n×m) version matching in CivitAI sync** — linear scan per version | `backend_v2/services/model_civitai_sync.py:180` | Build lookup dicts before loop |
| 2.3.5 | **`except Exception:` without `as exc`** — loses exception context | `backend_v2/services/world_integration_service.py:451` | Change to `except Exception as exc:` |

---

### Phase 3 — Component Decomposition (Ongoing)

These are large extractions that improve maintainability but aren't urgent:

| Component | Lines | Extraction Target |
|-----------|-------|-------------------|
| `StorySandbox.jsx` | 1,142 | `StoryHeader`, `StoryEditorContainer`, `StoryBeatsPanel`, `StoryActionBar` → `components/story/` |
| `Settings.jsx` | 1,130 | Tab components per category (AI, Gallery, Models, Generator, Branding) → `components/settings/` |
| `Characters.jsx` | 1,016 | `CharacterModal`, `CharacterCard` → `components/characters/` |
| `Statistics.jsx` | 657 | `ContributionHeatmap`, `CustomTooltip`, chart sections → `components/statistics/` |
| `RelationshipGraph.jsx` | 601 | `EditPanel`, `FilterBar` → `components/graph/` |
| `Lorebooks.jsx` | 580 | `LorebookEntryForm`, `EntryList` → `components/lorebook/` |

---

### Phase 4 — Feature Completeness Hardening (Post-P1)

These address the "demo-like" feel — features that exist but lack depth for daily use:

| Feature | Gap | Action |
|---------|-----|--------|
| **Character Expressions** | No CRUD, no sheet upload | Full expression management with image upload |
| **Lorebook Depth/Distance** | Hardcoded `depth: 4` in export, ignored on import | Per-entry depth config + import parsing |
| **Location Images** | Text field only, no upload | Image upload endpoint + frontend picker |
| **Batch Character Import** | Single PNG only | Multi-file import (zip of PNGs) |
| **Memory Decay** | `last_accessed_at` tracked but no background job | Scheduled job to adjust importance / archive stale memories |
| **Campaign ↔ Lorebook/Scenario** | Not linkable | Extend JSON arrays or join tables |
| **Story PDF Export** | Only comic PDF + webtoon PNG | Add clean PDF export (markdown → PDF) |
| **Chat Message Search** | Backend supports `q` param, no UI | Search input in chat sidebar |
| **Relationship Graph Creation** | Read-only | Add/link entities from graph UI |
| **Animatediff Avatar Display** | Backend fixed, frontend display unverified | Verify animated avatar renders in Characters.jsx |
| **RAG Recall Quality** | Implemented but unverified | Live test with real embeddings, add "why this memory?" debug |
| **Idle Simulation** | Implemented but unverified | Confirm lifecycle scheduling, verify summary UI |

---

## 5. Verification Gates (Every Phase)

```bash
# Frontend
cd frontend_v2 && npm test && npm run lint

# Backend lint
ruff check backend_v2/

# Backend tests (requires Docker stack down or permission fix)
cd backend_v2 && pytest

# E2E (stack running)
cd frontend_v2 && npx playwright test

# Full stack spin-up
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d
```

---

## 6. Execution Order Recommendation

```
Phase 0 (P0) — Immediate
  └─ Fix StoryReader markdown export crash

Phase 1 (P1) — Current Sprint
  ├─ 1.1 Backend correctness (job.workflow None, pagination, ref cleanup)
  ├─ 1.2 Entity FKs + missing columns
  ├─ 1.3 Feature completeness (expressions, lorebook taxonomy, auto-memories)
  └─ 1.4 Frontend correctness (settings subscription, dead exports, modal migration)

Phase 2 (P2) — Parallel after Phase 1
  ├─ 2.1 Frontend polish (search, save indicator, word count, campaign, graph)
  ├─ 2.2 Code cleanup (dead params, dead queries, doc mismatches)
  └─ 2.3 Performance (unbounded queries, O(n×m) matching)

Phase 3 — Ongoing (opportunistic decomposition)

Phase 4 — Post-P1 feature hardening
```

---

## 7. Key Decisions (Resolved 2026-08-27)

| # | Question | Decision |
|---|----------|----------|
| 1 | **Story/Campaign JSON arrays vs. join tables** | ✅ **Refactor to join tables** — proper many-to-many with relational integrity |
| 2 | **Auto-memory generation scope** | ✅ **At chat end** — run LLM summarization when a chat session ends |
| 3 | **Component decomposition priority** | ✅ **As touched** — opportunistic decomposition when working in those areas |
| 4 | **Lorebook depth/distance** | ✅ **Full SillyTavern parity** — depth, selectiveLogic, probability, caseSensitive, etc. |

---

## 8. Non-Exhaustive: Ideas for Improvement

These emerged during investigation but weren't deeply validated:

- **Image gallery virtualization** for Dashboard.jsx (`@tanstack/react-virtual`) — flagged in old plans, still not done
- **Branding live reactivity** — poll/WS for branding updates without refresh
- **Keyboard shortcuts** — Chat `Ctrl+Enter`/`Ctrl+N`, Story `Ctrl+S` (partially present)
- **Statistics cross-pillar analytics** — workspace filter + chat/story/LLM analytics (partially done)
- **Prompt Library discoverability** — `/prompts` route exists but sidebar link may be missing
- **Drag-and-drop sorting** — characters have `sort_order`, but stories/lorebooks/locations may need it too
- **Settings save flow clarity** — `handleSaveAiBackend` is disconnected from `useSettings` mutations; users may not realize they need to click "Save to Backend" separately
- **Load Balancer refactor** — class-level mutable state flagged as risk; instance-based singleton with `asyncio.Lock` recommended
- **API versioning unification** — mix of `/api/`, `/api/v2/`, `/api/settings/` etc.; standardize on `/api/v2/` for World Vault + providers + collections
