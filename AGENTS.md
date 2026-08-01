# AGENTS.md

## Quick commands

```bash
# Full stack (agent/dev shell)
bash setup_jules.sh

# Full stack (Docker)
docker compose up -d

# Backend only (from backend_v2/)
pip install -r requirements.txt && uvicorn api.main:app --host 0.0.0.0 --port 8002 --reload
pytest

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
- `backend_v2/**` -> `backend-tests.yml` (Python 3.13, pytest)
- `frontend_v2/**` -> `frontend-tests.yml` (Node 20, vitest)
- `provider_containers/**` -> `provider-tests.yml` (Python 3.13, pytest)

## Backend conventions

- Services take a request-scoped `Session` and instantiate repositories internally.
- Route handlers resolve dependencies via `api/deps.py` — never import sessions or singletons directly from infrastructure.
- Domain errors: use `core/exceptions.py` (`ComfyError` hierarchy), not ad hoc `HTTPException`.
- Domain events: emit through `core/events.py` helpers (`emit_job_event`, `emit_download_event`).
- Config precedence: `COMFY_*` env vars > `config.json` > `DEFAULT_CONFIG` in `config.py`.
- `metadata` is `metadata_` in Python models, aliased back to `metadata` in API payloads.
- Migrations are manual in `infrastructure/database.py` (`_run_migrations()`) — no Alembic.
- Startup re-enqueues PENDING/RUNNING jobs from DB — preserve this when changing lifecycle code.
- `LoadBalancer` uses class-level state in `services/load_balancer.py` — avoid introducing more shared mutable globals.

### Testing

```bash
# Run all backend tests
cd backend_v2 && pytest

# Run a single test file
cd backend_v2 && pytest tests/test_job_service.py

# Run a single test
cd backend_v2 && pytest tests/test_job_service.py::test_create_job
```

Tests that create DB sessions must override **both** dependency sources: `api.deps.get_session` and `infrastructure.database.get_session`. See `backend_v2/tests/conftest.py`.

## Frontend conventions

- **Zustand** (`src/store/`): UI state, form drafts, realtime WebSocket job updates.
- **React Query** (`src/hooks/`): HTTP fetching, caching, mutations. Do not store server data in Zustand.
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

- Container name for providers must be `comfy-provider-{PROVIDER_ID}` so the backend can detect them.
- Backend runs as `user: "1000:1000"`.
- Frontend file watching in Docker requires polling: `CHOKIDAR_USEPOLLING=true`.
- `docker compose up -d` starts backend, then frontend (depends_on with healthcheck), then providers.

## Never

- Run ComfyUI locally in the backend — inference is always dispatched to serverless workers.
- Commit checkpoints, output images, or `.env` — all are gitignored.
- Bypass `api/deps.py` for dependency injection in routes.
- Introduce parallel provider caches or standalone provider websocket hooks — data ownership is consolidated.

## Docs

- `docs/` has architecture, backend, frontend, deployment, and API reference.
- `plan.md` tracks the phased refactor roadmap — read it before large-scale changes.
- `.github/instructions/backend.instructions.md` has backend-specific rules scoped to `backend_v2/**`.
