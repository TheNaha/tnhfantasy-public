# Architecture Overview

TNHComfy is designed around a decoupled, microservices-style architecture tailored for generative AI inference workflows. The system is split into three main components:

## 1. Frontend (tnhcomfy-frontend)
- **Framework:** React + Vite
- **State Management:** Zustand (Client State), React Query (Server Data/Cache)
- **Role:** Provides the interactive user interface, rendering job queues, image galleries, and generation parameters. It communicates with the backend via REST APIs and WebSockets.

## 2. Backend (tnhcomfy-backend)
- **Framework:** FastAPI (Python)
- **Role:** Acts as the central orchestrator. It manages the custom job queuing system, exposes REST endpoints for the frontend, coordinates real-time updates via WebSockets, and handles the local model management system without permanently storing large checkpoints on the backend.
- **Data Storage:** Uses a localized SQLite database (`backend_v2/data/db/comfy.db`) for tracking application state, jobs, and metadata. Output images are stored on the filesystem but not tracked in version control.

## 3. Provider Workers
- **Providers:** Serverless instances running on Modal or Beam.
- **Role:** These remote environments execute the actual ComfyUI workflows (inferencing). By offloading heavy compute tasks to scalable serverless providers, the backend remains lightweight and responsive.

## High-Level Flow
1. **User Request:** A user submits a generation request via the Frontend.
2. **Job Queue:** The Frontend sends an API request to the Backend, which queues the job in the local SQLite database.
3. **Dispatch:** The Backend dispatches the job payload to an available Provider Worker (Modal/Beam).
4. **Processing:** The Provider Worker executes the ComfyUI workflow and generates the image.
5. **Completion:** The worker returns the results to the Backend. The Backend saves the output, updates the job status, and triggers a WebSocket event.
6. **Update:** The Frontend receives the WebSocket event and updates the UI with the finished result.
