# Architecture Overview

TNHComfy is an **AI fantasy engine** with three pillars sharing one data layer:

1. **Image generation** — ComfyUI workflows dispatched to serverless workers (Modal, Beam) or a remote ComfyUI sidecar.
2. **Roleplay chat** — SillyTavern-style character chats with an agentic, multi-turn pipeline (triage → act → audit → update → illustrate → chain).
3. **Story sandbox** — an AI Dungeon–style interactive document editor (chapters, branches, illustrations).

All three share the **World Vault** data layer (Characters, Chats, Lorebooks, Stories, Personas, Worlds, Locations, Scenarios, Voices, Memories) in **PostgreSQL 16 + pgvector**. The design rule is that any change must keep working across all three pillars.

---

## Stack at a glance

| Layer | Lives in | Technology | Role |
|---|---|---|---|
| Frontend | `frontend_v2/` | React 19 + Vite + Zustand + React Query | UI, gallery, chat workspace, story sandbox, provider management |
| Backend | `backend_v2/` | FastAPI + SQLModel + Python 3.13 | Orchestrator: routes → services → repositories |
| In-process engines | `backend_v2/services/engines/` | Python (modal/beam SDKs, httpx) | Execute inference against provider workers; never run ComfyUI locally |
| Cloud worker source | `deployables/` | Modal apps + Beam deployments | What runs in Modal/Beam on the other end of the engine calls |
| Remote agent sidecar | `remote_agent/` | Python + ComfyUI host | Optional self-hosted GPU rig; backend reaches it through `external_worker` |
| Database | `data/pgdata` (compose `db` service) | PostgreSQL 16 + pgvector | The World Vault — jobs, providers, characters, chats, stories, assets |

The backend is the only service with an HTTP surface. Everything else (frontend, engines, remote agent) talks to it, or to the database directly.

---

## The backend — request flow

The backend follows a strict layering:

```
Client (HTTP / Socket.IO)
    ↓
api/routes/*.py          — FastAPI routers, whitelisted request models
    ↓
api/deps.py              — Depends(get_session), service constructors
    ↓
services/*.py            — JobService, JobProcessing, ProviderService, etc.
    ↓
infrastructure/repositories/  — one SQLModel repo per domain table
    ↓
PostgreSQL + pgvector
```

Key conventions:

- **Services take a request-scoped `Session`** and build their repositories internally. Routes only get dependencies through `api/deps.py`.
- **Errors** come from the `ComfyError` hierarchy in `core/exceptions.py`, not ad hoc `HTTPException`.
- **Events** flow through `core/events.py` (`emit_job_event`) and reach the frontend over Socket.IO on `/socket.io`.
- **Config precedence:** `COMFY_*` env vars > `config.json` (runtime-editable via the Settings UI, written atomically) > `DEFAULT_CONFIG` in `config.py`.
- **No Alembic.** Migrations are appended as `MigrationStep(version=..., apply_fn=...)` in `infrastructure/migrations/steps.py`, run once at startup and recorded in `schema_migrations`.
- **Python models use `metadata_`**, aliased to `metadata` on the wire.
- **Single uvicorn worker only.** `--workers N` is refused at boot because the websocket broadcast, scheduler, and job recovery are all in-process per-process.

### Startup sequence (`api/main.py` lifespan)

1. Initialize the database and run schema migrations.
2. Load load-balancer state from the DB.
3. Start the async job queue (worker pool).
4. Recover PENDING/RUNNING jobs (handles restarts — order matters; post-processing jobs are finalised before the sweep re-enqueues active ones).
5. Start the background scheduler (vacuum, reconciliation, preview prefetch, data cleanup, job reaper, idle simulation, CivitAI resync).
6. Mount the Socket.IO ASGI app on `/socket.io`.

---

## The three pillars

### 1. Image generation

`POST /api/jobs` → `JobService.create_job` → `job_queue.enqueue` → a worker coroutine picks the job → `execute_job()` → `_call_provider()` → an `InProcessEngine` (Modal, Beam, Direct ComfyUI) runs the ComfyUI workflow over HTTP/WebSocket → results saved → `asset_reconciler` writes thumbnails, blurhash, and the `assets` row → `job.status = COMPLETED` → WebSocket event → frontend gallery refresh.

