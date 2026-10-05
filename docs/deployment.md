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

### Which env file is which
Three files, and picking the wrong one is how a provider ends up half-configured:

| file | for | notes |
|---|---|---|
| `.env.example` → `.env` | the compose stack | Read by compose for interpolation *and* injected into the backend via `env_file:`. This is the one `cp` into place. |
| `.env.example.backend` | **the backend's own variables** | **The canonical reference for every `COMFY_*` setting `backend_v2` reads** — its default, and what breaks when it is unset. Use it for a host-only run (`setup_jules.sh`, `uvicorn` without compose), where `env_file:` is not in play. It is not a template to copy over `.env`; it is documentation that happens to be copy-pasteable. |
| `.env.example.provider.engines`, `.env.example.tts`, `.env.example.direct-url` | one file per provider container | Copied to `.env.<PROVIDER_ID>`, as below. |

`scripts/preflight.sh` and `backend_v2/tests/test_env_contracts.py` both read these,
so a variable that no example file mentions fails a test rather than being
discovered missing on a live stack.

### Architecture
- **db**: PostgreSQL 16 with the `pgvector` extension. Everything else waits on its healthcheck. Published on `127.0.0.1:5432` by the dev override only.
- **backend_v2**: FastAPI server on port 8002. Runs as `user: "1000:1000"`. Readiness check hits `/api/ready`. **Publishes no host port at all** — see "Backend reachability" below. Its DSN is assembled in-process from the discrete `POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` that compose passes it, because the URL is the only place a password can be percent-encoded. Compose's own `environment:` block does not set `COMFY_DATABASE_URL`, but `env_file: - .env` does if your `.env` has one — see "Which database the backend uses".
- **frontend_v2**: React/Vite dev server or Nginx (prod). Depends on backend health. Proxied via Traefik.
- **providers** (one service per provider, all in the `providers` profile): `provider-modal-zetsuke`, `provider-modal-hp196`, `provider-modal-stepmania`, `provider-tts-modal-hp196`, `provider-llm-local`, `provider-direct-url`. Each is a long-running worker container that self-registers with the backend by heartbeat and holds its own credentials; `provider-tts-modal-hp196` additionally serves as the deploy container for the `comfy-modal-tts` Modal app. Container names must be `tnhcomfy-{PROVIDER_ID}` — the backend derives the name it looks for from the provider id — and they depend on backend health.

### Backend reachability

**The backend has no host port. Do not add one.** A bare `8002:8002` in a compose
file publishes the entire unauthenticated API on every interface the host has:
`GET`/`POST` on every route, `DELETE /api/jobs`, and `PATCH
/api/v2/providers/{id}`. Nothing in front of it authenticates. On 2026-10-01 an
ordinary audit probe called `DELETE /api/jobs` from the LAN and destroyed 154 rows
of job history, and on 2026-10-03 that is what prompted removing the publish.

The API is reached two ways, and neither is a host port:

- **Traefik**, over the external `proxy` Docker network. Two routers, both on
  the `websecure` entrypoint (443, TLS), both declared as labels in
  `docker-compose.yml`:
  | router | host | service |
  |---|---|---|
  | `comfyui-frontend` | `comfy.lan.thenaha.my.id` or `100.150.0.4` | `frontend_v2` on 5174 |
  | `comfyui-api` | `comfy-backend.lan.thenaha.my.id` | `backend_v2` on 8002 |

  `comfy.lan.thenaha.my.id` is what a browser uses: the frontend's Vite dev
  server proxies `/api` to the backend in-process, so the browser never needs the
  API hostname. `comfy-backend.lan.thenaha.my.id` exists for `curl`, Postman and
  anything else talking to the API directly.
- **A shell inside the container**, which is where `scripts/preflight.sh` reads
  provider state from:
  ```bash
  docker compose exec backend_v2 curl -s localhost:8002/api/live
  ```

Who may reach it from outside is therefore governed by **the NetBird ACL on the
reverse proxy**, not by anything in this repository. If you add a router, you are
adding an unauthenticated endpoint — put it behind the ACL you have already got,
and expect `docs/STATUS.md` to need updating in the same commit.

