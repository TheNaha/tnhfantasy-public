# AGENTS.md

## Project Vision & Architecture

TNHComfy has evolved from a simple ComfyUI image generator wrapper into a **Comprehensive AI Fantasy Engine**. It now integrates three core pillars:
1. **Image Generation**: The original ComfyUI wrapper using serverless providers (Modal, Beam).
2. **Roleplay Chatbots**: Stateful, SillyTavern-style character chats with autonomous agentic workflows (allowing characters to trigger their own scene narration or image generation).
3. **Story Sandbox**: An AI Dungeon-style interactive document editor for crafting stories, with context injected from active characters and lorebooks.

All of these share the **World Vault** data layer (Characters, Chats, Lorebooks, Stories) via PostgreSQL + pgvector. Ensure that future architectural decisions support this unified, multi-modal vision.

## Quick commands

```bash
# Full stack (agent/dev shell)
bash setup_jules.sh

# Full stack (Docker, in-process engines by default; containers optional)
# Run scripts/preflight.sh first on a new host: it creates the `metrics` and
# `proxy` networks that compose declares external (without them `up` fails at
# network creation, for every service, with an unrelated-looking error) and
# reports the config that silently disables features.
bash scripts/preflight.sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -V -d

# Backend only (from backend_v2/)
# Bind to loopback, not 0.0.0.0: the API is unauthenticated, so a wildcard
# publish exposes every route (including DELETE /api/jobs) to the LAN.
# Use COMFY_BACKEND_BIND=<address> to publish on one named address.
.venv/bin/pip install -r requirements.txt && .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8002 --reload
.venv/bin/pytest

# Frontend only (from frontend_v2/)
npm install && npm run dev -- --host 0.0.0.0 --port 5174
npm test
npm run lint
```

## Port trap

The frontend runs on **5174**, not 5173. `setup_jules.sh`, `vite.config.js`, and `docker-compose.yml` all use 5174. Some older docs referenced 5173.

## Package manager

Frontend is npm-only. `pnpm` and `yarn` are rejected by a preinstall guard (`frontend_v2/scripts/enforce-npm.cjs`).

## CI test triggers

Tests run on push/PR to `main`/`master` only when the relevant directory changes:
- `backend_v2/**` -> `backend-tests.yml` (Python 3.13, pytest + ruff)
- `frontend_v2/**` -> `frontend-tests.yml` (Node 20, vitest + eslint + build)
- `frontend_v2/**` or `backend_v2/**` -> `frontend-e2e.yml` (Playwright)
- `remote_agent/**` -> `provider-tests.yml` (builds the remote-agent image + backend/frontend app images) and
  `build-agent-binaries.yml`.
- any path -> `secret-scan.yml` (gitleaks)

## Backend conventions

- Services take a request-scoped `Session` and instantiate repositories internally.
- Route handlers resolve dependencies via `api/deps.py` — never import sessions or singletons directly from infrastructure.
- Domain errors: use `core/exceptions.py` (`ComfyError` hierarchy), not ad hoc `HTTPException`.
- Domain events: emit through `core/events.py` helpers (`emit_job_event`). There is no `emit_download_event` — the `download.*` family was removed on 2026-10-03 because it had zero producers and zero subscribers; model-download status is served by polling the model-status endpoints.
- Config precedence: `COMFY_*` env vars > `config.json` > `DEFAULT_CONFIG` in `config.py`.
- `metadata` is `metadata_` in Python models, aliased back to `metadata` in API payloads.
- Migrations run automatically at backend startup via the ordered steps runner in `infrastructure/migrations/steps.py` (no Alembic). Add new migrations as `MigrationStep(version=..., apply_fn=...)` entries there; each step is recorded in `schema_migrations` and runs once.
- Startup re-enqueues PENDING/RUNNING jobs from DB — preserve this when changing lifecycle code.
- `LoadBalancer` uses class-level state in `services/load_balancer.py` — avoid introducing more shared mutable globals.

### Testing

```bash
cd backend_v2 && pytest

# Run a single test file
cd backend_v2 && pytest tests/test_job_service.py

# Run a single test
cd backend_v2 && pytest tests/test_job_service.py::test_create_job

# Lint (auto-fix safe, non-noisy rules only)
cd backend_v2 && ruff check .
```

Ruff config in `ruff.toml` selects `F` (pyflakes) only — catching real bugs like
undefined names (F821), unused imports (F401), and redefined-while-unused (F811).
F401 is **on**; it was globally ignored until 2026-09-26, which hid a stale import
whose only consumer had been deleted. Individual lines need `# noqa: F401` and a
reason — genuine re-export modules (`deps.py`, `worker_ws.py`), star-import
consumers (`api/routes/models/crud.py`, `maintenance.py`), and names that exist
only as a `monkeypatch.setattr` / `patch()` string target
(`services/job_runner.ProviderService`). F811 is ignored for test files (test
class redefinition is sometimes intentional).

Never blanket-ignore a lint rule to quiet one finding. Turning F401 on broke 8
tests immediately, which is the real reason to document a `noqa` — not a reason to
switch the rule off.

Tests that create DB sessions must override **both** dependency sources: `api.deps.get_session` and `infrastructure.database.get_session`. See `backend_v2/tests/conftest.py`.

`get_session_sync()` is redirected for **every** test by an autouse fixture in
`conftest.py`, and the fixture rebinds the name in every already-imported module
that holds it. A module doing `from api.deps import get_session_sync` binds the
function at import time, so patching `api.deps` alone does not reach it — which
is how `api/routes/files.py` ended up running against the real `data/comfy.db`
during tests. Use the `session` fixture for ORM work; do not open your own.

