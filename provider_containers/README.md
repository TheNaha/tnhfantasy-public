# Provider Containers — Setup Guide

## Overview

Each provider profile runs in its own Docker container with isolated credentials. Workers are unified into two images: **`image_worker`** (ComfyUI image generation via `ENGINE=modal|beam|direct_url`) and **`llm_worker`** (text generation via `ENGINE=openai_compat|anthropic|google|modal`), sharing the `provider_core` package. Env files live at the repo root (`.env.modal-*`, `.env.llm-local`, etc.).

## Prerequisites

1. **Docker installed** and running
2. **Modal credentials** for each account you want to use
3. **Python packages**: `docker` SDK

```bash
pip install docker
```

## Architecture

```
Backend (ProviderService / ContainerManager)
  ↓ starts/stops
Docker Containers (one per provider)
  ├─ Container 1: Modal Account 1 (port 8000 internally)
  ├─ Container 2: Modal Account 2 (port 8000 internally)
  └─ Container 3: Beam Account (port 8000 internally)
```

Each container:
- Runs an HTTP server (`worker.py`)
- Has its own provider credentials (env vars)
- Exposes port 8000 internally
- Backend communicates via HTTP using the container name `tnhcomfy-{PROVIDER_ID}`

---

## Step-by-Step Setup

### 1. Get Modal Credentials

For each Modal account:

```bash
# Login to Modal
modal token set

# Get your token
modal token show
```

Save the `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET` for each account.

### 2. Create Environment Files

For each provider profile, create an `.env` file:

**`.env.modal-zetsuke` / `.env.modal-stepmania` (repo root):**
```bash
MODAL_TOKEN_ID=ak-xxx...
MODAL_TOKEN_SECRET=as-xxx...
MODAL_USERNAME=account1
MODAL_APP_NAME=comfy-modal-stack
PROVIDER_ID=modal-account1
PORT=8000
```

### 3. Register Provider via Backend API or UI

Providers can be registered via:

**Option A: Provider Discovery (recommended)**
Containers with `BACKEND_URL` set will self-register via `POST /api/v2/providers/discovery`.

**Option B: Backend API**
```bash
curl -X POST http://localhost:8002/api/providers \
  -H "Content-Type: application/json" \
  -d '{
    "id": "modal-primary",
    "type": "modal",
    "enabled": true,
    "priority": 1,
    "credentials": {"username": "zetsuke17"},
    "config": {"app_name": "comfy-modal-stack"}
  }'
```

**Option C: Docker Compose**
Add provider blocks to `docker-compose.yml` with unique `PROVIDER_ID` and `container_name`.

### 4. Build Docker Image

```bash
cd provider_containers/image_worker
docker build -t comfy-provider-image:latest .
```

Or let the system build it automatically when using `docker compose up -d`.

### 5. Start Backend

```bash
cd backend_v2
uvicorn api.main:app --host 0.0.0.0 --port 8002 --reload
```

Or use Docker Compose from the project root:
```bash
docker compose up -d
```

The backend will automatically:
1. Discover running provider containers (if `BACKEND_URL` is set on providers)
2. Register providers via the discovery endpoint
3. Initialize provider instances
4. Add them to the load balancer

### 6. Verify Containers Running

```bash
docker ps
```

You should see:
```
CONTAINER ID   IMAGE                      PORTS
abc123...      tnhcomfy-modal-account1   0.0.0.0:8001->8000/tcp
```

### 7. Test Multi-Profile

Submit a job and watch the load balancer distribute across providers:

```bash
curl http://localhost:8002/api/providers/
```

Should return both providers.

---

## Usage via UI

1. Go to **Providers** page
2. Click **"Add Provider"**
3. Fill in:
   - **Provider ID**: `modal-account3`
   - **Type**: `modal`
   - **Priority**: `3`
   - **Username**: `account3`
4. Click **"Add Provider"**

The backend will automatically:
- Register the provider in the database
- Add it to the load balancer

---

## Troubleshooting

### Container Won't Start

```bash
# Check container logs
docker logs tnhcomfy-modal-account2

# Common issues:
# - Invalid Modal credentials
# - Port already in use
# - Missing .env file
```

### Health Check Fails

