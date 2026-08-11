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

- `backend_v2/`: FastAPI + SQLite (WAL) + async job queue
- `frontend_v2/`: React + Vite + Tailwind
- `provider_containers/`: provider workers (`modal_worker/`, `beam_worker/`) plus shared `provider_core/`

Main request flow:

`POST /api/generate` -> `JobService.create_job` -> `job_queue.enqueue` -> provider call (`/inference` NDJSON stream) -> `ImageService.save()` -> WebSocket event -> frontend refresh.

## Build And Test

Use these entry points unless a task requires something else.

```bash
# Full stack (agent/dev shell)
bash setup_jules.sh

# Full stack (Docker)
docker compose up -d

# Backend (from backend_v2/)
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8002 --reload
pytest

# Frontend (from frontend_v2/)
npm install
npm run dev -- --host 0.0.0.0 --port 5174
npm test
```

## Conventions

### Backend (`backend_v2/`)

- Services take a request-scoped `Session` and instantiate repositories internally.
- Route handlers should resolve dependencies via `api/deps.py` (`get_session`, `get_*_service`).
- Emit domain events through `core/events.py` helpers (`emit_job_event`, `emit_download_event`).
- Use `core/exceptions.py` (`ComfyError` hierarchy) for domain errors.
- Migrations are manual in `infrastructure/database.py` (`_run_migrations()`), no Alembic.
- Config precedence is: `COMFY_*` env vars > `config.json` > `DEFAULT_CONFIG` in `config.py`.
- `metadata` is represented as `metadata_` in Python models and aliased back to `metadata` in API payloads.

### Frontend (`frontend_v2/`)

- Read `frontend_v2/STATE_MANAGEMENT.md` before changing app state.
- Keep state ownership strict:
  - Zustand: client/UI and realtime socket state
  - React Query: server-fetched data and cache
- Use `src/api/client.js` for HTTP requests and `src/api/websocket.js` for socket usage.
- Keep store tests close to stores and use Vitest + Testing Library patterns already present.

### Provider Contract (`provider_containers/`)

- Shared API models live in `provider_containers/provider_core/models.py`.
- `POST /inference` must stream NDJSON progress and finish with a success or error payload.
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
