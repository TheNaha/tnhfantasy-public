# TNHFantasy — Feature-Completeness & Hardening Plan

> **Status:** Implementation-ready. Supersedes `ROADMAP.md` (2026-08-24), which is **stale** — most of its Track A (P0/P1/P2) backend items are already fixed in HEAD. This plan is based on a fresh code audit + live test runs performed 2026-08-24.

## 1. Investigation summary (verified, not assumed)

- **Test baselines (run live):** backend `pytest` → **1515 passed / 6 skipped**; frontend `npm test` → **561 passed / 0 failed**; `npm run lint` → 0 errors. The "demo-like" complaint is a **runtime feature-completeness** problem, not test breakage.
- **E2E is already in CI** via `.github/workflows/frontend-e2e.yml` (triggers on push/PR to `main`/`master` for `frontend_v2/**` + `backend_v2/**`, uses `pgvector/pgvector:pg16`). The ROADMAP claim "E2E not in CI" is **false**.
- **Many ROADMAP items already fixed in HEAD** (do NOT redo): AnimateDiff double-wrap + test; TTS enable banner; RAG gate + toggle + test; `useEntityCRUD.js` deleted; `useVoices.js` enabled no-op removed; `useChatStreaming` handles `JOB_CREATED`/`JOB_UPDATED`/`JOB_POST_PROCESSING`; `world_hub` story limit 200 + dangling-link flag; `orchestrator_service` 120s top-level `asyncio.wait_for` + removed `report_failure` on mode mismatch; `stories` comic/webtoon embeds real images + title fix; Statistics cross-pillar filter; duplicate `cleanup_orphaned_models` removed; inline `import time` removed; `StoryReader` already calls `data.blob()`; only one `ModelSelector.jsx` exists (no collision); `App.jsx` uses `useSettings()` only (no double-subscribe); `normalizeModalStats`/`mergeModalStats` are tested (not dead); `moveAsset` already removed; `world-vault-hub.spec.js` duplicate already removed; `agent_simulation` already filters jobs by `chat_id`; `model_reconciliation` already guards `startswith("models/")`.
- **Genuinely open items found:** `reference_cleanup.py` is dead code (zero importers); frontend still mixes `/api` (40) vs `/api/v2` (128) call sites (P2, not breaking).

## 2. Git findings (per your note 3)

- **Main repo:** working tree clean. You are **1 commit ahead of `origin/master`** — `b61538d` "fix: update PostgreSQL image to pgvector for E2E tests and remove unused cleanup method" (legit fix). I will **not push** without explicit request.
- **Stale agent worktrees:** ~14 worktrees exist, including `comfyui.worktrees/agents-i-would-like-you-to-check-the-entirety-5eae8f03` which has **uncommitted changes** (`lifecycle.py`, `statistics.py`, `files.py` bare-`except`→typed-except cleanups, `+41` docker-compose.yml, `useStore.js` removal, docs). These are cosmetic/cleanup and not merged.
- **Action:** Phase 0 reconciles this (review/prune), but I will not push or force-merge without your go-ahead.

## 3. Scope & decisions

- **Live Modal/Beam credentials are available** → Phase 2 validates **real** image generation end-to-end (not fallback).
- **Primary goal:** make the 3 pillars + vision frontiers genuinely usable end-to-end for a casual/power user (you), eliminating the "demo-like" gaps. Secondary: unify/clean a few real loose ends.
- **Out of scope:** net-new frontier features beyond what already exists; multi-tenancy; performance rewrites that aren't needed for a single-user workload.

## 4. Phased plan

### Phase 0 — Git & worktree reconciliation (housekeeping)
1. Report (do not push) the 1 unpushed commit `b61538d`; confirm it is correct/safe to keep.
2. Review the uncommitted diff in `agents/...` worktree; either fold the cosmetic cleanups into a `chore/lint-cleanup` branch or discard — **ask before merging**.
3. Prune the ~13 stale subagent worktrees (`git worktree remove` / `git worktree prune`) to declutter. Confirm none hold unique work first.

### Phase 1 — Close genuine remaining code issues (low risk, verified open)
4. `backend_v2/services/reference_cleanup.py`: delete (dead) **or** wire into entity-deletion flows (characters/stories/locations). Pick one; add a test.
5. **API versioning helper:** add a single `API_BASE`/version constant in `frontend_v2/src/api/client.js`; migrate the 40 legacy `/api/...` call sites to go through it (keep legacy `/api/generate|/files|/prompts|/view|/thumbnail` working). Avoid per-call hardcoded versions. Files: `collectionsApi.js`, `providers.js`, `useLLMProviderStatus.js`, `useFavorites.js`, `useBranding.js`, `useLLMJobResult.js`, `files.js`, `generate.js`.

