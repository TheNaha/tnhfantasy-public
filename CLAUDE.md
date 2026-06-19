# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TNHComfy is a serverless ComfyUI wrapper with three main components:
- **backend_v2/**: FastAPI + SQLite (WAL) + async job queue
- **frontend_v2/**: React + Vite + Tailwind CSS + Zustand + React Query
- **provider_containers/**: Serverless inference workers (Modal, Beam) plus shared `provider_core/`

The backend never runs ComfyUI locally—it dispatches jobs to serverless provider workers.

## Development Commands

```bash
# Full stack (agent/dev shell)
bash setup_jules.sh

# Full stack (Docker)
docker-compose up -d

# Backend (from backend_v2/)
cd backend_v2 && pip install -r requirements.txt && uvicorn api.main:app --host 0.0.0.0 --port 8002 --reload
pytest

# Frontend (from frontend_v2/)
cd frontend_v2 && npm install && npm run dev -- --host 0.0.0.0 --port 5173
npm test
npm run test:watch  # interactive watch mode
npm run test:ui     # browser-based UI
```

## Architecture

### Request Flow
`POST /api/generate` → `JobService.create_job` → `job_queue.enqueue` → provider call (`/inference` NDJSON stream) → `ImageService.save()` → WebSocket event → frontend refresh.

### Backend Structure (`backend_v2/`)
- `api/routes/` — REST endpoints (jobs, models, providers, collections, files, settings)
- `core/` — Domain entities, events, exceptions
- `services/` — Business logic (job queue, load balancer, provider services, gallery indexer)
- `infrastructure/` — Database, HTTP client, image processing, logging
- `api/deps.py` — Single source for request-scoped dependency injection

### Frontend Structure (`frontend_v2/`)
- `src/store/` — Zustand stores for client/UI state (jobStore, settingsStore, useStore)
- `src/hooks/` — React Query hooks for server data
- `src/pages/` — Page components
- `src/components/` — Reusable UI components
- `src/api/` — HTTP client (`client.js`) and WebSocket client (`websocket.js`)

### State Management (Frontend)
**Read `frontend_v2/STATE_MANAGEMENT.md` before changing state logic.**

- **Zustand**: UI state, form drafts, WebSocket-driven job updates
- **React Query**: HTTP fetching, caching, mutations

### Provider Workers (`provider_containers/`)
- Shared API models in `provider_core/models.py`
- `POST /inference` streams NDJSON progress, finishes with success/error payload
- Model directories: `models/checkpoints`, `models/loras`, `models/vae`, `models/controlnet`, `models/unet`, `models/clip`

## Key Conventions

### Backend
- Services take a request-scoped `Session` and instantiate repositories internally
- Route handlers resolve dependencies via `api/deps.py` (`get_session`, `get_*_service`)
- Emit domain events through `core/events.py` helpers (`emit_job_event`, `emit_download_event`)
- Use `core/exceptions.py` (`ComfyError` hierarchy) for domain errors
- Migrations are manual in `infrastructure/database.py` (`_run_migrations()`)—no Alembic
- Config precedence: `COMFY_*` env vars > `config.json` > `DEFAULT_CONFIG` in `config.py`
- `metadata` represented as `metadata_` in Python models, aliased to `metadata` in API payloads

### Frontend
- Use Zustand for client/UI state and WebSocket data
- Use React Query for HTTP requests and server cache
- Provider data flows through `useProvidersPageData` hook as single source of truth
- Collections bootstrapped at app startup; images lazy-loaded when opened

## Important Notes

- **No local ComfyUI**: Never try to run ComfyUI locally in the backend
- **No checkpoints in git**: Large model files, output images, and `.env` are excluded from version control
- **Startup recovery**: Backend re-enqueues PENDING/RUNNING jobs from DB on startup—preserve this behavior
- **LoadBalancer**: Uses class-level state in `backend_v2/services/load_balancer.py`—avoid introducing more shared mutable globals
- **Tests with DB sessions**: Override both `api.deps.get_session` and `infrastructure.database.get_session` (see `backend_v2/tests/conftest.py`)

## Documentation Links

Detailed documentation exists in `docs/`:
- [Architecture](docs/architecture.md)
- [Backend](docs/backend.md)
- [Frontend](docs/frontend.md)
- [API Reference](docs/api.md)

## Additional Context

See `plan.md` for the phased refactor roadmap addressing architectural hotspots like Dashboard.jsx, providers route separation, and frontend state boundaries.

See `.github/instructions/` for domain-specific rules and `.github/copilot-instructions.md` for workspace-level guidance.
