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

# Full stack (Docker, with providers + dev overrides)
# Run scripts/preflight.sh first on a new host: it creates the `metrics` and
# `proxy` networks that compose declares external (without them `up` fails at
# network creation, for every service, with an unrelated-looking error) and
# reports the config that silently disables features.
bash scripts/preflight.sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d

# Backend only (from backend_v2/)
.venv/bin/pip install -r requirements.txt && .venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8002 --reload
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
- `provider_containers/**` or `remote_agent/**` -> `provider-tests.yml`
  (Python 3.13, pytest + ruff + compileall). The `build` job also validates the
  compose file and builds the three provider images; it seeds the required
  `.env*` files first, because compose refuses to render while an `env_file:` is
  missing and every one of them is gitignored.
- any path -> `secret-scan.yml` (gitleaks)
- `remote_agent/**` -> `build-agent-binaries.yml` (PyInstaller, push/release only)

## Backend conventions

- Services take a request-scoped `Session` and instantiate repositories internally.
- Route handlers resolve dependencies via `api/deps.py` — never import sessions or singletons directly from infrastructure.
- Domain errors: use `core/exceptions.py` (`ComfyError` hierarchy), not ad hoc `HTTPException`.
- Domain events: emit through `core/events.py` helpers (`emit_job_event`, `emit_download_event`).
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

- Shared API models: `provider_containers/provider_core/models.py`.
- `POST /inference` streams NDJSON progress lines, finishes with a success or error JSON payload.
- Model directories: `models/checkpoints`, `models/loras`, `models/vae`, `models/controlnet`, `models/unet`, `models/clip`.

## Docker gotchas

- Container name for providers must be `tnhcomfy-{PROVIDER_ID}` so the backend can detect them (see `infrastructure/providers/runtime.py`).
- Backend runs as `user: "1000:1000"`.
- Frontend file watching in Docker uses polling via Vite (`usePolling: true` in `vite.config.js`) — no `CHOKIDAR_USEPOLLING` needed.
- `docker compose up -d` starts backend, then frontend (depends_on with healthcheck), then providers.

## Never

- Run ComfyUI locally in the backend — inference is always dispatched to serverless workers.
- Commit checkpoints, output images, or `.env` — all are gitignored.
- Bypass `api/deps.py` for dependency injection in routes.
- Introduce parallel provider caches or standalone provider websocket hooks — data ownership is consolidated.

## Docs

- `docs/` has architecture, backend, frontend, deployment, and API reference.
 - `docs/STATUS.md` is the authoritative project status and what-is-still-open list.
   `docs/audit-2026-10-01.md` is the most recent code audit, and it supersedes
   `docs/audit-2026-09-29b.md`, `docs/audit-2026-09-29.md`, `docs/audit-2026-09-28.md`,
   `docs/audit-2026-09-27.md`, `docs/audit-2026-09-26.md` and
   `docs/audit-2026-09-26-followup.md` for everything it marks fixed. Read
   STATUS.md and the 2026-10-01 audit before large-scale changes.
   `docs/archive/` holds superseded planning docs —
   historical only, and they contradict each other.
- `.github/instructions/backend.instructions.md` has backend-specific rules scoped to `backend_v2/**`.