Retries use tenacity with exponential backoff. 4xx is permanent (no retry); 5xx/429/408 are transient.

Provider engines are selected by provider type in `engine_factory.py`. Provider *selection* (which healthy provider gets a job) is the load balancer's job, filtered by capability (`provider.serves(task_type)`), not by worker type. Worker types are `image`, `llm`, `tts`, and `direct`.

The backend never runs ComfyUI itself. Inference always goes to a worker. Cloud workers are deployed only from the host CLI (`bash scripts/deploy.sh {image,tts,llm,beam,all}`) — there is deliberately no deploy HTTP route.

### 2. Roleplay chat (the 6-stage pipeline)

The chat pipeline is **manifest-driven**, not hardcoded:

- `services/chat_pipeline.py` — the single source of truth. Six stages: **triage** → **act** → **audit** → **update** → **illustrate** → **chain**. Each stage names its owner (laya / actor / updater / illustrator / user), its executor, and its `next_stages`.
- `services/pipeline_runner.py` — walks the graph; nothing walks it by hand.
- `services/pipeline_stages.py` — the actual stage executors.
- `core/pipeline_limits.py` — every limit read by the code itself, so the LLM Studio manifest (`GET /api/v2/llm/pipeline`) cannot quote a number the pipeline doesn't enforce.

Limits: `MAX_AUTONOMOUS_TURNS=4`, `MAX_CONTINUATION_ATTEMPTS=4`, `MAX_AGENTIC_IMAGES=2`, `UPDATER_GATE_THRESHOLD=0.55`, `IMAGE_TRIGGER_THRESHOLD=0.65`, `DIRECTOR_TIMEOUT_SECONDS=15.0`.

Flow for one user message:

