# Deployment Guide

Deploying TNHComfy is designed to be straightforward, leveraging Docker and Docker Compose to containerize both the frontend and backend. The application relies on external serverless inference providers (Modal or Beam) for heavy computational tasks.

## Prerequisites
- Docker and Docker Compose installed on the host machine.
- Accounts and API keys for Modal and/or Beam for serverless inference execution.
- Optional: A domain name and SSL certificate if exposing to the public internet.

## Configuration (.env)
Before deploying, you must configure the environment variables. Copy the `.env.example` file to `.env` in the root directory and provide the necessary credentials:
```bash
cp .env.example .env
```
Key variables typically include:
- `HF_TOKEN`: Hugging Face API token for downloading models.
- `CIVITAI_TOKEN`: Civitai API token for accessing specific models.
- Any other provider-specific configuration needed for Modal/Beam.

## Using Docker Compose
The provided `docker-compose.yml` orchestrates both the `tnhcomfy-frontend` and `tnhcomfy-backend` containers. It automatically mounts necessary directories (`input`, `output`, `provider_containers`, `backend_v2`, `frontend_v2`) and configures networking.

### Start the Application
1. Ensure the `.env` file is properly configured.
2. Run the following command from the root directory:
   ```bash
   docker-compose up -d --build
   ```
3. The application should now be accessible.
   - **Frontend:** Typically port 5174 (check `docker-compose.yml`).
   - **Backend:** Typically port 8002 (check `docker-compose.yml`).

### Stop the Application
To gracefully shut down the application:
```bash
docker-compose down
```

## Production Considerations
- **Security:** Ensure that `.env`, `backend_v2/data/comfy.db`, and generated images (`output` directory) are protected and not publicly accessible.
- **Reverse Proxy:** The `docker-compose.yml` includes Traefik labels, suggesting a setup where Traefik handles routing, load balancing, and potentially SSL termination. Configure Traefik according to your domain setup.
- **Persistent Data:** The `comfy.db` database and the `output` directory are mapped to the host filesystem via volumes, ensuring data persists across container restarts.

## Logs
To view the logs for the entire application:
```bash
docker-compose logs -f
```
To view logs for a specific service (e.g., backend):
```bash
docker-compose logs -f backend_v2
```
