# Deployment Guide

Deploying TNHComfy uses Docker Compose for the frontend, backend, and PostgreSQL. Inference runs **in-process**: each provider is served by an engine in `backend_v2/services/engines/` (Modal, Beam, hosted LLM, Direct/ComfyUI, TTS), not by a sidecar container. Remote ComfyUI hosts attach through the optional `remote_agent/` stack.

## Prerequisites
- Docker and Docker Compose installed on the host machine.
- Accounts and API keys for the serverless provider(s) you intend to use (Modal, Beam, OpenAI/Anthropic/Google, or a Direct ComfyUI URL).
- Optional: a domain name and SSL certificate if exposing to the public internet (Traefik config, not this guide).

## Configuration (.env)
Before deploying, copy the stack env:
```bash
cp .env.example .env
```
`.env.example` is the canonical reference for every `COMFY_*` setting `backend_v2` reads — its default, and what breaks when it is unset. It also documents variables for a host-only run (`setup_jules.sh`, `uvicorn` without compose), where compose's `env_file:` is not in play. It is documentation that happens to be copy-pasteable, not a template to copy blindly.

Per-provider credentials are configured **through the Providers UI or `POST /api/v2/providers`**, not via per-worker env files. The backend passes each provider's credential row to its in-process engine; `preflight.sh` no longer demands a per-worker env file. If you prefer a file over the DB row, the backend resolves a per-provider `.env.<provider_id>` under `COMFY_PROVIDER_ENV_PATH` for engine credential discovery — see `.env.example`.

Key variables surfaced by `.env.example`:
- `HF_TOKEN` / `CIVITAI_TOKEN`: model download tokens.
- `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`, `BEAM_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`: provider credentials.
- `COMFY_PROVIDER_TOKEN`: bearer token that gates remote-agent registration and is attached to outbound calls to remote agents (allowlist via `COMFY_WORKER_HOSTS` / `COMFY_DISCOVERY_ALLOWED_HOSTS`).
- `COMFY_PROVIDER_ENV_PATH=/comfyui`: in-compose mount root for per-provider `.env.<provider_id>` credential discovery.

## Using Docker Compose
`docker-compose.yml` orchestrates the backend, frontend, and PostgreSQL.

### Architecture
- **db**: PostgreSQL 16 with the `pgvector` extension. Everything else waits on its healthcheck. Published on `127.0.0.1:5432` by the dev override only.
- **backend_v2**: FastAPI server on port 8002. Runs as `user: "1000:1000"`. Readiness check hits `/api/ready`. Published on `127.0.0.1:8002` and on `${COMFY_BACKEND_BIND:-100.150.0.4}:8002` (see "Backend reachability"). Its DSN is assembled in-process from `POSTGRES_*`.
- **frontend_v2**: React/Vite dev server or Nginx (prod). Depends on backend health. Proxied via Traefik.

### Backend reachability

**The backend is published on NAMED addresses, never on a wildcard.** A bare
`8002:8002` in a compose file publishes the entire unauthenticated API on every
interface the host has: `GET`/`POST` on every route, `DELETE /api/jobs`, and
`PATCH /api/v2/providers/{id}`. Nothing in front of it authenticates. On
2026-10-01 an ordinary audit probe called `DELETE /api/jobs` from the LAN and
destroyed 154 rows of job history, and on 2026-10-03 that is what prompted
removing the wildcard publish.

What the compose file publishes today:

| host address | source | who it serves |
|---|---|---|
| `127.0.0.1:8002` | hard-coded | this machine only |
| `${COMFY_BACKEND_BIND:-100.150.0.4}:8002` | `COMFY_BACKEND_BIND` in `.env` | the operator's own VPN/LAN address (`100.150.0.4` is a NetBird address on this host) |

> This section used to read "**The backend has no host port. Do not add one.**"
> and to list only the in-container and Traefik routes. That stopped being true
> in `7a1f1e93`, which added the two named publishes above, and the document
> kept asserting the opposite. The *rule* is unchanged and still enforced by
> `scripts/preflight.sh`: **never a wildcard**. Verify what is actually
> published with `docker compose ps`.

