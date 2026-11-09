# AGENTS.md

TNHFantasy is an AI fantasy engine with three pillars: **image generation** (ComfyUI run on serverless Modal/Beam workers), **roleplay chat** (SillyTavern-style, with agentic turns that can narrate scenes or generate images), and a **story sandbox**. All three share the **World Vault** data layer (Characters, Chats, Lorebooks, Stories, Personas) in PostgreSQL + pgvector. Design changes so they keep working across all three.

## Layout

- `backend_v2/`: FastAPI app (`api/main.py`). The flow is routes → services → repositories. Models and providers are in `services/engines/`, migrations in `infrastructure/migrations/steps.py`.
- `frontend_v2/`: React 19 + Vite + Zustand + React Query. Uses bun only.
- `deployables/`: the only source for the cloud workers (Modal `comfy-modal-stack`, `comfy-modal-tts`, `tnh-llm`, plus the Beam deployments). The backend does not import it. It has its own `ruff.toml`.
- `remote_agent/`: a separate worker runtime for Colab, remote ComfyUI, or a hosted agent. The backend reaches it through `external_worker`.
- `scripts/` (repo root): `preflight.sh`, `deploy.sh`, `generate_api_docs.py`. `backend_v2/scripts/` holds one-off maintenance and migration scripts.

## Commands

```bash
# New host: create the external `metrics`/`proxy` networks first, otherwise compose fails with an unrelated-looking error
bash scripts/preflight.sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -V -d
# Containers: tnhfantasy-backend, tnhfantasy-frontend, tnhfantasy-db. The dev override mounts ./backend_v2:/app and the repo at /comfyui.
# Without the dev override, code edits do NOT reach the running backend.

# Backend tests: prefer running them inside the container (it has the right deps, /comfyui mount and Postgres)
docker exec tnhfantasy-backend python -m pytest -q tests/test_job_service.py
docker exec tnhfantasy-backend python -m pytest -q tests/test_job_service.py::test_create_job
# Lint on the host:
cd backend_v2 && ruff check .

# Frontend (from frontend_v2/)
bun run lint && bun run test && bun run build   # == `bun run verify`, the same order CI uses
bun run test -- src/path/to/file.test.jsx       # single file
bun run test:e2e                                 # Playwright; starts its own dev server on 5174

# Backend only, outside Docker (from backend_v2/)
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8002 --reload
```

- Bind the backend to loopback, never `0.0.0.0`. The API has no authentication, so a wildcard bind exposes `DELETE /api/jobs` and every other route to the LAN. Use `COMFY_BACKEND_BIND=<address>` to publish on one named address.
- The frontend runs on port **5174**, not 5173. Some old docs still say 5173.
- The frontend is **bun only**. The preinstall guard (`scripts/enforce-bun.cjs`) rejects npm, pnpm and yarn.

## Testing gotchas

- `pytest.ini` sets `addopts = -n auto` (xdist, one worker per core). The full suite (~4,200 tests, ~6 min) has OOM'd this host. Run targeted files, and never run vitest at the same time as backend pytest.
- Unit tests use in-memory SQLite. Postgres/pgvector tests (`test_migration_indexes_exist.py`, `test_pgvector_integration.py`, …) run only when `PGVECTOR_TEST_URL` is set, as it is in CI.
- Tests that create DB sessions must override **both** `api.deps.get_session` and `infrastructure.database.get_session` (see `tests/conftest.py`). An autouse fixture redirects `get_session_sync()` and rebinds it in every module that already imported it. Use the `session` fixture and never open your own session, or the test hits the real DB.
- Tests that read files outside `backend_v2` (`docs/`, `frontend_v2/e2e/`, `remote_agent/`) locate the repo root through `tests/repo_paths.py`: ancestors, then `TNH_REPO_ROOT`, then `/comfyui`.
- `docs/api.md` is **generated**, and `tests/test_api_docs_contract.py` checks it for drift. After you change any router, run `cd backend_v2 && .venv/bin/python ../scripts/generate_api_docs.py`.
- Contract tests that fail on purpose:
  - `test_deployable_contract.py` AST-checks `services/engines/` against `deployables/` in both directions.
  - `test_provider_core_parity.py` pins the fork between `deployables/provider_worker_core` and `remote_agent/provider_core`. Do **not** unify the two.
