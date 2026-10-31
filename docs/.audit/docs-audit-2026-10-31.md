# Documentation Audit — 2026-10-31

Scope: whole repo. Baseline: maintenance pass 2026-10-31 (commit 6af8e33d), backend 4217 passed / 5 skipped, frontend 232 files / 2059 tests, ruff 0.

## Stale or Incorrect

1. **`docs/architecture.md` (conventions) — "Single uvicorn worker only. `--workers N` is refused at boot."**
   - Evidence: `backend_v2/api/main.py` `_warn_if_multiple_processes()` only logs a warning; multi-worker dispatch is safe under `FOR UPDATE SKIP LOCKED` + Postgres NOTIFY bus. Maintenance audit confirms ("multi-worker is now supported (warns only)").
   - Action: rewrite to state multi-worker is supported with a warning; single-worker remains the documented default.

2. **`docs/architecture.md` (image generation) — "Worker types are `image`, `llm`, `tts`, and `direct`."**
   - Evidence: `backend_v2/core/entities.py` defines `CATEGORY_IMAGE/LLM/TTS/HYBRID`; `transport` is a separate axis (`TRANSPORT_DIRECT` in `services/engines/registry.py`). "direct" is a transport, not a category.
   - Action: correct to categories `image`, `llm`, `tts`, `hybrid` with transport as a separate axis.

3. **`docs/architecture.md` (startup sequence) — lists 6 steps.**
   - Evidence: `backend_v2/api/lifecycle.py` `startup_application` runs ~20 phases (asset_migration, provider_hosts, provider_telemetry, cross_process_dispatch, world_integration, in_process_reconcile, civitai_resync, …).
   - Action: expand to reflect actual phases.

4. **`docs/backend.md` (Background tasks) — scheduler list omits several jobs.**
   - Evidence: `startup_application` registers provider_host_refresh, in_process_reconcile, civitai_resync_job, job_reaper, idle_simulation, world_integration, cross_process_dispatch, asset_migration, provider_monitor, telemetry, broadcast.
   - Action: update list.

5. **`docs/backend.md` (Development setup) — host SQLite path mismatch.**
   - Evidence: `backend_v2/config.py:295` default is `sqlite:///./data/db/comfy.db`; doc line 77 says `sqlite:///./data/comfy.db`.
   - Action: fix to `sqlite:///./data/db/comfy.db`.

6. **`docs/deployment.md` — `worker_type: "image"|"llm"|"tts"|"direct"`.**
   - Evidence: `backend_v2/api/routes/providers/crud.py` `WorkerType = Literal["image", "llm", "tts", "hybrid"]`.
   - Action: replace `"direct"` with `"hybrid"`.

7. **`docs/STATUS.md` — test counts stale.**
   - Evidence: maintenance audit 2026-10-31: backend 4217 passed / 5 skipped; frontend 232 files / 2059 tests.
   - Action: update verified-state table and the inline "Backend suite" line.

8. **`AGENTS.md` / `docs/backend.md` — test count "~3,900" / "~3,900 tests".**
   - Evidence: maintenance audit 4217.
   - Action: update to ~4,200.

## Missing Coverage

9. **Multi-process / cross-process dispatch not documented as supported.** `backend_v2/infrastructure/worker_registry.py` `start_cross_process_dispatch_listener`; PG NOTIFY bus `tnhcomfy_job_events`. Docs still imply single-process only. Action: note in architecture/backend.
10. **Asset migration background task** (`_run_asset_migration`) and **provider host refresh timer** are undocumented startup side effects. Action: add to startup sequence.
11. **`docs/.env.example` drift guard** exists (`tests/test_env_contracts.py`) and passes; no doc gap, but worth a one-line pointer in backend.md. (optional)

## Structural Problems

12. **Startup sequence duplicated** in `architecture.md` and `backend.md` with different detail; consolidate by linking. Action: keep detailed list in backend.md, summary in architecture.md.

## Found While Documenting

- `backend_v2/scripts/backfill_download_urls.py:31` defaults `COMFY_DATABASE_URL` to `sqlite:///./data/comfy.db` while `config.py` default is `sqlite:///./data/db/comfy.db`. Same mismatch as test_database.py. Not a docs issue; flagging for code review. Do not fix (code is read-only per instructions).
- `docs/backend.md` line 77 SQLite path mismatch is the doc side of the above.
- The `CATEGORY_HYBRID` value is accepted by the provider API but `docs/deployment.md` only listed `direct`; fixed doc only.

## Plan

Files to update:
- `docs/.audit/docs-audit-2026-10-31.md` — this file.
- `docs/architecture.md` — multi-worker, categories, startup sequence.
- `docs/backend.md` — startup/scheduler, SQLite path, test count, multi-worker.
- `docs/deployment.md` — worker_type values.
- `docs/STATUS.md` — test counts.
- `AGENTS.md` — test count ~4,200.
EOF
echo done