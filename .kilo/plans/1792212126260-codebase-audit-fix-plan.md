# Codebase Audit & Remediation Plan

Generated 2026-10-17 from a fresh multi-agent sweep of `backend_v2`, `frontend_v2`,
and the cross-seam integration. Supplements (does not replace) `docs/STATUS.md`
and the 2026-10-10 audits; those remain authoritative for their scopes. This plan
targets what those audits left open plus new findings from the consolidation mess.

## 0. Scope and constraints

- Plan mode: no source edits performed; this file is the only artifact.
- Invariants to preserve: website reachable on :5174 after changes; backend on
  :8002 inside container; all suites green; `ruff check .` clean; `npm run lint`
  0 errors.
- Allowed major changes: unify duplicated helpers, unify inference send-path,
  unify `by_directory` shape, unify model deletion sidecar cleanup, offload sync
  DB work from async routes, remove dead exports.
- Out of scope (deliberate product decisions, not bugs): no app auth, no resume
  for Modal streaming (platform decision), provider enable/disable is operator-owned.

## 1. Findings summary (prioritized)

Severity: P0 = data loss/crash, P1 = wrong behavior, P2 = quality/perf, P3 = cosmetic.

### P0
- `backend_v2/services/engines/direct_comfy_engine.py:1198` — `_fetch_view` returns
  `None` on non-200 and outputs filtered out; job still reports success with
  missing images. Transient ComfyUI 500 on 1 of N images → "successful" N-1 job.
- `backend_v2/services/in_process_reconciliation.py:253` — `current_download` mutated
  lock-free by concurrent downloads; last writer wins, progress lies.

### P1
- `backend_v2/api/routes/providers/lifecycle.py:220` — `remove_model_from_provider`
  ignores `engine.delete_file()` result and always returns success; sidecars survive.
- `backend_v2/services/engines/llm_engine.py:747` — `get_file_stream` treats short
  read as EOF (`if not chunk: break`) instead of fatal; reconciliation stores a
  truncated file that fails its own sha256 later.
- `backend_v2/services/engines/direct_comfy_engine.py:164` — websocket `connect`
  passes no `max_size` (1 MiB default) vs Beam's 20 MiB; large frames raise
  `ConnectionClosedError` → whole job retried.
- `backend_v2/infrastructure/scheduler.py:99` — `_AdvisoryRunLock.__exit__` returns
  early without closing the session when lock not granted → connection leak.
- `backend_v2/services/job_service.py:281` — `get_job`/`record_attempt`/`mark_failed`/
  `update_job` are async shells over sync SQLModel commits on the event loop.
- `backend_v2/services/load_balancer.py:419` — `get_next_provider` runs 2-3 sync DB
  reads per dispatch inline.
- `frontend_v2/src/hooks/useLLMJobResult.js:147` — `useQueryClient()` called inside
  try/catch (conditional hook) → rules-of-hooks violation, unstable identity.
- `frontend_v2/src/pages/StoryReader.jsx:196` — manual HTML escaping + `dangerouslySetInnerHTML`;
  fragile, and `*`/`**` regex can mishandle multiline content.

### P2 — duplicated code / non-unified
- `download_token_for_url` copied 4 times with drift:
  `llm_engine.py:496` (adds Beam), `direct_comfy_engine.py:267` (defaults to HF token),
  `modal_engine.py:445` (instance tokens vs env). Unify into one helper in
  `services/engines/base.py`.
- Inference send-path contract (`file_uploads`, `delete_after_use`, `outputs`)
  mandated by client_v2/reducer but absent from 3 of 5 loops:
  `modal_engine:92-108`, `vllm_engine:143-157`, `direct_comfy_engine:574-582`,
  `beam_engine:255-270`, `llm_engine:390-420`. Only engines that copied it work.
- `by_directory` two incompatible shapes: `direct_comfy:526` flat with directory
  prefixes; `llm_engine:753-755` nested with recursive `models/` prefixes. One live
  caller consumes the latter. Unify to nested shape everywhere.
- `engines still export dead contract`: `deploy`, `get_storage_stats`, `register_engine`,
  `clear_engine_cache`, `queue_download`, `trigger_download`, `get_client` — no
  production callers. Remove or gate behind `manages_*` flags.
- `tts_workflow_builder.build_voice_clone_workflow` (no callers), `workflow_parser`
  `get_all_required_files`/`get_required_storage_paths` (tests only),
  `context_builder.inject_lorebooks_into_system_prompt` (superseded by `assemble`),
  `asset_sql.meta_string` (no callers), `load_balancer.pop` dead, `world_integration_service`
  dead assignment at :919.