The API is reached three ways:

- **Traefik**, over the external `proxy` Docker network. Two routers, both on
  the `websecure` entrypoint (443, TLS):
  | router | host | service |
  |---|---|---|
  | `comfyui-frontend` | `comfy.lan.thenaha.my.id` or `100.150.0.4` | `frontend_v2` on 5174 |
  | `comfyui-api` | `comfy-backend.lan.thenaha.my.id` | `backend_v2` on 8002 |

  `comfy.lan.thenaha.my.id` is what a browser uses: the frontend's Vite dev
  server proxies `/api` to the backend in-process, so the browser never needs the
  API hostname. `comfy-backend.lan.thenaha.my.id` exists for `curl`, Postman and
  anything else talking to the API directly.
- **The host**, on the two named addresses above: `http://127.0.0.1:8002` and
  `http://100.150.0.4:8002`.
- **A shell inside the container**, which is where `scripts/preflight.sh` reads
  provider state from:
  ```bash
  docker compose exec backend_v2 curl -s localhost:8002/api/live
  ```

Who may reach it from outside is governed by **the NetBird ACL on the reverse proxy**.

### Frontend reachability — the same boundary applies

**The frontend is a reverse proxy to that API, so its bind address is the API's reach.** `frontend_v2/nginx.conf` and `vite.config.js` forward `location /api/` to `backend_v2:8002`. Publishing the frontend therefore publishes every route above.

The bind comes from `COMFY_FRONTEND_BIND` in `.env`: `unset` → loopback only (`127.0.0.1`/`127.0.0.2`); `COMFY_FRONTEND_BIND=100.150.0.4` → plus that one VPN address; `COMFY_FRONTEND_BIND=0.0.0.0` → every interface (preflight fails on it). Leave unset behind the remote proxy.

### Which database the backend uses
Compose always sets `POSTGRES_HOST=db`, so in this stack the answer is Postgres. Do not put `COMFY_DATABASE_URL` in `.env` unless you intend a non-compose override — `preflight.sh` reports a leftover one as a `note`.

### Data Volumes
The `./data` directory is mounted into all containers at `/data`. Contains models (`data/models/`), inputs (`data/input/`), output images (`data/output/`), and PostgreSQL data (`data/pgdata`).

### Start the Application
There are two ways to run: Production and Development.

**Production Mode:**
1. Run `scripts/preflight.sh` first. It creates the `metrics` and `proxy` networks that `docker-compose.yml` declares `external: true`.
2. Ensure `.env` is configured.
3. `docker compose -f docker-compose.yml up -d --build -V`

**Development Mode** (hot-reload for backend + frontend):
1. `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -V -d`

`-V` (`--renew-anon-volumes`) is **required in dev**: the frontend's `node_modules` is an anonymous volume seeded from the image, and without `-V` a lockfile bump leaves the old dependency tree served with no error.

The application is accessible at **Port 5174** (frontend). The backend has no host port — see "Backend reachability".

### Adding a Provider (in-process engine)
A new provider is a row in the DB, not a compose service. Either:
- create it in the UI: **Providers → + Add Provider**, pick an engine type, and fill its credential fields; or
- `POST /api/v2/providers` with `{ "type": "modal"|"beam"|"openai_compat"|..., "worker_type": "image"|"llm"|"tts"|"direct", "enabled": true, ...credentials }`.

The schema for each type is served by `GET /api/v2/providers/schemas` (`ProviderModal.jsx` is fully schema-driven — type options, credential fields, and config are all rendered from it; save payload is schema-only). An added provider with a live credential resolves on next reconcile to an `InProcessEngine` and can receive jobs immediately; with no credential it is marked `connected:false` until one is supplied. No compose change, no `--profile`, no per-worker env file.

### Remote Agent
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
