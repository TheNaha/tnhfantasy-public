# Host scripts

Scripts at the repository root that operators run from the host — never from
inside a container and never from an HTTP route. Each one is a CLI tool with a
documented purpose, preconditions, and exit behaviour.

## `scripts/preflight.sh` — pre-deploy checks

Run before `docker compose up`, on a new host or whenever you want to verify the
stack will start cleanly.

```bash
bash scripts/preflight.sh          # check and create what is missing
bash scripts/preflight.sh --check  # report only, create nothing
```

What it does:

- **Docker networks** — creates the `metrics` and `proxy` networks if missing.
  `docker-compose.yml` declares both as `external: true`, so compose fails at
  network creation for every service if they are absent — with an error that
  names nothing useful.
- **Leftover provider env files** — notes `.env.modal-*`, `.env.llm-local`,
  `.env.tts-modal-hp196`, `.env.direct-url`, `.env.remote-comfy` as safe to
  delete (containerized providers were removed on 2026-10-09; engines now
  resolve credentials from provider rows + `COMFY_PROVIDER_ENV_PATH`).
- **Auth tokens** — verifies `COMFY_PROVIDER_TOKEN` is non-empty in `.env`.
  Both the backend and remote agents fail closed without it. Also flags stale
  `PROVIDER_WORKER_TOKEN` / `COMFY_DISCOVERY_TOKEN` lines from the two-token
  era.
- **Network exposure** — fails on `COMFY_FRONTEND_BIND=0.0.0.0` or
  `COMFY_BACKEND_BIND=0.0.0.0` (the unauthenticated API on every interface).
  Also verifies `COMFY_BACKEND_BIND` is an address this host actually owns, so
  compose does not die with an opaque bind error.
- **Provider state** — reads providers from inside the backend container and
  reports how many are disabled and whether any LLM provider is enabled (chat
  is non-functional without one).
- **Feature gates** — reports `COMFY_IDLE_SIM_ENABLED`,
  `COMFY_LB_HEALTH_CHECKS_ENABLED`, `COMFY_ASSET_MIGRATION_FORCE`,
  `COMFY_DB_POOL_SIZE/MAX_OVERFLOW/POOL_TIMEOUT`, `COMFY_WORKER_HOSTS`,
  `COMFY_DISCOVERY_ALLOWED_HOSTS`, `COMFY_UVICORN_WORKERS` and what each
  costs when unset.

Exit code is non-zero on any `FAIL`.

## `scripts/deploy.sh` — deploy cloud workers

The **only supported way** to ship new code to Modal/Beam deployables. Run on
the host; there is deliberately no `POST /providers/{id}/deploy` route.

```bash
bash scripts/deploy.sh list                 # what can be deployed
bash scripts/deploy.sh check [target]       # preconditions only
bash scripts/deploy.sh image [--dry-run]    # Modal app comfy-modal-stack
bash scripts/deploy.sh tts [--dry-run]      # Modal app comfy-modal-tts
bash scripts/deploy.sh llm [--dry-run]      # Modal app tnh-llm (llama.cpp)
bash scripts/deploy.sh beam [--dry-run]     # all Beam deployments
bash scripts/deploy.sh all [--dry-run]      # every target whose check passes
```

Targets:

- `image` → `deployables/modal/image/modal_app.py` → Modal app `comfy-modal-stack`
- `tts` → `deployables/modal/tts/modal_app.py` → Modal app `comfy-modal-tts`
- `llm` → `deployables/modal/llm/app.py` → Modal app `tnh-llm`
- `beam` → `deployables/beam/beam_app.py` + `deployables/beam/llm_tts_app.py` → 6 Beam deployments

Deploy from the **repository root**: the Modal apps find
`remote_agent/provider_core` and `deployables/provider_worker_core` by walking
up to the repo root, and Beam syncs the working directory into its containers.

See `deployables/README.md` for the name contract (enforced by
`tests/test_deployable_contract.py`) and `docs/provider-architecture.md` for
which tree runs where.

## `scripts/generate_api_docs.py` — regenerate the API reference

Regenerates the exhaustive route index in `docs/api.md` from the live
OpenAPI schema (`app.openapi()["paths"]`).

```bash
cd backend_v2 && .venv/bin/python ../scripts/generate_api_docs.py
```

Run **after changing any router**. `tests/test_api_docs_contract.py` fails if
the documented surface drifts from the live one (every documented path must
exist, and coverage must not fall below 65%). The script replaces everything
between `<!-- BEGIN GENERATED ROUTE INDEX -->` and
`<!-- END GENERATED ROUTE INDEX -->` markers and leaves hand-written prose
untouched.

## `scripts/launch_modal_worker.py` — maintenance helper

One-off helper for launching Modal worker operations. Not part of the deploy
path; use `scripts/deploy.sh` for deployments.

## `scripts/migrate_sqlite_to_pg.py` — data migration

Migrates a SQLite World Vault into PostgreSQL. Reads `COMFY_DATABASE_URL` or
defaults to `sqlite:///./data/comfy.db` (the older flat path — a latent
inconsistency with `backend_v2/config.py`'s `sqlite:///./data/db/comfy.db`).
Not part of normal operation; the running app uses `COMFY_DATABASE_URL` from
the environment or the Compose-assembled DSN.

## `scripts/update_colab_notebooks.py` — notebook sync

Updates the Colab worker notebooks (`TNHFantasy_Colab_Worker.ipynb`,
`TNHComfy_Colab_Worker.ipynb`) so their dead API paths and provider
registration match the current backend surface. Run when the notebook's
backend-facing contract changes.

## Backend maintenance scripts (`backend_v2/scripts/`)

One-off maintenance and migration scripts, run from `backend_v2/`. None are part
of the request path or the deploy path.

### Data migrations

- `migrate_sqlite_to_postgres.py` — Migrates a SQLite World Vault into PostgreSQL.
  Takes `--sqlite-url` and `--pg-url` (or the `COMFY_DATABASE_URL`/`COMFY_SQLITE_DATABASE_URL`
  env vars); both are required. The SQLite source defaults to
  `sqlite:///./data/comfy.db`, a latent inconsistency with `backend_v2/config.py`'s
  `sqlite:///./data/db/comfy.db` default — point `--sqlite-url` explicitly rather
  than relying on the default.
- `migrate_output.py` — Data migration for generated outputs.
- `migrate_unet_models.py` — Data migration for UNET models.

### One-off maintenance

- `reindex_asset_loras.py` — Reindexes asset LoRA metadata.
- `backfill_download_urls.py` — Backfills download URLs; defaults its SQLite source
  to `sqlite:///./data/comfy.db` (same latent path inconsistency as above).
- `clean_preview_cache.py` — Cleans the model-preview cache.
- `benchmark_statistics.py` — Benchmarks statistics generation.

### Remote-agent helper

- `external_worker_client.py` — Client helper for remote agents (`remote_agent/`).

Run each with `python <script>.py --help` for its exact arguments; they read the
same `COMFY_*` environment surface as the backend (see `.env.example`).