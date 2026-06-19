# Context

## Overview
This repository contains a ComfyUI Wrapper Application designed to manage generation workflows using serverless container workers (Modal or Beam). The system consists of:
1. **backend_v2**: FastAPI server managing sqlite DB, WebSocket, job queueing, and dispatching.
2. **frontend_v2**: React stateful app rendering dashboard, prompts, and settings.
3. **provider_containers**: Inference workers deployed as container images on serverless platforms.

## Key Files & Entry Points
- Backend entrypoint: `backend_v2/api/main.py`
- Backend dependencies: `backend_v2/api/deps.py`
- Frontend entrypoint: `frontend_v2/src/main.jsx`
- Frontend state: `frontend_v2/src/store/jobStore.js` and hooks in `frontend_v2/src/hooks/`
- Provider interface: `provider_containers/provider_core/models.py`

## Active Environment & Credentials
- Database URL: `sqlite:////data/db/comfy.db`
- Ports:
  - Frontend: `5173` (Vite dev) or `80` (production)
  - Backend: `8002`
  - Providers: `8000`

## Known Hotspots & Architectural Debt
- Shared mutable global state in backend load balancer.
- Blurred data boundaries in frontend between Zustand (job progress) and React Query (history list).
- Monolithic frontend components (`Dashboard.jsx`) causing high maintenance overhead.
- Direct database session access bypassing dependency injection.