```bash
# Test health endpoint directly (default port 8000)
curl http://localhost:8000/health

# Should return:
# {"status":"healthy","provider_id":"modal-account2",...}
```

### ModuleNotFoundError: provider_core During Cloud Deploy

- Symptom:
  - `ModuleNotFoundError: No module named 'provider_core'` while loading `modal_app.py` or `beam_app.py` in cloud runtime.
- Cause:
  - Deploy/build context did not include the sibling `provider_core` package.
- Fix:
  - Use `provider_containers/` as deploy/build context so `provider_core` is available.
  - For Modal cloud functions, keep explicit image packaging for `provider_core` in `image_worker/engines/modal/modal_app.py`.

### Provider Shows "Inactive"

- Container may have crashed - check logs
- Port mapping incorrect
- Credentials invalid

### Jobs Fail with Containerized Provider

```bash
# Test inference endpoint (default port 8000)
curl -X POST http://localhost:8000/inference \
  -H "Content-Type: application/json" \
  -d '{"workflow": {...}}'
```

---

## Manual Container Management

### Start Container Manually

```bash
docker run -d \
  --name tnhcomfy-modal-test \
  --env-file .env.modal1 \
  --network tnhcomfy \
  comfy-provider-modal:latest
```

### Stop All Provider Containers

```bash
docker ps | grep tnhcomfy- | awk '{print $1}' | xargs docker stop
```

### Remove All Provider Containers

```bash
docker ps -a | grep tnhcomfy- | awk '{print $1}' | xargs docker rm
```

---

## Benefits

✅ **True Multi-Account**: Each container uses different Modal credentials  
✅ **Isolated Execution**: Containers can't interfere with each other  
✅ **Easy Scaling**: Add more providers by creating new env files  
✅ **Cost Optimization**: Route to cheapest/fastest provider  
✅ **Fault Tolerance**: Automatic fallback if one provider fails  

---

## Beam.cloud Provider Setup

Beam.cloud is now supported as an alternative to Modal.

### 1. Get Beam Credentials

1. Create account at [beam.cloud](https://www.beam.cloud)
2. Get your API key from the dashboard
3. Install Beam CLI: `pip install beam-client`
4. Configure: `beam configure` (or use API key directly)

### 2. Deploy Beam App

Note: worker `/deploy` endpoints are compatibility-only. Trigger deploys through the backend orchestrator (`POST /api/providers/{provider_id}/deploy`) or the Providers UI.

```bash
cd provider_containers/image_worker/engines/beam
beam deploy beam_app.py
```

This deploys the inference, model download, and file management endpoints.

### 3. Create Environment File

Create `.env.beam` at the repo root (docker-compose reads it from there):

```bash
cd /path/to/repo/root
cp .env.example.provider .env.beam
# Edit .env.beam with your credentials
```

**`.env.beam`:**
```bash
BEAM_API_KEY=your-beam-api-key
BEAM_APP_NAME=comfy-beam
PROVIDER_ID=beam-primary
BACKEND_URL=http://backend_v2:8002
```

### 4. Build and Run Container

```bash
# Build
cd provider_containers/image_worker
docker build -t comfy-provider-image:latest .

# Run (or use docker-compose)
docker run -d \
  --name tnhcomfy-beam-primary \
  --env-file .env.beam \
  --network tnhcomfy \
  comfy-provider-image:latest
```

### 5. Add Provider via UI

1. Go to **Providers** page
2. Click **"Add Provider"**
3. Select Type: **beam**
4. Fill in:
   - **Provider ID**: `beam-primary`
   - **API Key**: Your Beam API key
   - **App Name**: `comfy-beam`

---

## Next Steps

- [x] Add Beam.cloud provider implementation
- [x] Unify image + LLM workers on the TaskEvent protocol (openai_compat / anthropic / google / modal-vLLM)
- [ ] Implement storage sync across providers
- [ ] Add cost tracking per provider
- [ ] Monitor container resource usage

---

## Security Notes

🔒 **Never commit `.env.*` files to git!**

Add to `.gitignore`:
```
provider_containers/**/.env.*
!provider_containers/**/.env.example
```

Store credentials securely:
- Use environment variables
- Use Docker secrets
- Use cloud secrets manager (AWS Secrets Manager, etc.)
