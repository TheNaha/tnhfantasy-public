# Phase 3: Container-Based Multi-Profile Setup Guide

## Overview

Phase 3 enables TRUE multi-profile support by running each provider profile in its own Docker container with isolated credentials.

## Prerequisites

1. **Docker installed** and running
2. **Modal credentials** for each account you want to use
3. **Python packages**: `docker` SDK

```bash
pip install docker
```

## Architecture

```
Backend (ProviderManager)
  ↓
ContainerManager
  ↓ starts/stops
Docker Containers (one per profile)
  ├─ Container 1: Modal Account 1 (port 8001)
  ├─ Container 2: Modal Account 2 (port 8002)
  └─ Container 3: Beam Account (port 8003)
```

Each container:
- Runs an HTTP server (`worker.py`)
- Has its own Modal credentials (env vars)
- Exposes port 8000 internally (mapped to unique host port)
- Backend communicates via HTTP

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

**`provider_containers/modal_worker/.env.modal1`:**
```bash
MODAL_TOKEN_ID=ak-xxx...
MODAL_TOKEN_SECRET=as-xxx...
MODAL_USERNAME=account1
MODAL_APP_NAME=comfy-modal-stack
PROVIDER_ID=modal-account1
PORT=8000
```

**`provider_containers/modal_worker/.env.modal2`:**
```bash
MODAL_TOKEN_ID=ak-yyy...
MODAL_TOKEN_SECRET=as-yyy...
MODAL_USERNAME=account2
MODAL_APP_NAME=comfy-modal-stack
PROVIDER_ID=modal-account2
PORT=8000
```

### 3. Update Provider Registry

Edit `backend/provider_registry.json`:

```json
{
  "providers": [
    {
      "id": "modal-primary",
      "type": "modal",
      "enabled": true,
      "priority": 1,
      "credentials": {
        "username": "zetsuke17"
      },
      "config": {
        "app_name": "comfy-modal-stack"
      },
      "container_config": null
    },
    {
      "id": "modal-secondary",
      "type": "modal",
      "enabled": true,
      "priority": 2,
      "credentials": {
        "username": "account2"
      },
      "config": {
        "app_name": "comfy-modal-stack"
      },
      "container_config": {
        "port": 8001,
        "env_file": ".env.modal2"
      }
    }
  ],
  "load_balancing": {
    "strategy": "round-robin",
    "fallback_enabled": true
  }
}
```

**Key Points:**
- `container_config: null` = Direct mode (uses env credentials)
- `container_config: {port, env_file}` = Containerized mode
- Each containerized provider needs a **unique port**

### 4. Build Docker Image

```bash
cd provider_containers/modal_worker
docker build -t comfy-provider-modal:latest .
```

Or let the system build it automatically on first run.

### 5. Start Backend

```bash
cd backend
python server.py
```

The `ProviderManager` will automatically:
1. Build Docker images (if not exists)
2. Start containers for containerized providers
3. Wait for health checks
4. Initialize `ModalProvider` instances

### 6. Verify Containers Running

```bash
docker ps
```

You should see:
```
CONTAINER ID   IMAGE                      PORTS
abc123...      comfy-provider-modal       0.0.0.0:8001->8000/tcp
```

### 7. Test Multi-Profile

Submit a job and watch the load balancer distribute across providers:

```bash
curl http://localhost:8000/api/providers/
```

Should return both providers.

---

## Usage via UI

1. Go to **Settings → Providers**
2. Click **"Add Provider"**
3. Fill in:
   - **Provider ID**: `modal-account3`
   - **Type**: `modal`
   - **Priority**: `3`
   - **Username**: `account3`
   - **Container Port**: `8002`
   - **Env File**: `.env.modal3`
4. Click **"Add Provider"**

The backend will automatically:
- Start a new container on port 8002
- Initialize the provider
- Add it to the load balancer

---

## Troubleshooting

### Container Won't Start

```bash
# Check container logs
docker logs comfy-provider-modal-account2

# Common issues:
# - Invalid Modal credentials
# - Port already in use
# - Missing .env file
```

### Health Check Fails

```bash
# Test health endpoint directly
curl http://localhost:8001/health

# Should return:
# {"status":"healthy","provider_id":"modal-account2",...}
```

### Provider Shows "Inactive"

- Container may have crashed - check logs
- Port mapping incorrect
- Credentials invalid

### Jobs Fail with Containerized Provider

```bash
# Test inference endpoint
curl -X POST http://localhost:8001/run-inference \
  -H "Content-Type: application/json" \
  -d '{"workflow": {...}}'
```

---

## Manual Container Management

### Start Container Manually

```bash
docker run -d \
  --name comfy-provider-modal-test \
  -p 8003:8000 \
  --env-file .env.modal1 \
  comfy-provider-modal:latest
```

### Stop All Provider Containers

```bash
docker ps | grep comfy-provider | awk '{print $1}' | xargs docker stop
```

### Remove All Provider Containers

```bash
docker ps -a | grep comfy-provider | awk '{print $1}' | xargs docker rm
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

```bash
cd backend_v2
beam deploy beam_app.py
```

This deploys the inference, model download, and file management endpoints.

### 3. Create Environment File

```bash
cd provider_containers/beam_worker
cp .env.example .env.beam
# Edit .env.beam with your credentials
```

**`.env.beam`:**
```bash
BEAM_API_KEY=your-beam-api-key
BEAM_APP_NAME=comfy-beam
PROVIDER_ID=beam-primary
BEAM_GPU_TYPE=RTX4090
BACKEND_URL=http://comfy-backend-v2:8002
```

### 4. Build and Run Container

```bash
# Build
cd provider_containers/beam_worker
podman build -t comfy-provider-beam:latest .

# Run
podman run -d \
  --name comfy-provider-beam-primary \
  -p 8004:8000 \
  --env-file .env.beam \
  --network comfy-modal-stack_default \
  comfy-provider-beam:latest
```

### 5. Add Provider via UI

1. Go to **Settings → Providers**
2. Click **"Add Provider"**
3. Select Type: **beam**
4. Fill in:
   - **Provider ID**: `beam-primary`
   - **API Key**: Your Beam API key
   - **App Name**: `comfy-beam`
   - **Container Port**: `8004`

---

## Next Steps

- [x] Add Beam.cloud provider implementation
- [ ] Add RunPod provider implementation  
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