- `nodes.invalidate_object_info_cache` has no caller → Direct ComfyUI schema changes
  invisible for 10-min TTL. Wire into provider update + reconciliation completion.
- `llm_config.py:189` PUT trusts unvalidated `provider_id`/`model_id` from body.
- `maintenance.py:518` keeps `_DIRECTORY_TO_MODEL_TYPE` second smaller vocabulary;
  import canonical `MODEL_DIRECTORIES` (already partially done, verify).
- `registry.py` vs `engine_factory.strict_provider_engine()` default vllm app name
  mismatch (`comfy-modal-vllm` vs `vllm-modal-stack`) — trap; align.
- `tts_workflow_builder` error message names deleted `POST /deploy` endpoint.
- `GoogleLLMEngine` health probe discards failure reason (:1521) and no-key branches
  omit `retryable` flag (:1794) that 401 branch sets.

### P2 — performance / unbounded reads
- `agent_simulation.py:94` — `select(Chat).where(idle_sim_enabled)` no limit; runs
  every idle-sim tick.
- `memory_extraction.py:226` — loads every `CharacterMemory.content` for a character
  (dedup set); no cap; no index on `(character_id, content)`.
- `model_service.py:313` — `search_models` returns full result set; no pagination.
- `model_availability_service.py:204` — unbounded join filtered only by requested pairs.
- `world_ownership.py:97`, `tts_workflow_builder.py:71`, `model_downloader.py:149`,
  `in_process_reconciliation.py:866` — unbounded provider loads per tick/request.
- `context_builder.py:1029` — per-request `Character` lookup by ids; no cache.
- `reference_cleanup.py:100-182` — sequential per-entity-type queries in loop.
- `statistics_service.py:231,337` — group-by scans with no date bound.
- `timeline.py:173`, `prompts.py:134`, `voices.py:50` — sync DB exec inline in
  async-adjacent paths.
- `world_integration_service.py:137,431,1490,1623,1660,1669` — multiple `.all()`
  fan-outs per call.
- `orchestrator_service.py:672`, `llm_config.py:122,165`, `session_detector.py:294,354,370`
  — unbounded scans.
- `model_availability_service.py:333` — cache invalidation only on explicit clear;
  stale on partial updates.
- `provider_status_service.py:152,258` — status counts recomputed per request; no TTL.
- `maintenance.py:156` — tag list query unbounded per model, repeated.

### P2 — frontend missing invalidation / polling
- `useMessages.js:115` `useImpersonateMessage` no `onSuccess` → new message never
  refreshes list.
- `useChats.js:132` `useSuggestReply` no invalidation.
- `useChats.js:64` `refetchInterval` polling on top of WS → doubles load.
- `useJobStatus.js:37`, `useLLMJobResult.js:107` — polling without WS gating.
- `useObjectInfo.js:94` — 5-min staleTime but refetchOnMount/WindowFocus/Reconnect true
  on a 30s-cost endpoint → repeated fetches.
- `useMessages.js:7-8` — query key includes limit/offset/search/tail; invalidation by
  chat prefix leaves stale variants.
- `useCharacters.js:176-194` — two collection queries per character list (N+1 at render).
- `useSessions.js` — verify each mutation invalidates session list + assets.

### P2 — frontend high-severity
- `useLLMJobResult.js:147` conditional hook (see P1).
- `StoryReader.jsx:196` manual escaping + dangerouslySetInnerHTML (see P1).
- `api/providers.js:171-234` `deployStream` uses raw `fetch` bypassing auth/base URL/error
  normalization.
- `ProviderModal.jsx:110-118` schema fetch failure swallowed (`.catch(() => {})`).
- `useDashboardSelection.js:36-56` selection cleared while toast.promise still running;
  failed download leaves UI cleared.
- `Settings.jsx:1462-1478` effect runs once with empty deps, swallows backend errors;
  AI settings sync stale.
- `StorySandbox.jsx:283-293` `setTimeout` updates editor state with exhaustive-deps
  disabled; stale chapter data can be adopted.
- `ChatWorkspaceContext.jsx:63-74` collapse state mirrored to localStorage via effects
  while other state is React Query → detached persistence drift.
- `useSelectedImageState.js:9-18` query key derived from mutable selected image object →
  stale cache entries.
- `Characters.jsx:188-193` `URL.createObjectURL` never revoked → blob URL leak.
- `SystemPromptPanel.jsx:47-51` resets values only on `chatKey`, missing linked-character
  append prompt updates.

### P3
- Namespace imports pulling whole modules: `useActiveJobs.js:4` and 8 others
  (`import * as ws`), `useObjectInfo.js:3` (`import * as idb`).
