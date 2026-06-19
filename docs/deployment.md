# Deployment Guide

Deploying TNHComfy is designed to be straightforward, leveraging Docker and Docker Compose to containerize the frontend, backend, and provider workers. The application relies on external serverless inference providers (Modal or Beam) for heavy computational tasks.

## Prerequisites
- Docker and Docker Compose installed on the host machine.
- Accounts and API keys for Modal and/or Beam for serverless inference execution.
- Optional: A domain name and SSL certificate if exposing to the public internet.

## Configuration (.env)
Before deploying, you must configure the environment variables. Copy the `.env.example` file to `.env` in the root directory and provide the necessary credentials:
```bash
cp .env.example .env
```
Key variables:
- `HF_TOKEN`: Hugging Face API token for downloading models.
- `CIVITAI_TOKEN`: Civitai API token for accessing specific models.
- `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`: Modal provider credentials (required for Modal providers).
- `BEAM_API_KEY`: Beam provider credentials (optional).

## Using Docker Compose
The provided `docker-compose.yml` orchestrates the backend, frontend, and provider containers.

### Architecture
- **backend_v2**: FastAPI server on port 8002. Runs as `user: "1000:1000"`. Health check hits `/api/health`.
- **frontend_v2**: React/Vite dev server or Nginx (prod). Depends on backend health. Proxied via Traefik.
- **provider-modal** (and other providers): Serverless worker containers. Container names must be `comfy-provider-{PROVIDER_ID}` for backend auto-detection. Depends on frontend health.

### Data Volumes
The `./data` directory is mounted into all containers at `/data`. This shared volume contains:
- Models (`data/models/`)
- Input files (`data/input/`)
- Output images (`data/output/`)
- Database (`data/db/comfy.db`)

### Start the Application
1. Ensure the `.env` file is properly configured.
2. Run the following command from the root directory:
   ```bash
   docker-compose up -d --build
   ```
3. The application should now be accessible.
   - **Frontend:** Port 5174 (dev) or 80 (prod via Traefik).
   - **Backend:** Port 8002 (internal, not exposed directly in production).

### Adding a Provider
1. Copy the `provider-modal` block in `docker-compose.yml`.
2. Set a unique `PROVIDER_ID` environment variable.
3. Set `container_name` to `comfy-provider-{PROVIDER_ID}` (required for backend detection).

### Stop the Application
To gracefully shut down the application:
```bash
docker-compose down
```

## Production Considerations
- **Security:** Ensure that `.env`, `backend_v2/data/db/comfy.db`, and generated images (`output` directory) are protected and not publicly accessible.
- **Reverse Proxy:** The `docker-compose.yml` includes Traefik labels for routing. Configure Traefik according to your domain setup.
- **Persistent Data:** The `./data` directory is mapped to the host filesystem via volumes, ensuring data persists across container restarts.
- **Frontend Polling:** Docker frontend file watching requires polling mode (`CHOKIDAR_USEPOLLING=true` is set in the Dockerfile).

## Logs
To view the logs for the entire application:
```bash
docker-compose logs -f
```
To view logs for a specific service (e.g., backend):
```bash
docker-compose logs -f backend_v2
```
