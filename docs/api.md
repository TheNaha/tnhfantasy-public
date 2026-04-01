# API Reference

TNHComfy exposes REST and WebSocket APIs for job lifecycle, model management, providers, and runtime state.

## Base URL
Typically `http://localhost:8002`.

## Authentication
TNHComfy is designed for trusted/self-hosted environments. If exposed publicly, enforce authentication at the reverse-proxy layer.

## Idempotency-Key

The following endpoints support optional `Idempotency-Key` headers:

- `POST /api/jobs`
- `POST /api/generate`
- `POST /api/generate/batch`

Behavior:

- When the header is provided, identical retries with the same key reuse the same response during a short server deduplication window.
- Deduplication is endpoint-scoped (the same key on different endpoints is treated independently).
- When the header is omitted, each request is treated as a new submission.

## Core Endpoints

### Jobs (`/api/jobs`)

- `GET /api/jobs`: List jobs (supports pagination via `limit` and `offset`).
- `POST /api/jobs`: Create and enqueue one job from a workflow payload.
- `GET /api/jobs/{job_id}`: Fetch one job.
- `DELETE /api/jobs/{job_id}`: Delete one job record.
- `DELETE /api/jobs`: Delete all jobs.
- `POST /api/jobs/{job_id}/retry`: Retry a failed job.
- `POST /api/jobs/validate`: Pre-flight validation for provider/model availability.
- `GET /api/jobs/queue`: Queue status and ETA hints.
- `GET /api/jobs/stats/summary`: Aggregate job statistics.

### Generation (`/api/generate`)

- `POST /api/generate`: Submit a single generation workflow.
- `POST /api/generate/batch`: Submit multiple workflows in one request.

### Models V2 (`/api/v2/models`)

- `GET /api/v2/models`: Grouped model listing.
- `POST /api/v2/models`: Import a model/version selection.
- `PUT /api/v2/models/{model_id}/default-version`: Set model default version.
- `DELETE /api/v2/models/{model_id}`: Delete model and associated status rows.
- `GET /api/v2/models/external/civitai`: Search CivitAI.
- `GET /api/v2/models/external/huggingface`: Search HuggingFace.

### Providers (`/api/providers`)

- `GET /api/providers`: List providers and runtime info.
- `POST /api/providers/wake`: Warm/ensure providers are ready.
- Additional provider management routes are available under `/api/providers/...`.

### Settings and Statistics

- `GET /api/settings`: Read runtime settings.
- `POST /api/settings`: Persist runtime settings.
- `GET /api/statistics`: Retrieve usage and metadata statistics.

### WebSocket

- Endpoint: `ws://localhost:8002/socket.io` (Socket.IO transport).
- Clients subscribe to job/provider events and receive real-time updates (created, progress, completed, failed, cancelled).