- Duplicated localStorage→API migration logic in `usePrompts.js:8-41` and
  `useCollections.js:34-62`.
- Stale comment in `useWorlds.js:13` referencing retired `/api/v2/campaigns`.
- `api/settingsApi.js:34` calls `/api/jobs/reconcile-chat-replies` — verify route exists.
- `api/files.js:181` statistics `images_by_date` vs facet date bucketing mismatch.
- `AdvancedGenerator.jsx` object_info stale-cache fallback can mask provider errors.
- Bundle: `App.jsx:22` framer-motion eager in root; `react-hot-toast` eager; `react-router-dom`
  full import in root.
- `direct_comfy_engine` websocket max_size (P1, listed above).
- `beam_engine.py:484` stream can end with no terminal event (`if item is None: break`).
- `beam_engine.py:242` does not await cancelled local-echo task.
- `direct_comfy_engine` no-agent `list_models` shape mismatch (paths without `models/`
  prefix) causes orphans (P2).
- `modal_engine` healthy with zero network contact (15s cache window) (P2).
- `model_service.delete_model` does not clear provider sidecars/availability caches.
- `reference_cleanup._scrub_json_array` LIKE pattern via raw f-string (already partially
  fixed? verify).
- `nodes.invalidate_object_info_cache` no caller (P2, listed).
- `llm_engine.get_file_stream` raises `NotImplementedError` on hosted LLM engines
  (contract gap, unreachable via `manages_model_files` gate).
- `modal_engine.deploy()` returns not_applicable (dead contract).
- `direct_comfy_engine.NODE_TO_DIRECTORY` had `"DiffusersLoader" → "diffusers"` removed;
  verify no other phantom dirs.

### Audit-disproved / not re-reported
Items in `docs/audit-2026-10-10.md §3` (8 disproved candidates) are excluded.

## 2. Major unification goals (architectural)

1. **One `download_token_for_url`** in `services/engines/base.py`, re-exported. All four
   call sites (modal, beam, direct_comfy, llm) call it. Resolve drift: prefer env token
   when instance token absent; Beam added; direct_comfy no longer defaults to HF token.
2. **One inference send-path** helper in `base.py`: `build_send_payload(workflow, ...)` producing
   `file_uploads`, `delete_after_use`, `outputs`. All five engines call it. Removes the
   "only engines that copied it work" class.
3. **One `by_directory` shape** (nested under `models/...`) in `base.py` normalizer;
   `direct_comfy` and `llm_engine` both emit it; storage-stats consumers read one shape.
4. **One model-deletion path**: `model_service.delete_model` calls `engine.delete_file`
   for the model + sidecars (`.json`, `.preview.png`, `.sha256`) and invalidates
   `ModelAvailabilityService` + load balancer health cache. Route `lifecycle.py` delegates.
5. **One `invalidate_object_info_cache` trigger**: call from provider update (capabilities
   changed) and reconciliation completion, not only engine_factory.
6. **Offload sync DB from async routes**: wrap `prompts.py:134`, `timeline.py:173`,
   `voices.py:50` bodies in `asyncio.to_thread`, matching `rollback_chat` pattern.
7. **Context builder unification** (per memory decision): merge
   `build_chat_context_async` + `build_system_prompt_sections` into one
   `build_context(session, workspace, mode=chat|story)`; remove dict-vs-ORM branching.
8. **Frontend query-key normalization**: introduce `queryKeys` factories for messages
   (include chatId only, not limit/offset/search) so invalidation is reliable; coalesce
   polling with WS via `WS_FALLBACK_EVERY` pattern already used in `awaitJobText`.
9. **EmptyState with error slot** (STATUS 1b item 8): migrate 33 inline empty states
   so failed fetches cannot render as "empty vault". Guard test already exists; ensure
   vocabulary covers health claims.

## 3. Execution plan (ordered)

Phase A — stop the bleeding (P0/P1 data-correctness) [do first]
1. Fix `direct_comfy_engine._fetch_view` to raise/record failure and fail the job (or
   retry) instead of silently dropping; add test reverting → fails.
2. Lock `current_download` mutation in reconciliation (asyncio.Lock or per-provider lock).
3. Fix `llm_engine.get_file_stream` short-read to raise `FileTruncatedError` / fatal.
4. Add `max_size=20*1024*1024` to direct_comfy websocket connect.
5. Fix scheduler `_AdvisoryRunLock.__exit__` to close session on non-granted path.
6. Offload `job_service` sync commits to `asyncio.to_thread` (get_job/record_attempt/
   mark_failed/update_job) — match rollback_chat.
