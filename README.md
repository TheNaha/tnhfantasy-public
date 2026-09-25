# TNHComfy

A serverless implementation of ComfyUI designed for scalability and user-friendly Web UI interaction.

## Documentation
For comprehensive details on architecture, frontend, backend, deployment, and APIs, please refer to the [Documentation Directory](docs/README.md):
- [Architecture Overview](docs/architecture.md)
- [Frontend Documentation](docs/frontend.md)
- [Backend Documentation](docs/backend.md)
- [Deployment Guide](docs/deployment.md)
- [API Reference](docs/api.md)
- [SillyTavern Card Compatibility](docs/sillytavern-compatibility.md)

## Overview
This project serves as a dynamic, containerized wrapper around ComfyUI that integrates provider-based serverless inferencing (Modal, Beam), a custom job queuing system, an image gallery, and a local model management system without permanently storing large checkpoints on the backend.

## Architecture Summary
- **tnhcomfy-frontend** (Vite + React)
- **tnhcomfy-backend** (FastAPI)
- **provider-workers** (Serverless instances on Modal or Beam)

## Quick Start
1. Copy `.env.example` to `.env` and configure the backend settings.
2. Copy `.env.example.provider` to each provider environment file referenced by `docker-compose.yml` (for example `.env.modal-hp196`) and configure that provider's credentials.
3. Start the project with the development Compose override and provider profile:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d
   ```
4. Access the Web UI on port 5174.

## Package Manager
The frontend workspace in `frontend_v2` is `npm`-only.
Use `npm install`, `npm run dev`, `npm test`, and `npm run build`.
`pnpm` and `yarn` are intentionally rejected by the frontend `preinstall` guard.

## Project Maintenance
Built to scale seamlessly using serverless providers. Output images are stored on the filesystem and the PostgreSQL database (`COMFY_DATABASE_URL`) is excluded from version control for security.