## Frontend conventions

- **Zustand** (`src/store/`): UI state, form drafts, realtime WebSocket job updates.
- **React Query** (`src/hooks/`): HTTP fetching, caching, mutations. Do not store server data in Zustand.
- **World Vault State**: Ensure entity relationships (like a Story's `character_ids` or `lorebook_ids`) are persisted directly to the backend via React Query mutations (e.g., `updateStory.mutate`), avoiding disconnected transient UI state.
- Provider data flows through `useProvidersPageData` as the single source of truth.
- Collections bootstrapped at app startup; images lazy-loaded when opened.
- Read `frontend_v2/STATE_MANAGEMENT.md` before changing state logic.

### Testing

```bash
cd frontend_v2 && npm test
cd frontend_v2 && npm run test:watch
```

Vitest config is in `vite.config.js` (jsdom environment, globals enabled, setup file at `src/test/setup.js`).

### Lint

```bash
cd frontend_v2 && npm run lint
```

ESLint runs on `**/*.{js,jsx}`. Unused vars starting with uppercase or underscore are allowed (`varsIgnorePattern: '^[A-Z_]'`).

### Vite proxy

Proxy falls back: `VITE_PROXY_TARGET` -> `VITE_API_URL` -> `http://localhost:8002`. In Docker, the container hostname is `backend_v2`, not `localhost`.

## Provider contract

- Default (and only) path is in-process: `backend_v2/services/engines/` (Modal, Beam,
  DirectComfy, LLM, TTS) + `backend_v2/services/in_process_reconciliation.py`. Engine contract:
  `services/engines/base.py` (`InProcessEngine`, `translate_legacy_image_update`,
   `normalize_validation_result`, `EngineAuthError`, `MODEL_DIRECTORIES`). The `COMFY_USE_IN_PROCESS_ENGINES`
   gate and the containerized `provider_containers/` workers (plus the `--profile providers`
   compose profile) were removed on 2026-10-08. The cloud-worker deploy sources those engines
   name were deleted with them and restored on 2026-10-15 to `deployables/` (Modal image, Modal
   TTS, Beam); see `docs/provider-architecture.md` for which tree runs where.
- The Modal LLM provider is `modal_llm` (was `modal_vllm`, still accepted as an alias) and runs
   llama.cpp, not vLLM: `deployables/modal/llm/app.py`, app `tnh-llm`, class `ChatLLM`.
- Deploying a cloud worker is a host-side CLI operation: `bash scripts/deploy.sh <image|tts|llm|beam>`.
   There is deliberately no deploy route. Providers that live in a separate runtime
   (remote ComfyUI, a hosted agent) connect via `external_worker` / `remote_agent/`.
- `POST /inference` streams NDJSON progress lines, finishes with a success or error JSON payload.
- Model directories: `models/checkpoints`, `models/loras`, `models/vae`, `models/controlnet`, `models/unet`, `models/clip`.
- Disabled providers (`enabled: false`): Intentionally excluded from load balancer routing. They represent a healthy, user-paused standby state (cost control, maxed billing, maintenance) and must never trigger "needs attention" or error states in system status.

## Docker gotchas

- Backend runs as `user: "1000:1000"`.
- Frontend file watching in Docker uses polling via Vite (`usePolling: true` in `vite.config.js`) — no `CHOKIDAR_USEPOLLING` needed.
- `docker compose up -d` starts backend (then frontend on its healthcheck). The compose stack no longer includes provider services.

## Never

- Run ComfyUI locally in the backend — inference is always dispatched to serverless workers.
- Commit checkpoints, output images, or `.env` — all are gitignored.
- Bypass `api/deps.py` for dependency injection in routes.
- Introduce parallel provider caches or standalone provider websocket hooks — data ownership is consolidated.
- Treat a disabled provider (`enabled: false`) as broken, an error, or a candidate for deletion — disabling is an intentional operational choice to pause routing.

## Docs

- `docs/` has architecture, backend, frontend, deployment, and API reference.
 - `docs/STATUS.md` is the authoritative project status and what-is-still-open list.
   `docs/audit-2026-10-10b.md` is the most recent code audit — a pass scoped to the
   in-process compute tier (`services/engines/`) that the 10-08 consolidation made
   the only execution path. `docs/audit-2026-10-10.md` is the *delta* pass scoped
   to what the 10-08 consolidation left behind in the rest of the tree. For anything
   that predates 10-08, `docs/audit-2026-10-05.md` remains the reference; it in turn
   supersedes `docs/audit-2026-10-04b.md` and `docs/audit-2026-10-04.md`; all three
   supersede `docs/audit-2026-10-03b.md`, `docs/audit-2026-10-03.md`,
   `docs/audit-2026-10-01.md`, `docs/audit-2026-09-29b.md`,
   `docs/audit-2026-09-29.md`, `docs/audit-2026-09-28.md`, `docs/audit-2026-09-27.md`,
   `docs/audit-2026-09-26.md` and `docs/audit-2026-09-26-followup.md` for everything
   they mark fixed. Read STATUS.md and the 2026-10-04 audit before large-scale
   changes. The 2026-10-10 audit's §3 lists the candidates that did not survive
   verification — read it before re-reporting one.
   `docs/archive/` holds superseded planning docs —
   historical only, and they contradict each other.
- `.github/instructions/backend.instructions.md` has backend-specific rules scoped to `backend_v2/**`.
