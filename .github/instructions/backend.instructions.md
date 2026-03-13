---
applyTo: backend_v2/**
description: "Use when editing backend_v2 FastAPI, services, repositories, job lifecycle, or backend tests."
---

# Backend V2 Instructions

## Scope

These instructions apply to backend code in backend_v2 only.

## Architecture Rules

- Keep request flow boundaries intact: route -> service -> repository.
- Services should take a request-scoped Session and instantiate repositories internally.
- Resolve dependencies through api/deps.py (for example get_session and get_*_service).
- Prefer domain errors from core/exceptions.py (ComfyError hierarchy) instead of ad hoc HTTPException branching.
- Emit domain events through core/events.py helpers (emit_job_event, emit_download_event).

## Data And Config Rules

- Preserve current migration model in infrastructure/database.py (_run_migrations()); do not introduce Alembic unless explicitly requested.
- Preserve config precedence: COMFY_* env vars > config.json > DEFAULT_CONFIG in config.py.
- Keep metadata alias behavior intact: metadata_ in Python models, metadata in API payloads.

## Lifecycle And Concurrency Rules

- Preserve startup recovery behavior that re-enqueues pending and running jobs from DB.
- Avoid adding new shared mutable globals; load balancer state is already class-level and sensitive.
- When touching async flows, avoid fire-and-forget tasks without tracking, logging, and error handling.

## Testing Rules

- Run backend tests from backend_v2 with pytest.
- For tests creating DB sessions, ensure overrides cover both api.deps.get_session and infrastructure.database.get_session.
- Keep tests close to existing fixture patterns in backend_v2/tests/conftest.py.

## Fast Checks Before Finishing

- Endpoint changes: verify route models and service calls still match.
- Persistence changes: verify migration safety and backward compatibility.
- Evented changes: verify websocket/event emissions still trigger expected frontend updates.