7. Offload `load_balancer.get_next_provider` DB reads.
8. Fix frontend conditional hook in `useLLMJobResult` (call `useQueryClient` at top
   level; guard provider presence differently) and `StoryReader` escaping (use a
   safe markdown renderer or keep escape-then-transform with tests).

Phase B — unify duplicated code
9. Create `base.download_token_for_url`; replace 4 copies.
10. Create `base.build_send_payload`; replace in 5 engines.
11. Normalize `by_directory` shape in both emitters + normalizer.
12. Remove dead exports (deploy, get_storage_stats, register_engine, clear_engine_cache,
    queue_download, trigger_download, get_client) or mark `@deprecated` with tests.
13. Remove dead helpers (build_voice_clone_workflow, get_all_required_files,
    get_required_storage_paths, inject_lorebooks_into_system_prompt, meta_string,
    load_balancer.pop, world_integration dead assignment) after confirming zero callers.
14. Wire `nodes.invalidate_object_info_cache` into provider update + reconciliation.
15. Validate `llm_config` PUT provider_id/model_id against registry before persist.
16. Align registry vs engine_factory default vllm app name.
17. Fix Google health probe to preserve failure reason + retryable flag.
18. Fix `tts_workflow_builder` error message (remove deleted endpoint reference).
19. Fix `maintenance.py` to use only canonical MODEL_DIRECTORIES.

Phase C — performance & unbounded reads
20. Add `limit`/pagination to `model_service.search_models`, `memory_extraction` dedup
    (cap + index), `agent_simulation` query, `model_availability_service` join.
21. Add composite index `(character_memories.character_id, content)` and
    `(messages.chat_id, created_at)` via migration step in `steps.py`.
22. Add short TTL cache to `provider_status_service` counts.
23. Invalidate `model_availability` on partial updates (not only explicit clear).
24. Offload sync DB in `prompts.py`, `timeline.py`, `voices.py`.
25. Coalesce frontend polling with WS (useChats, useJobStatus, useLLMJobResult,
    useObjectInfo refetch gating).

Phase D — frontend correctness
26. Add invalidation to `useImpersonateMessage`, `useSuggestReply`, `useChatStreaming`
    memories (already done? verify).
27. Fix `deployStream` to use api client (auth/base URL).
28. Surface schema fetch errors in `ProviderModal`.
29. Defer selection clear until toast resolves in `useDashboardSelection`.
30. Fix `Settings.jsx` AI settings sync (deps + error handling).
31. Fix `StorySandbox.jsx` setTimeout stale data.
32. Unify collapse persistence in `ChatWorkspaceContext` (React Query or single store).
33. Fix `useSelectedImageState` query key stability.
34. Revoke blob URLs in `Characters.jsx`.
35. Fix `SystemPromptPanel` linked-character append prompt.
36. EmptyState error slot + migrate inline empty states.

Phase E — validation
37. Run backend pytest + ruff; frontend vitest + lint + build.
38. Verify stack reachable: `localhost:5174` → 200, `/api/live`, `/api/ready` → 200.
39. Add revert-verified tests for each P0/P1 fix (follow audit convention).
40. Update `docs/STATUS.md` open-items section.

## 4. Risks / migration notes

- Context builder unification (goal 7) touches many callers (chat, story, agent
  simulation). Do behind a feature flag or keep old functions as thin wrappers
  delegating to `build_context` until callers migrated; remove wrappers in follow-up.
- Dead-export removal may break monkeypatch string targets in tests
  (`services/job_runner.ProviderService` pattern). Grep tests before deleting.
- `by_directory` shape change must update the single live caller atomically.
- Index migration must run after `create_all` (existing trap): add as explicit
  `MigrationStep` with `CREATE INDEX IF NOT EXISTS`, not rely on `create_all`.
- Frontend query-key change requires updating all invalidation call sites; use
  `queryKeys` factories to avoid drift.

## 5. Out of scope

- App authentication (deliberate single-user studio; document boundary, don't implement).
- Modal streaming resume (platform decision: presigned URL/volume mount).
- Provider enable/disable (operator-owned via Providers page).
- Colab notebook changes (separate track; not part of this consolidation).

## 6. Success criteria

- All P0/P1 items fixed with revert-verified tests.
- `ruff check .` clean; `npm run lint` 0 errors.
- Backend pytest ≥ current baseline; frontend vitest ≥ current baseline.
- Stack serves :5174 and /api/live, /api/ready → 200 after changes.
- No new dead code introduced; `grep` for removed helpers returns only tests.