1. **Triage** (Laya, inline): picks the agent/variant, sets pacing, runs the Fate & Skill anti-godmoding check.
2. **Act** (actor, a job): the chosen persona generates the reply.
3. **Audit** (Laya, inline): completion check; truncated replies continue inline (continuation budget counts attempts).
4. **Update** (updater, a job): Statekeeper writes gated state deltas to the World Vault (mood, inventory, clock, location, relationships — only the gates that fired).
5. **Illustrate** (illustrator, optional job): the Illustrator agent authors a bounded scene spec (sampler, resolution, steps, LoRA, hires — not a raw ComfyUI graph) when a visual beat warrants it. Opt-in per chat.
6. **Chain** (Laya, deferred to the updater's completion hook): decides up to 4 autonomous turns or yields back to the user. Deferred so it reads the post-update snapshot.

The chat pipeline does **not** go through the job queue's load balancer for its Director decisions — Laya calls its engines directly, out of band, with 15-second timeouts.

### 3. Story sandbox

Chapters, branches, scenes, and illustrations built on the same World Vault entities as chat. Story actions (continue, rewrite, expand, summarize, illustrate, compile) go through the same LLM router and job system. `Chat.story_id` and `Story.chat_id` are nullable provenance columns — each direction is genuinely one-way.

---

## Realtime

The backend mounts a Socket.IO ASGI app on `/socket.io`. Events from the `EventBus` (`core/events.py`) are broadcast into topic rooms (jobs, downloads, reconciliation, provider). The frontend joins rooms and updates Zustand / job state in realtime.

---

## Providers and engines

`backend_v2/services/engines/` is the **entire** provider layer now. The containerized provider workers were removed in the 2026-10-08 consolidation; `provider_core` relocated to `remote_agent/provider_core`.

| Tree | Runs where | Imported by backend? | Deployed how |
|---|---|---|---|
| `backend_v2/services/engines/` | In-process, in the backend container | Yes — this *is* the provider layer | Nothing to deploy |
| `deployables/` | Modal and Beam cloud | Never | `bash scripts/deploy.sh <target>` |
| `remote_agent/` | Your own Docker host | Never | `docker compose` in that directory |

The rule: **the backend never imports a deployable, and a deployable never imports the backend.** Everything crossing that line crosses it over the network.

Engine examples:
- `direct_url` + `remote_comfy` → `DirectComfyEngine`
- `openai_compat` + `ollama` → `OpenAICompatLLMEngine`
- `modal_llm` (legacy alias `modal_vllm`) → `ModalLlamaCPPEngine` (runs **llama.cpp**, not vLLM)

A contract test (`tests/test_deployable_contract.py`) AST-parses engines against deployables in both directions, so names can't drift. Another (`tests/test_provider_core_parity.py`) pins the deliberate fork between `deployables/provider_worker_core` and `remote_agent/provider_core` — do not unify them.

---

## Data layer — the World Vault

One PostgreSQL database, no second store. Core entities (each with a route, a repo, and a frontend consumer):

- `characters`, `chats`, `lorebooks`, `stories`, `personas`, `worlds`, `locations`, `scenarios`, `voice_models`, `memories`, `branches`, `story_chapters`, `story_revisions`

World membership is one indexed `world_id` on each member table (migration `090_world_membership_fks`), not arrays on the `worlds` row — one owner module, `services/world_ownership.py`.

`pgvector` powers semantic search over `LorebookEntry.embedding` (`Vector(384)`) and character memories. The database is not interchangeable with plain Postgres because of the extension.

Assets (output images) live on the filesystem under `data/output/{user_id}/{workspace}/YYYY/MM/DD/`; the `assets` table is the single source of truth for gallery listing, thumbnails, and statistics — no filesystem scans at startup.

---

## Conventions worth knowing (newcomer tripwires)

- **Whitelisted request models** (`UpdateStory`, `ChatRequest`) — add every new field to the whitelist; `null` clears a field. `extra="forbid"` is set on several, so a misspelled field is a 422, not a silent drop.
- **MutableList in-place dict mutation doesn't persist** — reassign the column instead.
- **ValidationError → 400**; `RequestValidationError` → 422 with `{error, code, detail}`.
- **A new World Vault route must be registered** in `api/routes/world_vault/__init__.py`.
- **Frontend state:** Zustand holds UI state, drafts, and realtime job updates; React Query holds server data. Don't store server data in Zustand. Persist World Vault relationships through mutations, not transient UI state. Read `frontend_v2/STATE_MANAGEMENT.md` before changing state logic.
- **Frontend is bun only** — the preinstall guard rejects npm, pnpm, and yarn. Dev port is **5174**, not 5173.
- **Backend binds loopback only** — never `0.0.0.0`. The API has no authentication.
- **`docs/api.md` is generated** — after changing any router, run `scripts/generate_api_docs.py` or `test_api_docs_contract.py` fails.
- **Ruff** selects F only (F401 on); every `# noqa: F401` needs a stated reason. Run `ruff check .` from `backend_v2/` (the repo root reports ~450 unrelated errors).
- **Never commit `.env*` files** — only `.env.example*` is tracked. Several real `.env.*` files with credentials exist at the repo root and are gitignored only by `.gitignore`.
- **Tests:** backend uses xdist (`-n auto`); the full suite has OOM'd this host — run targeted files and never run vitest concurrently with backend pytest. Postgres/pgvector tests need `PGVECTOR_TEST_URL`.

---

## Where to start

- **End-to-end flow:** `api/main.py` (lifespan + request flow) → `api/app_setup.py` (router mounting) → `api/routes/jobs.py` → `services/job_service.py` / `services/job_processing.py` → `services/engines/base.py` (engine contract).
- **Chat pipeline:** `services/chat_pipeline.py` (manifest), `services/pipeline_runner.py`, `services/pipeline_stages.py`, `core/pipeline_limits.py`.
- **World Vault route:** `api/routes/world_vault/__init__.py` (where to register), matching repo in `infrastructure/repositories/`, service in `services/`.
- **Provider engine:** `services/engines/engine_factory.py` + an engine file (`modal_engine.py`, `beam_engine.py`, etc.) + the deployable it talks to in `deployables/`.
- **Frontend:** `src/api/client.js` (how it reaches the backend), `src/store/useStore.js` / `worldVaultStore.js` (Zustand), `src/pages/` (React Query pages).

**Commands:**
- Backend lint: `cd backend_v2 && ruff check .`
- Backend tests: `docker exec tnhcomfy-backend python -m pytest -q <file>`
- Frontend: `cd frontend_v2 && bun run lint && bun run test && bun run build` (== `bun run verify`)
- Backend outside Docker: `cd backend_v2 && .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8002 --reload`
