# TNHComfy Workspace Instructions

## Project Guidelines

- Prefer focused edits that preserve existing architecture and module boundaries.
- Link to docs instead of duplicating long explanations:
  - `docs/architecture.md`
  - `docs/backend.md`
  - `docs/frontend.md`
  - `docs/api.md`
- Never run local ComfyUI in this repo. This backend dispatches to serverless workers.
- Never commit checkpoints, generated outputs, or secrets (`.env`, model files, output images).

## Architecture

TNHComfy is a serverless ComfyUI wrapper with three parts:

- `backend_v2/`: FastAPI + PostgreSQL/pgvector (SQLite-compatible tests) + async job queue
- `frontend_v2/`: React + Vite + Tailwind
- `remote_agent/`: optional remote agent daemon (ComfyUI host side); its shared library `provider_core/` now lives under `remote_agent/provider_core/`. Provider inference engines run in-process inside `backend_v2`.

Main request flow:

`POST /api/generate` -> `JobService.create_job` -> `job_queue.enqueue` -> provider call (`/inference` NDJSON stream) -> `infrastructure/image_processor.py` -> WebSocket event -> frontend refresh.

## Build And Test

Use these entry points unless a task requires something else.

```bash
# Full stack (agent/dev shell)
bash setup_jules.sh

# Full stack (Docker)
# preflight.sh first on a new host: compose declares `metrics` and `proxy` as
# external, and without them `up` fails for every service at network creation.
bash scripts/preflight.sh
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Backend (from backend_v2/)
.venv/bin/pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8002 --reload
pytest

# Frontend (from frontend_v2/)
npm ci
npm run dev -- --host 0.0.0.0 --port 5174
npm test
```

## Conventions

### Backend (`backend_v2/`)

- Services take a request-scoped `Session` and instantiate repositories internally.
- Route handlers should resolve dependencies via `api/deps.py` (`get_session`, `get_*_service`).
- Emit domain events through `core/events.py` helpers (`emit_job_event`). Do not use `emit_download_event`: it was removed on 2026-10-03 with the whole `download.*` event family, which had no producer and no subscriber.
- Use `core/exceptions.py` (`ComfyError` hierarchy) for domain errors.
- Migrations are ordered startup steps in `infrastructure/migrations/`, with no Alembic.
- Config precedence is: `COMFY_*` env vars > `config.json` > `DEFAULT_CONFIG` in `config.py`.
- `metadata` is represented as `metadata_` in Python models and aliased back to `metadata` in API payloads.

### Frontend (`frontend_v2/`)

- Read `frontend_v2/STATE_MANAGEMENT.md` before changing app state.
- Keep state ownership strict:
  - Zustand: client/UI and realtime socket state
  - React Query: server-fetched data and cache
- Use `src/api/client.js` for HTTP requests and `src/api/websocket.js` for socket usage.
- Keep store tests close to stores and use Vitest + Testing Library patterns already present.

- `POST /inference` streams NDJSON progress and finishes with a success or error payload (served by backend in-process engines in `backend_v2/services/engines/`).
- Keep model directory conventions unchanged:
  `models/checkpoints`, `models/loras`, `models/vae`, `models/controlnet`, `models/unet`, `models/clip`.

## Pitfalls

- Tests that create DB sessions must override both dependency sources:
  `api.deps.get_session` and `infrastructure.database.get_session` (see `backend_v2/tests/conftest.py`).
- Vite uses proxy fallbacks in `frontend_v2/vite.config.js`:
  `VITE_PROXY_TARGET` -> `VITE_API_URL` -> `http://localhost:8002`.
- Docker frontend file watching uses Vite polling (`usePolling: true` in `frontend_v2/vite.config.js`); no `CHOKIDAR_USEPOLLING` needed.
- `LoadBalancer` currently uses class-level state in `backend_v2/services/load_balancer.py`; avoid introducing more shared mutable globals.
- Startup recovers pending/running jobs from DB and re-enqueues them; preserve that behavior when changing lifecycle code.
