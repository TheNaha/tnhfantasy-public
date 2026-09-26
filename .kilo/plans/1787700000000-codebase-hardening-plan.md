# Hardening Plan — 2026-09-26

Source: `docs/audit-2026-09-26.md`. Baseline `master` @ `ae3a010`, worktree clean.
Precondition to preserve: the stack must stay reachable at `:5174` with `/api/` working after every wave.

## Sequencing rationale

Waves are ordered so that each one is independently verifiable and leaves the app in a working
state. Wave 1 is pure data-integrity with no schema change. Wave 2 is the availability/auth layer
and the only wave that can make the site unreachable, so it gets a runtime check. Wave 3 is
frontend-only and is verified with vitest + lint. Waves 4-5 are performance and consolidation,
ordered so that each fix removes duplicated work rather than adding abstraction.

A rule for this pass: **prefer deleting to repairing.** Several findings (the path-traversal proxy
endpoint, 16 test-only config getters, a `build_image_job` that nothing calls) are cheaper and safer
to remove than to harden, and removal cannot regress a caller that does not exist.

---

## Wave 1 — Data integrity (backend, no schema change)

| # | Fix | Files |
|---|---|---|
| P0-1 | Character delete must not cascade chats/messages. Mirror `delete_chat`'s hardened pattern: bulk-`UPDATE` child `character_id` to NULL, then delete with a core `DELETE` that bypasses ORM unit-of-work. | `api/routes/world_vault/characters.py`, `core/entities.py` |
| P0-2 | Clear `VoiceModel.character_id` on character delete, and add `ondelete="SET NULL"` semantics to the entity relationship. | `services/reference_cleanup.py`, `core/entities.py` |
| P0-3 | `illustrate` role filter must use the `MessageRole` enum, not lowercase literals. | `api/routes/world_vault/chats.py` |
| P0-4 | Hoist the `narrate_scene` imports to module scope so the persist block cannot raise `UnboundLocalError`. | `services/orchestrator_service.py` |
| P0-5 | Delete the unconsumed `GET /api/files/proxy/...` endpoint (no frontend consumer, no safe-path validation). | `api/routes/files.py` |
| P0-6 | Normalise + clamp legacy `progress` / `overall_progress` before writing, so the `CHECK` constraint cannot kill the socket. | `api/routes/worker_ws.py` |
| P0-7 | Always re-read the job at the top of each dispatch attempt so a cancellation during failover is honoured. | `services/job_runner.py` |
| P0-13 | Remove `sort_order` from the 049 INSERT — 055 owns that column. Also make 049 tolerant if the column is absent. | `infrastructure/migrations/steps.py` |
| P0-17 | Tighten `_worker_owns_job` so `provider_id IS NULL` is not claimable by any worker. | `api/routes/worker_ws.py` |

Verification: `pytest` in `backend_v2`, plus a targeted test that a character delete preserves
chats and messages, and that narrate persists under agentic metadata.

## Wave 2 — Availability and auth (highest regression risk)

| # | Fix | Files |
|---|---|---|
| P0-14 | Force runtime DNS re-resolution in nginx by proxying through a variable. This is the "site is down and I did nothing" fix. | `frontend_v2/nginx.conf` |
| P0-8 | `provider_core` auth fails **closed** when the token is unset, with a clear 503 message; ship a non-empty placeholder in `.env.example`. | `provider_containers/provider_core/router.py`, `.env.example` |
| P0-9 | Give `provider-direct-url` the same `environment:` block as the other providers. | `docker-compose.yml` |
| P0-10 | Inject `PROVIDER_WORKER_TOKEN` into autostarted provider containers and bind the published port to loopback. | `services/container_manager.py`, `services/provider_env_builder.py` |
| P0-11 | Discovery fails closed on an unset token; reject registration outright when new providers are not allowed. | `api/routes/discovery.py`, `services/provider_service.py` |
| P0-12 | Give `HOST_BACKEND_PATH` / `HOST_PROVIDER_CONTAINERS_PATH` working defaults derived from the container mount, so autostart/deploy are not permanently dead. | `services/container_manager.py`, `services/provider_deploy_orchestrator.py`, `.env.example` |
| P0-15 | Point `scripts/migrate_sqlite_to_pg.py` at a module that exists, or delete the wrapper. | `scripts/` |
| P0-16 | Make the remote-agent volume source a required variable. | `remote_agent/docker-compose.yml` |
| P1 | `scripts/preflight.sh` that creates the `metrics`/`proxy` networks if missing and validates `.env` presence, so `docker compose up` cannot fail at network creation. | `scripts/preflight.sh` |
| P1 | Ignore `.env.remote-comfy` before it gets a real token committed. | `.gitignore` |
| P1 | Add `.example` templates for the five provider `.env.*` files and document the copy step. | `.env.example.*` |

Verification: `docker compose build` the two touched images, `docker compose up -d`, then
`curl` `/api/ready` through the frontend's nginx path (`http://localhost:5174/api/ready`) —
not just the backend's direct port, because the nginx change is the one that could take the site down.

## Wave 3 — Frontend broken features