`http://localhost:8002` on the host answers `000` (connection refused). That is
the security boundary working, not a misconfiguration, and it is the single most
useful thing to know when a document, a curl command or a support answer tells
you to try it.

### Frontend reachability — the same boundary applies

**The frontend is a reverse proxy to that API, so its bind address is the API's
reach.** `frontend_v2/nginx.conf` has `server_name _` and forwards
`location /api/` to `backend_v2:8002` with no host check, and `vite.config.js`
does the same in dev. Publishing the frontend therefore publishes every route
above, and the "no host port" boundary above is undone at the proxy in front of it.

It was published on `0.0.0.0:5174` until 2026-10-04, with a comment arguing that
binding it bought nothing because the backend was the exposure. Measured on the
running stack at the time:

```bash
curl http://192.168.1.28:5174/api/ready   # 200  — the API, on the plain LAN
curl http://192.168.1.28:8002/api/ready   # 000  — as designed
```

The bind now comes from `COMFY_FRONTEND_BIND` in `.env`:

| value | serves |
|---|---|
| unset (default) | `127.0.0.1` and `127.0.0.2` — loopback only, nothing reachable from a network |
| `COMFY_FRONTEND_BIND=100.150.0.4` | loopback **plus** that one VPN address |
| `COMFY_FRONTEND_BIND=0.0.0.0` | **every interface — the hole above.** `preflight.sh` fails on it. |

Two bindings, because one host address cannot be both `localhost` and a VPN
address and losing `http://localhost:5174` is not a trade worth making. Traefik
needs no host port at all — it reaches the service on the `proxy` network — so the
documented deployment can leave the variable unset.

Naming a VPN or LAN address is a deliberate widening: it makes the API reachable
by anything that can route there, which on a home LAN means every device on the
wifi. Prefer leaving it unset and using `https://comfy.lan.thenaha.my.id`.

### Which database the backend uses

`POSTGRES_HOST` is not a fallback — it is the deployment stating which database it
uses. When it is set, the backend assembles the DSN from `POSTGRES_*` and any
`COMFY_DATABASE_URL` is not consulted, **and the discarded value is logged at
boot** as `database_url_from_postgres_env_overrides_comfy_database_url`. Compose
always sets `POSTGRES_HOST=db`, so in this stack the answer is always Postgres.

Therefore: **do not put `COMFY_DATABASE_URL` in `.env`** unless you intend to
override it for a non-compose run. A leftover `sqlite:///...` there is inert for
the compose stack and misleading for anyone reading `docker exec backend printenv`
— and if you ever remove `POSTGRES_HOST`, that same line starts being obeyed and
the backend comes up against an empty database. `scripts/preflight.sh` reports it
as a `note` when it finds one. For a host-only run, use
`.env.example.backend`, which documents the whole variable set.

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
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -V -d
   ```
2. Start with providers included:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d
   ```

`-V` (`--renew-anon-volumes`) is **required in dev, not optional**. The frontend's
`node_modules` is an *anonymous* volume seeded from the image, and the dev
override mounts `package.json` and `package-lock.json` into the running
container. So a lockfile bump is picked up by the container while the dependency
tree it needs is not: `npm` resolves against the *previous* `node_modules` and
serves it, with no error anywhere. `docker volume ls -f dangling=true` will find
the volume. This is why `README.md`, `AGENTS.md` and the header of
`docker-compose.dev.yml` all say `-V`.

The application should now be accessible.
   - **Frontend:** Port 5174 in both modes. There is no port 80 anywhere. Both Traefik routers (frontend and api) are on the `websecure` entrypoint. The host publish is `127.0.0.1:5174` plus `${COMFY_FRONTEND_BIND}:5174` — see "Frontend reachability" above before changing it; the default exposes nothing to a network.
   - **Backend:** No host port in either mode. See "Backend reachability" above — it is reached through Traefik on the `proxy` network or from inside the container, and `http://localhost:8002` is `000` by design.

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