### Phase 2 — Runtime feature-completeness validation (the "demo-like" fix) — REQUIRES full stack
Bring the stack up exactly as you specified:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V
```
Then walk each pillar in the browser + drive with Playwright (creds live). For every item below: if it works, mark verified; if it's stubbed/broken/incomplete, fix it and add a regression test/spec. Output a per-item pass/fail log.

**2A. Chat Workspace (Roleplay)**
- Send message → assistant LLM reply end-to-end with a configured provider.
- Swipe between generations; branch create/switch UI (`MessageTimeline`).
- Inline image generation per message → result appears in-thread; **agentic tool flow** (`generate_image`/`narrate_scene`/`update_world_state`) actually produces in-thread results.
- In-chat "Enable narration" affordance when `settings.ai.ttsEnabled` is false (banner/button → flips setting via Settings endpoint).
- Chat sidebar CRUD (create / switch / delete) — currently only direct-URL nav exists per ROADMAP 4.1.4.

**2B. Story Sandbox**
- Authoring + AI "continue" works; `illustrate → batch variations` flow wired.
- Export modal (`md`/`json`/`epub`/`comic`/`webtoon`) actually generates; **comic/webtoon renders real panels** (not gray placeholders — `stories.py:330` fallback).
- Inline entity referencing (Character/Lorebook) without leaving editor; `StoryReader` published share + export.

**2C. World Vault**
- Characters / Locations / Lorebooks / Scenarios / Campaigns / Voices: full CRUD + search + tags end-to-end.
- Cross-linking: campaign entity pickers; character↔lorebook↔scenario links resolve.
- Relationship Graph: pan/zoom, node click → open entity, hover tooltips, dangling-link handling.
- World Timeline: URL-persistent filters, sticky date-group headers.
- Avatar Gallery + **AnimateDiff animated avatar display** in character card/gallery.
- First-run wizard auto-opens on fresh stack; starter-pack seed (migration 049) shows demo character + scenario.

**2D. Vision frontiers (validate, don't rebuild)**
- **RAG:** embeddings generate (local SBERT, CPU); recall surfaces in chat/story context; settings toggle + "why this memory?" debug UI.
- **Idle simulation:** `lifecycle.py` actually schedules `run_idle_simulation_tick`; a chat with `idle_sim_enabled` produces a summarized offline-activity view on return.
- **Comic/Webtoon export** real image panels (see 2B).

### Phase 3 — Cross-pillar integration hardening
6. Image generated inside a chat/story appears in that pillar's context + the shared gallery (single source of truth via React Query, not Zustand).
7. Branding live reactivity (poll/WS) without page refresh.
8. Statistics: cross-pillar filter + World Vault panel stays correct after Phase 2 changes.
9. Drag-and-drop sorting (`@dnd-kit/sortable`) for characters/stories/lorebooks/locations — verify it persists (`sort_order` column, migration 055).
10. Prompt Library discoverability (`/prompts` route + sidebar link).
11. Keyboard shortcuts verified: Chat `Ctrl+Enter`/`Ctrl+N`; Story `Ctrl+S`/`Ctrl+Shift+C`.
12. Gallery virtualization (`@tanstack/react-virtual`) for `Dashboard.jsx`.

### Phase 4 — Performance & API verification
13. Re-verify `world_hub.get_relationships` is bounded (limit + dangling-link flag) and doesn't silently drop links.
14. Confirm `list_chat_jobs` / `regenerate_reply` JSONB queries are acceptable for single-user (note only; no rewrite).
15. Confirm `orchestrator_service` top-level `asyncio.wait_for` is active (already present — verify).

### Phase 5 — QA consolidation & docs
16. Run the full Playwright suite (all 26 specs) against the live stack; fix any failures. Confirm `frontend-e2e.yml` is green.
17. Refresh/retire stale `ROADMAP.md` and `REMEDIATION_PLAN_v2.md` (mark superseded by this plan) so future sessions don't redo fixed work. Append the Phase 2 pass/fail log to `.kilo/plans/` or `ROADMAP.md` §appendix.

## 5. Verification gates (every phase)
```bash
# Backend
cd backend_v2 && .venv/bin/pytest -q
# Frontend
cd frontend_v2 && npm test && npm run lint
# E2E (stack running, creds live)
cd frontend_v2 && npx playwright test
# Full stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V
```

## 6. Risks
- Phase 2 depends on the running stack + live provider creds; if a provider is down, isolate that pillar and continue.
- `reference_cleanup.py` deletion: ensure no hidden runtime import path before removing.
- API versioning migration (Phase 1.5) is mechanical but touches many files — do it behind the single helper to avoid behavior change.

## 7. Open questions / your input needed
- **Push:** `b61538d` is unpushed — leave as-is unless you say push?
- **Agents worktree:** fold its cosmetic cleanups into a chore branch, or discard?
- **`reference_cleanup.py`:** delete as dead code, or wire it into entity deletion? (Recommend: delete unless you want orphan-asset GC.)