| # | Fix | Files |
|---|---|---|
| P1 | Preflight state must be shared across all `useGeneratorCore()` call sites, not per-instance. | `src/hooks/useGenerationPreflight*`, `useGeneratorCore.js`, `useWorkflowBuilder.js` |
| P1 | Move `CharacterModal` outside the `!activeStoryId` branch so "Edit Character" works from the context panel. | `src/pages/StorySandbox.jsx` |
| P1 | Add `group` to the character row so the Edit pencil is visible. | `src/components/story/StoryContextPanel.jsx` |
| P1 | Depend on `updateChapter.mutateAsync`, not the mutation object, so chapter auto-save is not debounce-defeated. | `src/pages/StorySandbox.jsx` |
| P1 | Invalidate the query keys that actually exist. | `src/hooks/useProviderModels.js`, `src/hooks/useMemories.js` |
| P1 | `D` goes to `/gallery`. | `src/hooks/useKeyboardShortcuts.js` |
| P1 | Delete the dead optimistic-write key path. | `src/hooks/useChats.js` |
| P1 | Add confirmation to provider delete and chapter delete. | `src/pages/Providers.jsx`, `src/pages/StorySandbox.jsx` |

Verification: `npm test`, `npm run lint`.

## Wave 4 — Performance

| # | Fix | Files |
|---|---|---|
| P1 | Replace the `steps_cfg` linear scan with a dict keyed on the normalised pair. | `api/routes/statistics.py` |
| P1 | Push the lorebook scan cap into SQL and prefilter on content/keys. | `services/rag_pipeline.py` |
| P1 | Clamp `GET /api/jobs` limit and strip `original_messages` from list payloads. | `api/routes/jobs.py`, `services/job_service.py` |
| P1 | Add a btree expression index on `jobs ((metadata_->>'chat_id'))` and use it. | `infrastructure/migrations/steps.py`, `chats.py`, `agent_simulation.py` |
| P1 | Wrap the four blocking `async def` file endpoints in `asyncio.to_thread`. | `api/routes/files.py` |
| P1 | Move `LoadBalancer.save_state_to_db` off the lock-holding async path. | `services/load_balancer.py` |
| P1 | Cache `llm_config` reads; write via temp-file + atomic rename. | `services/llm_config.py` |
| P1 | Bound the full-table asset load; aggregate in SQL where possible. | `services/asset_reconciler.py` |
| P1 | Store agentic context once per job instead of twice. | `services/orchestrator_service.py`, `services/llm_workflow.py` |
| P1 | Fix the four re-render/perf chains: `activeStreams`, `listItems`, `MessageTimeline` index, `contextValue` deps. | `useChatWorkspaceData.js`, `ChatWorkspaceContext.jsx`, `MessageTimeline.jsx` |
| P1 | Use `createStableSorter` for the random model sort. | `src/components/ModelSelector.jsx` |
| P1 | Revoke the object URL on change and unmount. | `src/components/generator/ImageUploader.jsx` |
| P1 | Stop polling when idle: `useChatJobs`, `useBranding`, and drop one duplicate keyboard registration. | `useChats.js`, `useBranding.js`, `Dashboard.jsx`, `Layout.jsx` |
| P1 | Aggregate model downloads with a per-path lock so two workers cannot interleave into one file. | `provider_containers/provider_core/downloads.py` |
| P1 | Add `Range`-based resume + retry to the shared download path. | `provider_containers/provider_core/downloads.py` |

## Wave 5 — Consolidation

| # | Fix | Files |
|---|---|---|
| P2 | One `DEFAULT_CHECKPOINT` constant, imported by the 7 sites that hardcode it; route them through `resolve_checkpoint`. | `core/workflow_builder.py` + 6 sites |
| P2 | Stop passing a `Chat.character_ids` attribute that does not exist — the story block is never emitted today. | `services/context_builder.py` |
| P2 | Drop `prune_context`'s never-read params. | `services/context_builder.py` |
| P2 | Derive `/api/settings/schema` from `PERSISTENT_KEYS` and mark read-only sections. | `api/routes/settings.py`, `config.py` |
| P2 | Delete confirmed dead code: `build_image_job`, `Job.queue_id`, `_cached_estimate_tokens`, `inject_lorebooks_into_system_prompt`, `_resolve_default_checkpoint`, dead `useGeneratorCore.generating`, `jobsApi.getDiagnostics`, `setApiUrl`, `backend_v2/memory_snapshot_helper/`. | multiple |
| P2 | Remove endpoints with zero consumers and the superseded legacy provider routes. | `api/routes/` |
| P2 | Add the `ProviderPrefix` constant and use it in `runtime.py` + `http_client.py`. | `backend_v2/infrastructure/providers/` |
| P2 | Return canonical `StatusResponse` from the three LLM `list_models` and the ad-hoc delete/upload dialects. | `provider_containers/**/engines/*/client.py` |
| P2 | Add `cached_nodes` to `_TASK_EVENT_KINDS` and test the canonical direction. | `provider_containers/provider_core/utils.py` |
| P2 | Add tests for `_require_worker_token` — currently zero coverage on a security-critical path. | `provider_containers/tests/` |
| P2 | Document the env vars that are read but absent from every example file. | `.env.example`, `docs/` |
| P2 | Repoint the dead plan reference in `ROADMAP.md` / `DEMO_GAPS_PLAN.md`. | `ROADMAP.md`, `DEMO_GAPS_PLAN.md` |

## Explicitly out of scope

- Audio / TTS / multi-tenancy — already deferred per prior decision.
- Streaming model fetch (P0-7 in the provider audit, materialising a 7 GB file three times in RAM).
  This is a real defect but it needs a ranged/streaming transport redesign across four engines and
  the backend proxy. Recording it, not attempting it in a hardening pass.
- `GroupedDashboardContent` re-architecture, `~35` modal overlays → `<Modal>`, and
  `CharacterCard` unification. Real duplication, but each is a multi-file refactor with UI risk and
  no correctness impact. Deferred to a dedicated pass.
