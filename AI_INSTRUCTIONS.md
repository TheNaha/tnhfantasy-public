# TNHComfy Codebase - AI Agent Instructions

Hello AI Agent! 🤖 This document provides an overview of the TNHComfy architecture to help you navigate the repository and make changes effectively without breaking the core design.

## 1. High-Level Architecture
TNHComfy is a **serverless** wrapper around ComfyUI. The core premise is that the backend does not run ComfyUI itself. Instead, it dispatches generation jobs to serverless worker containers (like Modal or Beam), while interacting with a local, responsive UI.

### 1.1 Backend (`/backend_v2`)
- **Framework**: FastAPI running on Python 3.11+.
- **Database**: SQLite, stored locally in `backend_v2/data/comfy.db` (this is ignored by Git).
- **Core Logic (`backend_v2/services/`)**: 
  - `job_queue.py` / `job_service.py`: Manages the queue of incoming generation requests.
  - `load_balancer.py` / `provider_service.py` / `container_manager.py`: Handles dispatching jobs to external serverless instances and managing container lifecycles.
  - `gallery_indexer.py`: Indexes completed generations into the local database and gallery system.
- **API Routes**: Defined in `backend_v2/api/routes/` and wired up in `backend_v2/api/main.py`.
- **Infrastructure (`backend_v2/infrastructure/`)**: Code for integrating with the serverless providers and database initialization.

### 1.2 Frontend (`/frontend_v2`)
- **Framework**: React 19 + Vite.
- **Styling**: Tailwind CSS and vanilla CSS.
- **State Management**:
  - `Zustand` (found in `src/store/`) for client-side ephemeral state.
  - `React Query` / `@tanstack/react-query` for API data fetching, caching, and synchronization.
  - *Note*: Always refer to `frontend_v2/STATE_MANAGEMENT.md` before making changes to state logic.
- **Source Structure**:
  - `src/components/` and `src/pages/` house the UI views.
  - `src/api/` contains the service wrappers for fetching from the FastAPI backend.

## 2. Development Setup & Execution
If you need to spin up the servers to test your code changes or verify the API, use the provided setup script at the root:

```bash
bash setup_jules.sh
```

**What this does:**
1. Sets up a `.venv` in `/backend_v2`, installs `requirements.txt`, and runs FastAPI on port `8002` in the background.
2. Runs `npm install` in `/frontend_v2` and starts the Vite dev server on port `5173` in the background.

Both servers are bound to `0.0.0.0` so they align seamlessly with cloud VMs and web-based agent workspaces.

## 3. Important Notes
- **Separation of Concerns**: Because this is a serverless architecture, do *not* try to initiate local GPU training or run ComfyUI locally inside the backend app. Always assume inference is outsourced to the providers.
- **Model Checkpoints**: Do not commit large checkpoints or output image blobs.
- **Tooling preferences**: Use `pip` for backend dependencies and `npm` for the frontend.
