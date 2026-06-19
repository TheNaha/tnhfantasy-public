# Project Plan: ComfyUI Wrapper Audit, Consolidation, and Repair

This plan outlines the architecture, milestone decomposition, interface contracts, and layout details for auditing, consolidating, and repairing the ComfyUI Wrapper application.

## Architecture
The application is a serverless wrapper around ComfyUI. The backend (`backend_v2`) handles job scheduling, balancing, database storage (SQLite), and event broadcasts via WebSockets. It dispatches inference tasks to serverless worker containers (`provider_containers/modal_worker` and `provider_containers/beam_worker`). The frontend (`frontend_v2`) is a React + Vite application that uses Zustand for client/WebSocket state and React Query for server state.

```
                  ┌─────────────────┐
                  │   Frontend_v2   │
                  │  (React+Zustand)│
                  └────────┬────────┘
                           │ HTTP / WS
                           ▼
                  ┌─────────────────┐
                  │   Backend_v2    │
                  │    (FastAPI)    │
                  └────────┬────────┘
                           │ Inference API (NDJSON)
                           ▼
              ┌─────────────────────────┐
              │   Provider Containers   │
              │  (Modal / Beam Worker)  │
              └─────────────────────────┘
```

## Milestones
The project is decomposed into the following milestones to be completed sequentially:

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Baseline Audit & Test Verification | Run existing backend and frontend test suites, document architecture, verify environment status | None | DONE |
| 2 | Backend Foundation & DI Stabilization | Unify dependency injection around `deps.py`, track background tasks, standardize error handler translations | M1 | DONE |
| 3 | Provider Integration & Health Normalization | Standardize worker contracts, implement robust pre-scheduling health checks, and normalize error payloads | M2 | DONE |
| 4 | Backend Refactoring & Decoupling | Extract job processing from `main.py`, separate provider routes from image-saving, add migration versioning | M3 | DONE |
| 5 | Frontend State & WebSocket Cleanup | Unify Zustand vs React Query boundaries, extract WebSocket lifecycle orchestration from store | M1 | DONE |
| 6 | Frontend Dashboard Monolith Decomposition | Split `Dashboard.jsx` into modular components (grid, filters, selections, container views) | M5 | IN_PROGRESS |
| 7 | Full Test Coverage & Acceptance | Write backend integration tests and frontend component tests, pass 100% tests, verify end-to-end flow | M4, M6 | PLANNED |

## Interface Contracts
### Backend ↔ Provider Workers
- **Protocol**: HTTP POST `/inference` returning NDJSON stream of progress events, concluding with a final status payload.
- **Payload Schema**: Standardized structures defined in `provider_containers/provider_core/models.py`.

### Backend ↔ Frontend WebSockets
- **WebSocket Protocol**: JSON events broadcasted on status changes (e.g., job updates, queue position, output generated).
- **Fallback**: Long-polling backend status endpoints if WebSocket fails.

## Code Layout
- `backend_v2/` - FastAPI backend application
  - `api/` - API routes and FastAPI setup
  - `core/` - Exceptions, events, and entity definitions
  - `services/` - Core business logic
  - `infrastructure/` - Database, image utilities, client integrations
- `frontend_v2/` - React frontend application
  - `src/api/` - HTTP and WebSocket clients
  - `src/components/` - Shared and page components
  - `src/hooks/` - React Query custom hooks
  - `src/store/` - Zustand global state stores
- `provider_containers/` - Container definitions and runner code for serverless backends
