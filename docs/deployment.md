# Deployment Guide

Deploying TNHComfy is designed to be straightforward, leveraging Docker and Docker Compose to containerize the frontend, backend, and provider workers. The application relies on external serverless inference providers (Modal or Beam) for heavy computational tasks.

## Prerequisites
- Docker and Docker Compose installed on the host machine.
- Accounts and API keys for Modal and/or Beam for serverless inference execution.
- Optional: A domain name and SSL certificate if exposing to the public internet.

## Configuration (.env)
Before deploying, configure the backend environment and each provider environment file referenced by the Compose file:
```bash
cp .env.example .env
cp .env.example.provider .env.modal-hp196
```
Repeat the provider step for every provider service that should run. Keep all credential files out of version control.
Key variables:
- `HF_TOKEN`: Hugging Face API token for downloading models.
- `CIVITAI_TOKEN`: Civitai API token for accessing specific models.
- `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`: Modal provider credentials (required for Modal providers).
- `BEAM_API_KEY`: Beam provider credentials (optional).

## Using Docker Compose
The provided `docker-compose.yml` orchestrates the backend, frontend, and provider containers.

### Architecture
- **backend_v2**: FastAPI server on port 8002. Runs as `user: "1000:1000"`. Readiness check hits `/api/ready`.
- **frontend_v2**: React/Vite dev server or Nginx (prod). Depends on backend health. Proxied via Traefik.
- **provider-modal** (and other providers): Serverless worker containers. Container names must be `tnhcomfy-{PROVIDER_ID}` for backend auto-detection. Depends on backend health.

### Data Volumes
The `./data` directory is mounted into all containers at `/data`. This shared volume contains:
- Models (`data/models/`)
- Input files (`data/input/`)
- Output images (`data/output/`)
- PostgreSQL data (`data/pgdata`)

### Start the Application
There are two ways to run the application: Production and Development.

**Production Mode:**
Runs the optimized, pre-built frontend and backend without hot-reloading.
1. Ensure the `.env` file is properly configured.
2. Run the following command from the root directory:
   ```bash
   docker compose -f docker-compose.yml --profile providers up -d --build -V
   ```

**Development Mode:**
Runs the application with hot-reloading for both backend and frontend. The provider containers are omitted by default to save resources, but can be included using the `--profile providers` flag.
1. Start core only (Backend + Frontend):
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
   ```
2. Start with providers included:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -d
   ```

The application should now be accessible.
   - **Frontend:** Port 5174 (dev) or 80 (prod via Traefik).
   - **Backend:** Port 8002 (internal, but exposed in dev).

### Adding a Provider
1. Copy the `provider-modal` block in `docker-compose.yml`.
2. Set a unique `PROVIDER_ID` environment variable.
3. Set `container_name` to `tnhcomfy-{PROVIDER_ID}` (required for backend detection).

### Remote Agent
The optional remote ComfyUI agent has its own environment file:
```bash
cp remote_agent/.env.agent.example remote_agent/.env.agent
```
Replace the example model path in `remote_agent/docker-compose.yml` before starting that stack.

To gracefully shut down the application:
```bash
docker compose down
```

## Production Considerations
- **Security:** Ensure that `.env`, provider credential files, the PostgreSQL volume (`data/pgdata`), and generated images (`output` directory) are protected and not publicly accessible.
- **Reverse Proxy:** The `docker-compose.yml` includes Traefik labels for routing. Configure Traefik according to your domain setup.
- **Persistent Data:** The `./data` directory is mapped to the host filesystem via volumes, ensuring data persists across container restarts.
- **Frontend Polling:** Docker frontend file watching requires polling mode (`usePolling: true` in `vite.config.js`).

## Logs
To view the logs for the entire application:
```bash
docker compose logs -f
```
To view logs for a specific service (e.g., backend):
```bash
docker compose logs -f backend_v2
```