- Frontend `vi.mock` factories must list every hook the page imports. Page tests also need a `confirmationStore` mock.
- `ruff.toml` selects `F` only, and F401 is on. Each `# noqa: F401` needs a stated reason (a re-export, a star-import consumer, or a `patch()` string target). Never blanket-ignore a rule. Running ruff from the repo root reports ~450 unrelated style errors, so run it from `backend_v2/`.

## Backend conventions

- Services take a request-scoped `Session` and create their repositories internally. Routes get dependencies only through `api/deps.py`.
- Raise errors from the `ComfyError` hierarchy in `core/exceptions.py`, not ad hoc `HTTPException`. Emit events through `core/events.py` (`emit_job_event`). There is no `download.*` event family: model-download status is polled.
- Config precedence: `COMFY_*` env vars > `config.json` > `DEFAULT_CONFIG` in `config.py`.
- Python models use `metadata_`, which is aliased to `metadata` in API payloads.
- Migrations: there is no Alembic. Append a `MigrationStep(version=..., apply_fn=...)` in `infrastructure/migrations/steps.py`. Steps run once at startup and are recorded in `schema_migrations`.
- A new World Vault route must be registered in `api/routes/world_vault/__init__.py`.
- Request models like `UpdateStory` and `ChatRequest` whitelist their fields explicitly. Add every new field to the whitelist; sending `null` clears a field.
- In-place changes to a dict inside a `MutableList` do not persist. Reassign the column instead.
- Startup re-enqueues PENDING and RUNNING jobs. Keep this behavior when you change lifecycle code.
- `LoadBalancer` keeps class-level state. Do not add more shared mutable globals, and do not fire off async tasks without tracking them.
- The chat pipeline is driven by a manifest: `services/chat_pipeline.py` (stages), `pipeline_runner.py`, `pipeline_stages.py`. Limits come only from `core/pipeline_limits.py`.

## Providers

- Execution is in-process only: `backend_v2/services/engines/` (contract in `base.py`). Never run ComfyUI inside the backend; inference always goes to a worker.
- Deploying a cloud worker is done **only from the host CLI**: `bash scripts/deploy.sh {list,check,image,tts,llm,beam,all} [--dry-run]`. There is deliberately no deploy route.
- `modal_llm` (alias `modal_vllm`) runs llama.cpp, not vLLM.
- `enabled: false` on a provider means the user paused it on purpose (cost, billing, maintenance). Never treat it as broken, raise "needs attention" for it, or propose deleting it.
- Do not add a parallel provider cache or a standalone provider websocket hook. Provider data flows through `useProvidersPageData`.

## Frontend conventions

- Zustand holds UI state, drafts and realtime job updates. React Query holds server data. Do not store server data in Zustand.
- Persist World Vault relationships (for example a Story's `character_ids` or `lorebook_ids`) through mutations like `updateStory.mutate`, not through transient UI state.
- Read `frontend_v2/STATE_MANAGEMENT.md` before changing state logic.
- In Docker, the Vite proxy target is `backend_v2`, not `localhost`. The fallback chain is `VITE_PROXY_TARGET` → `VITE_API_URL` → `http://localhost:8002`.

## CI

Workflows run on push or PR to `main`/`master`, filtered by path:
- `backend_v2/**` or `docs/api.md` → `backend-tests.yml`: Python 3.13, ruff, pytest, with a pgvector service.
- `frontend_v2/**` → `frontend-tests.yml`: lint, then vitest, then build.
- `frontend_v2/**` or `backend_v2/**` → `frontend-e2e.yml`.
- `remote_agent/**`, `scripts/**`, `docker-compose*.yml` → `provider-tests.yml`.
- Any path → `secret-scan.yml` (gitleaks).

Never commit checkpoints, outputs, or `.env` / `.env.*` files. Only `.env.example*` is tracked. The repo root holds several real `.env.*` files with credentials, and gitignore is the only thing keeping them out.

## Docs

- `docs/STATUS.md` is the authoritative status. The newest code audit is `docs/maintenance/audit-2026-11-09.md`; the prior consolidated reference is `docs/audit-2026-11-02.md` (root `docs/audit-2026-11-*.md` and `docs/.audit/docs-audit-*`). Each audit supersedes the earlier ones for every item it marks fixed.
- `docs/audit-2026-11-*.md` (root) and `docs/maintenance/audit-2026-11-*.md` are historical audits; `docs/features/` holds planning drafts. There is no `docs/archive/` in this checkout.
- `.github/instructions/backend.instructions.md` holds backend rules scoped to `backend_v2/**`.
- `deployables/README.md` maps each deployable to its engine. `docs/provider-architecture.md` explains which tree runs where.
