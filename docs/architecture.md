# Architecture Overview

TNHComfy is designed around a decoupled, microservices-style architecture tailored for generative AI inference workflows. The system is split into four main components (frontend, backend, provider worker containers, and PostgreSQL):

## 1. Frontend (tnhcomfy-frontend)
- **Framework:** React + Vite
- **State Management:** Zustand (Client State), React Query (Server Data/Cache)
- **Role:** Provides the interactive user interface, rendering job queues, image galleries, and generation parameters. It communicates with the backend via REST APIs and WebSockets.

## 2. Backend (tnhcomfy-backend)
- **Framework:** FastAPI (Python)
- **Role:** Acts as the central orchestrator. It manages the custom job queuing system, exposes REST endpoints for the frontend, coordinates real-time updates via WebSockets, and handles the local model management system without permanently storing large checkpoints on the backend.
- **Data Storage:** PostgreSQL (+ pgvector for Lorebook/character semantic embeddings) is the single indexer of application state, jobs, metadata, and assets. Output images are stored on the filesystem (synced via the Asset table) and not tracked in version control.

## 3. Provider Workers
- **Providers:** Serverless instances running on Modal or Beam.
- **Role:** These remote environments execute the actual ComfyUI workflows (inferencing). By offloading heavy compute tasks to scalable serverless providers, the backend remains lightweight and responsive.

## 4. PostgreSQL + pgvector
- **Image:** `pgvector/pgvector:pg16`, the `db` service. Every other service waits on its healthcheck.
- **Role:** The single indexer of application state — jobs, providers, characters, chats, lorebooks, stories, assets — across all three pillars. There is no second store to fall back to: the stack is Postgres-only, and `backend_v2/config.py`'s local-dev default is still `sqlite:///./data/db/comfy.db`, which this deployment cannot use because SQLite has no pgvector.
- **Vector columns:** `LorebookEntry.embedding` is `Vector(384)`, which is what powers the semantic lorebook search the roleplay and story context builders rely on. The extension is the reason the database is not interchangeable with a plain Postgres.
- **Schema management:** No Alembic. An ordered list of `MigrationStep(version=..., apply_fn=...)` entries in `backend_v2/infrastructure/migrations/steps.py` runs at backend startup, each recorded in `schema_migrations` and applied once.
- **DSN:** Compose passes discrete `POSTGRES_HOST/PORT/USER/PASSWORD/DB` to the backend and the backend assembles the URL from them. It does so in compose, not in an interpolated string, because the URL is the only place a password can be percent-encoded — interpolating it there produced an unparseable DSN whenever `POSTGRES_PASSWORD` contained `@ : / #`, the backend failed its healthcheck, and nothing behind it started.
- **Migrations and scheduled jobs** are advisory-locked, which is what makes it safe for more than one process to hold the schema.
- **Persistence:** `data/pgdata` is a bind mount, so the World Vault survives `docker compose down -v`. Nothing in this repo takes a backup; `pg_dump` on a schedule is the operator's responsibility.

## High-Level Flow
1. **User Request:** A user submits a generation request via the Frontend.
2. **Job Queue:** The Frontend sends an API request to the Backend, which queues the job in PostgreSQL and dispatches it to an available provider worker.
3. **Dispatch:** The Backend dispatches the job payload to an available Provider Worker (Modal/Beam).
4. **Processing:** The Provider Worker executes the ComfyUI workflow and generates the image.
5. **Completion:** The worker returns the results to the Backend. The Backend saves the output, updates the job status, and triggers a WebSocket event.
6. **Update:** The Frontend receives the WebSocket event and updates the UI with the finished result.
