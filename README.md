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
2. **On a new host, run `scripts/preflight.sh` first.** Compose declares the `metrics` and `proxy` networks as external, so without it every `up` fails at network creation — for every service, with an error that does not name the cause. It also reports the config that silently disables features.
3. Configure the providers you actually want. Each provider is opt-in via a Compose profile, so there is no one file to copy:
   - `--profile providers` enables `modal-hp196`, `modal-stepmania`, `modal-zetsuke`, `llm-local` and `direct_url`.
   - **Do not copy `.env.example.provider`.** It is an all-commented stub with zero assignments — it is a reference, not a template. It is also missing `.env.llm-local` and `.env.direct-url`, so a copy-driven setup silently ends up with two required `env_file`s absent. Create the per-provider files you need from `.env.example.provider.engines` and fill in only the keys for the providers you enabled.
4. Start the project with the development Compose override and provider profile:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d
   ```
   `-V` (`--renew-anon-volumes`) matters in dev: the frontend's `node_modules` is an anonymous volume initialised from the image, and without `-V` a lockfile change leaves the container serving the previous dependency set with no error.
5. Access the Web UI on port 5174.

## Package Manager
The frontend workspace in `frontend_v2` is `npm`-only.
Use `npm install`, `npm run dev`, `npm test`, and `npm run build`.
`pnpm` and `yarn` are intentionally rejected by the frontend `preinstall` guard.

## Project Maintenance
Built to scale seamlessly using serverless providers. Output images are stored on the filesystem, and the whole `data/` directory — the PostgreSQL cluster (`data/pgdata`), the image output, and the generated `config.json` — is excluded from version control, not just the database. Nothing under `data/` is lost by `docker compose down -v`, because it is a bind mount rather than a named volume, but there is also no automated backup: see `docs/deployment.md`.
