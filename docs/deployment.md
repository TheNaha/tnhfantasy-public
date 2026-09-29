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
cp .env.example.provider.engines .env.modal-hp196
```
**Use `.env.example.provider.engines`, not `.env.example.provider`.** The latter is a
35-line stub in which every assignment is commented out, so copying it produces a
provider with no `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` that cannot start. The engines
file is the canonical reference and says so at its own line 5.

With `--profile providers`, compose needs **all six** provider env files present
(`.env.modal-zetsuke`, `.env.modal-hp196`, `.env.modal-stepmania`,
`.env.tts-modal-hp196`, `.env.llm-local`, `.env.direct-url`) plus `.env`, and
refuses to start if any is missing — `scripts/preflight.sh` hard-fails on exactly
these, deriving the list from the compose file's own `env_file:` entries. There is
no `.env.example.llm-local`; the LLM worker's variables are the provider ones.
`.env.tts-modal-hp196` is the sixth and has its own example: the TTS provider is a
separate container with its own Modal app name, model directory, scale-down
window and timeout. It is the same Modal workspace as the image providers, so its
`MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` are the same credentials, not a new account.

```bash
cp .env.example.provider.engines .env.modal-zetsuke
cp .env.example.provider.engines .env.modal-stepmania
cp .env.example.provider.engines .env.llm-local
cp .env.example.tts           .env.tts-modal-hp196
cp .env.example.direct-url     .env.direct-url
```

Keep all credential files out of version control.
Key variables:
- `HF_TOKEN`: Hugging Face API token for downloading models.
- `CIVITAI_TOKEN`: Civitai API token for accessing specific models.
- `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`: Modal provider credentials (required for Modal providers).
- `BEAM_API_KEY`: Beam provider credentials (optional).

## Using Docker Compose
The provided `docker-compose.yml` orchestrates the backend, frontend, and provider containers.

### Architecture
- **db**: PostgreSQL 16 with the `pgvector` extension. Everything else waits on its healthcheck. Published on `127.0.0.1:5432` by the dev override only.
- **backend_v2**: FastAPI server on port 8002. Runs as `user: "1000:1000"`. Readiness check hits `/api/ready`. Assembles its own DSN from the `POSTGRES_*` variables compose passes it — compose does not set `COMFY_DATABASE_URL`.
- **frontend_v2**: React/Vite dev server or Nginx (prod). Depends on backend health. Proxied via Traefik.
- **providers** (one service per provider, all in the `providers` profile): `provider-modal-zetsuke`, `provider-modal-hp196`, `provider-modal-stepmania`, `provider-tts-modal-hp196`, `provider-llm-local`, `provider-direct-url`. Each is a long-running worker container that self-registers with the backend by heartbeat and holds its own credentials; `provider-tts-modal-hp196` additionally serves as the deploy container for the `comfy-modal-tts` Modal app. Container names must be `tnhcomfy-{PROVIDER_ID}` — the backend derives the name it looks for from the provider id — and they depend on backend health.

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
1. Run `scripts/preflight.sh` first. It creates the `metrics` and `proxy` networks that `docker-compose.yml` declares `external: true`, and reports the config that silently disables features. Without it the command below fails at network creation for *every* service, with an error that does not name the cause.
2. Ensure the `.env` file is properly configured.
3. Run the following command from the root directory:
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
   - **Frontend:** Port 5174 in both modes. The production compose publishes `5174:5174`; the only Traefik router is on the `websecure` entrypoint (443), so there is no port 80 anywhere.
   - **Backend:** Port 8002, published on `0.0.0.0` by the base compose in both modes. It has no authentication, so on a reachable host it is open to anyone who can route to it. Restrict it at the firewall, or bind it to loopback and reach the backend through the frontend's `/api/` proxy.

### Adding a Provider
`ProviderDeployOrchestrator.start_attempt_container` builds its deploy container
from `dockerfile=f"{worker_kind}_worker/Dockerfile"` against `provider_containers`
as the build context, and `backend_v2/infrastructure/providers/runtime.py` looks the
runtime container up by the name `tnhcomfy-{PROVIDER_ID}`. So a new provider is a
block in `docker-compose.yml`, an env example, and the two names inside it that
have to agree:

1. Copy the `provider-llm-local` block — it has no Modal- or Beam-specific
   settings, so it is the one to start from — and paste it into the `providers`
   profile.
2. Set a unique `PROVIDER_ID`. `_infer_discovery_type` in
   `backend_v2/api/routes/providers/crud.py` reads the name, not the image or the
   environment, and falls through to `direct_url`/`image` for anything it does not
   recognise — which registers the provider as an image worker and offers it
   checkpoint jobs its container cannot run. It matches `modal-`, `beam-`, the
   exact string `direct-url`, and the substrings `llm` and `tts`. `tts` is checked
   first, deliberately: `tts-modal-<name>` would otherwise be read as `modal-`.
3. Set `container_name` to `tnhcomfy-{PROVIDER_ID}`, **verbatim** — the underscore
   in `direct_url` is part of the id, not a typo to normalise — and point
   `env_file:` at a `.env.<PROVIDER_ID>` you also add as `.env.example.<PROVIDER_ID>`
   so `scripts/preflight.sh` and the CI compose check can find it.
4. If it needs a credential, copy `.env.example.provider.engines` (never
   `.env.example.provider`, which is an all-commented stub) to
   `.env.<PROVIDER_ID>`.
5. `bash scripts/preflight.sh` and
   `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers config --quiet`
   both read compose's `env_file:` entries, so a new service with no env file fails
   both. CI does the second one on every change to `docker-compose*.yml`,
   `scripts/**` or `.env.example*`.

### Remote Agent
The optional remote ComfyUI agent is a **separate stack** with its own compose
file, its own env file, and its own required variable:
```bash
cd remote_agent
cp .env.agent.example .env.agent
# edit .env.agent and set a real REMOTE_AGENT_TOKEN
```

`DATA_DIR` — the GPU rig's storage root for the agent — must be in **compose's own
environment**, because compose interpolates `${DATA_DIR}` at parse time to build the
bind mount, before any `env_file:` is read. Putting it in `.env.agent` has no
effect: `env_file:` only populates the container environment, and by then the
mount is already resolved. The file makes this a hard requirement (`:?`) rather
than shipping a placeholder path that `up` would create as a literal directory on
the host:

```bash
DATA_DIR=/home/user/ComfyUI/models docker compose up -d
```

The same applies to an exported `DATA_DIR` or a `.env` file *next to* that compose
file. See [`remote_agent/README.md`](../remote_agent/README.md) for the binary
build, the Windows path, and what `DATA_DIR` is expected to point at — note that
`remote_agent/README.md`'s variable table calls it the storage root containing
`models/`, `output/` and `input/`, while the comments in
`remote_agent/docker-compose.yml` still describe it as the models directory. The
two disagree and only the agent's behaviour on the rig can settle it.

To gracefully shut down the application:
```bash
docker compose down
```

## Production Considerations
- **Security:** Ensure that `.env`, provider credential files, the PostgreSQL bind mount (`data/pgdata`), and generated images (`data/output`) are protected and not publicly accessible. Two container-level footguns are already handled and are worth not undoing: the frontend image runs as uid 1000 rather than root (it is the only Traefik-exposed service), and the provider image build excludes nested `.env*` files — the build context is the repository root, so a root-anchored `.dockerignore` pattern would bake `remote_agent/.env.agent`, and with it a live `REMOTE_AGENT_TOKEN`, into a published image layer.
- **Reverse Proxy:** The `docker-compose.yml` includes Traefik labels for routing. Configure Traefik according to your domain setup.
- **Persistent Data:** The `./data` bind mount maps to the host filesystem, so data survives container restarts. `data/pgdata` is the PostgreSQL cluster, `data/output` holds generated images, and `data/config.json` is the Settings UI's writable state file (see `COMFY_CONFIG_PATH` in `docker-compose.yml` — without it the container writes to its own layer and every setting reverts on recreate).
- **No automated backup exists.** Nothing in this repo takes one. `data/pgdata` holds the entire World Vault, so a `pg_dump` on a schedule is the operator's responsibility. `data/old-dont-touch-unless-backup/` exists on some hosts, which is an ad-hoc manual copy, not a procedure.
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
