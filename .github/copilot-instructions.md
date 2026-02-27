# TNHComfy — Copilot Instructions

## Architecture

TNHComfy is a **serverless ComfyUI wrapper**. The backend never runs ComfyUI — it dispatches generation jobs to serverless GPU workers (Modal, Beam) and manages results locally. Three components communicate over HTTP/WebSocket:

- **`backend_v2/`** — FastAPI (Python 3.11+), SQLite (WAL mode), async job queue
- **`frontend_v2/`** — React 19 + Vite 7 + Tailwind CSS 4
- **`provider_containers/`** — Shared core (`provider_core/`) + per-provider workers (`modal_worker/`, `beam_worker/`)

**Request flow:** Client → `POST /api/generate` → `JobService.create_job` → `job_queue.enqueue` → worker coroutine → `_call_provider()` (streaming NDJSON to Modal/Beam) → images returned → `ImageService.save()` → WebSocket event → frontend gallery refresh.

## Backend Patterns

- **Entities** use `SQLModel` (SQLAlchemy + Pydantic combined). Two coexisting schemas: V1 (`core/entities.py` — flat) and V2 (`core/entities_v2.py` — normalized `ModelV2 → ModelVersion → ModelFile`). V2 is the modern path.
- **Services** (`services/`) take a `Session` in their constructor, create an internal repository, and expose `async` methods. Services are instantiated per-request inside route handlers: `service = get_job_service(session)`.
- **Dependency injection** via `api/deps.py`: `get_session()` yields request-scoped SQLModel sessions. `ContainerManager` is a lazy singleton. `EventBus` is a global singleton.
- **Event system** (`core/events.py`): async pub/sub `EventBus` with dotted event types (`job.created`, `download.progress`). Uses `asyncio.Queue` per subscriber. Emit via `emit_job_event()`, `emit_download_event()`, etc.
- **Exceptions** (`core/exceptions.py`): hierarchy under `ComfyError` with machine-readable `code` field — `NotFoundError`, `ValidationError`, `ProviderError`, `JobError`, `DownloadError`, `ConfigurationError`.
- **Database migrations** are manual column additions in `infrastructure/database.py._run_migrations()` — no Alembic. FTS5 virtual tables for prompt search.
- **Caching** (`infrastructure/cache.py`): in-memory TTL/LRU via `cachetools`. Use `@cached("cache_name")` decorator; `invalidate_cache("name")` to bust.
- **Config precedence**: env vars (`COMFY_*`) > `config.json` (runtime-editable via API) > `DEFAULT_CONFIG` dict in `config.py`.
- **`metadata_` aliasing**: The `metadata` field is stored as `metadata_` in Python (avoids `BaseModel.metadata` conflict) but serialized as `"metadata"` via Pydantic `alias="metadata"`.
- **Logging**: `structlog` via `get_logger("module_name")` from `infrastructure/logging.py`.

## Frontend Patterns

- **State management** — read `frontend_v2/STATE_MANAGEMENT.md` before changing state logic:
  - **Zustand** (`src/store/`): client-only state (UI, forms, WebSocket job progress)
  - **React Query** (`@tanstack/react-query`): server data fetching, caching, mutations
  - Never duplicate state between Zustand and React Query
- **API client** (`src/api/client.js`): centralized `request()` with `api.get/post/put/delete/patch` helpers. Dev mode uses Vite proxy (relative URLs).
- **WebSocket** (`src/api/websocket.js`): Socket.IO singleton with room-based topic subscriptions. Backend mounts Socket.IO at `/socket.io`.
- **Stores** have co-located tests (e.g., `jobStore.test.js`). Use Vitest + Testing Library.

## Provider Workers

Workers in `provider_containers/` share `provider_core/models.py` for the API contract:
- `POST /inference` — streaming NDJSON response with progress updates
- `POST /download`, `POST /list-models`, `POST /delete-model`, `POST /upload`

Standardized model directories: `models/checkpoints`, `models/loras`, `models/vae`, `models/controlnet`, `models/unet`, `models/clip`.

## Development & Testing

```bash
# Full stack (Docker)
docker-compose up -d          # Backend :8002, Frontend :5174

# Cloud/agent workspace
bash setup_jules.sh            # Starts backend :8002 + frontend :5173

# Backend tests (from backend_v2/)
pip install -r requirements.txt
pytest                         # asyncio_mode=auto, in-memory SQLite

# Frontend tests (from frontend_v2/)
npm install
npm test                       # vitest run
npm run test:watch             # vitest watch mode
```

**Test gotcha**: test fixtures must override **both** `api.deps.get_session` AND `infrastructure.database.get_session` — some routes import from different locations. See `tests/conftest.py`.

## Key Conventions

- Route files define inline Pydantic request/response models at top, then `router = APIRouter(prefix="/api/...", tags=[...])`.
- `LoadBalancer` uses **class-level** state with `threading.Lock` (not instance-level) — state persists across instances within the same process.
- Image post-processing (WebP thumbnails at 512px + blurhash) runs as async background task after job completion.
- On startup, PENDING/RUNNING jobs are recovered from DB and re-enqueued (in-memory `asyncio.Queue`).
- Request deduplication via `infrastructure/request_dedup.py` — `deduplicated(key, coro)` prevents duplicate concurrent work.
- Never run ComfyUI locally or commit model checkpoints/output images.
