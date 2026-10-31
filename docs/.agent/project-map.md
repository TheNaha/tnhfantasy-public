# TNHFantasy — Project Map

**Recorded commit:** `77e1426c0cc963fbfc0e37927d90fc08b174bf67`
**Commit date:** 2026-10-30 13:53:07 +0700
**Branch:** `master` (working directory clean except `.gitignore` edit per HEAD diff — see diff --stat shows only `.gitignore` changed vs HEAD, 4 insertions / 1 deletion).

This map is dense and scannable, not a code dump. File/module paths are absolute under the repo root `/home/thenaha/containers/stacks/comfyui`. Claims marked `unverified` were not directly confirmed by reading code.

---

## 1. What this is and who uses it

TNHFantasy is an AI fantasy engine with three pillars sharing one data layer (the **World Vault**): image generation, roleplay chat, and a story sandbox. The end user opens the Web UI on port **5174** and, within a single app, generates images, chats with characters (autonomous agentic turns that can narrate scenes or generate images), and edits AI Dungeon–style story chapters with comic/webtoon export. Everything is backed by PostgreSQL 16 + pgvector. There is **no authentication** — the backend binds loopback/named addresses only (`COMFY_BACKEND_BIND`, never `0.0.0.0`).

Three pillars over one World Vault:
1. **Image generation** — original core. Jobs dispatched by load balancer to provider workers (Modal, Beam, direct ComfyUI, remote agent).
2. **Roleplay chat** — SillyTavern-style, agentic multi-turn pipeline (triage → act → audit → update → illustrate → chain).
3. **Story sandbox** — chapter editor with branches, revisions, illustrations, comic/webtoon export.

Any change must keep working across all three pillars (a stated design rule).

---

## 2. Architecture overview

| Layer | Lives in | Technology | Role |
|---|---|---|---|
| Frontend | `frontend_v2/` | React 19 + Vite + Zustand + React Query | UI, gallery, chat workspace, story sandbox, provider management. Port 5174. Bun only. |
| Backend | `backend_v2/` | FastAPI + SQLModel + Python 3.13 | Orchestrator: routes → services → repositories. Port 8002 (loopback only, no auth). |
| In-process engines | `backend_v2/services/engines/` | Python (modal/beam SDKs, httpx) | Execute inference against provider workers; never run ComfyUI locally. |
| Cloud worker source | `deployables/` | Modal apps + Beam deployments | Runs in Modal/Beam on the other end of engine calls. HOST CLI deploy only (`scripts/deploy.sh`); not imported by backend. |
| Remote agent sidecar | `remote_agent/` | Python + ComfyUI host | Optional self-hosted GPU rig; backend reaches it through `external_worker`. |
| Database | compose `db` service | PostgreSQL 16 + pgvector | The World Vault — jobs, providers, characters, chats, stories, assets. |

**Communication:** The backend is the only service with an HTTP surface. Frontend talks to backend via REST (`/api`, `/api/v2`) and Socket.IO WebSocket (`/socket.io`, `/ws`). Engines call provider workers over the network. No provider sidecar containers in this stack; no standalone provider websocket hook — provider data flows through `useProvidersPageData`.

**Backend entry:** `backend_v2/api/main.py` — lifespan: (1) SQLite init + schema migrations, (2) load balancer state from DB, (3) async job queue + worker pool, (4) recover PENDING/RUNNING jobs, (5) background scheduler, (6) mount Socket.IO ASGI on `/socket.io`. `configure_app()` in `api/app_setup.py` mounts routers, CORS, gzip, security headers, exception handlers.

**Route groups** (`api/routes/`): `gallery`, `jobs`, `generation`, `health`, `interrogate`, `models`, `models_external`, `nodes`, `prompts`, `providers`, `statistics`, `websocket`, `worker_ws`, `files`, `collections`, `settings`, `world_vault` (prefix `/api/v2`).

**World Vault routes** (`api/routes/world_vault/__init__.py`): registers `characters`, `chats` (+ `branches` nested), `lorebooks`, `memories`, `scenarios`, `personas`, `worlds`, `stories` (+ chapters/revisions/beats nested), `voices`, `world_hub`, `locations`, `timeline`, `graph_layout`, `graph_edges`, `util`, `onboarding`, `agents`, `llm_config`.

**Frontend entry:** `frontend_v2/src/main.jsx` → `App.jsx` (React Router v6, lazy pages, `QueryClientProvider`, `ErrorBoundary`, `ConfirmationHost`, `toast`). Sidebar nav from `constants/navigation.js` (`EXPERT_TOOLS`) rendered in `components/Layout.jsx` and `RoleplayWorkspace.jsx`. Auth: none.

**State split (frontend):** Zustand holds UI state, drafts, realtime job updates only. React Query holds all server data. Rule: do not store server data in Zustand. Stores: `useStore.js` (activeCollection only), `generatorStore.js` (generation drafts, persisted localStorage), `settingsStore.js`, `worldVaultStore.js`, `confirmationStore.js`.

**DB sessions:** request-scoped `Session` via `api/deps.py get_session`; services create their own repositories internally. Tests must override BOTH `api.deps.get_session` and `infrastructure.database.get_session`.

**Config precedence:** `COMFY_*` env vars > `config.json` > `DEFAULT_CONFIG` in `config.py`. `.env` (Pydantic Settings) carries infrastructure secrets (`COMFY_DATABASE_URL`, `OUTPUT_DIR`, `INPUT_DIR`, `COMFY_PREVIEW_CACHE_DIR`, `HF_TOKEN`, `CIVITAI_TOKEN`, `MODAL_TOKEN_*`, `BEAM_API_KEY`, `COMFY_CORS_ORIGINS`, `COMFY_WORKER_BACKEND_URL`). `config.json` carries runtime app behavior (job concurrency, timeouts, retries, image processing, scheduler intervals) and is UI-editable via API.

**Entity aliasing:** Python models use `metadata_`, aliased to `metadata` in API payloads.

**Migrations:** No Alembic. `infrastructure/migrations/steps.py` — `MigrationStep(version, description, apply_fn)`; 111 steps versions `001_jobs_started_completed` … `111_...`. `schema_migrations` table records applied versions; each step idempotent (checks columns/tables before `ALTER TABLE ... ADD COLUMN`). `run_migrations(engine)` acquires a Postgres advisory lock at startup. Steps run once at startup and are recorded. `test_database` asserts subsets only.

---

## 3. User-facing glossary

**Sidebar / navigation** — `components/Layout.jsx` + `constants/navigation.js` (`EXPERT_TOOLS`). Entries: World Vault (`/world-vault`), World Architect (`/world-architect`), Characters (`/characters`), Personas (`/personas`), Activity (`/activity`), World Graph (`/world-graph`), Locations (`/locations`), Scenarios (`/scenarios`), Voices (`/voices`), Lorebooks (`/lorebooks`), LLM Studio (`/llm-studio`). Expert tools appear behind a disclosure control on both Layout sidebar and Roleplay Home. If a user says "the thing in the sidebar doesn't update," look at `EXPERT_TOOLS` (shared list, kept in sync) + `Layout.jsx` active state + React Query invalidation for that page.

**Dashboard** — `pages/Dashboard.jsx`. Gallery of generated images; realtime WS job events; lightbox delete (`Dashboard.lightboxDelete.test.jsx`); auto-refresh hook `useGalleryAutoRefresh.js`.

**Generator pages** — `SimpleGenerator.jsx` (t2i preset), `AdvancedGenerator.jsx` (custom ReactFlow graph compiled by `utils/WorkflowCompiler`), `BatchGenerate.jsx`, `Img2ImgGenerator.jsx`, `InpaintGenerator.jsx`. Draft lives in `store/generatorStore.js` (Zustand, persisted localStorage). "Generate" → `api/jobs.js` `POST /api/jobs` `{workflow, metadata, task_type: "image"}` + `Idempotency-Key` header. If a user says "that button does nothing" after import/generation, look here → job submission → engine → WS event → gallery.

**ChatWorkspace** — `pages/ChatWorkspace.jsx` + context `contexts/ChatWorkspaceContext.jsx` (`useChatWorkspaceMutations`). Send path: user types → `sendMessage` mutation → `POST /api/v2/chats/{chat_id}/messages` → `api/routes/world_vault/chats.py` `add_message` → `_send_message` → `pipeline_runner.run_from("triage", ctx)`.

**RoleplayWorkspace** — `pages/RoleplayWorkspace.jsx`. Gallery/launcher listing chats and stories; clicking a chat navigates into ChatWorkspace.

**LLM Studio** — `pages/LLMStudio.jsx`. Models, agents, and the roleplay pipeline. Serves the pipeline manifest (`GET /api/v2/llm/pipeline` — backend `services/chat_pipeline.py` is authoritative; `GET /api/v2/llm/director/gates` for gates). AgentPromptVariant (`variant:<slug>`) editable here; overrides prompt+samplers; wired into job_processing, chats, simulate.

**StorySandbox** — `pages/StorySandbox.jsx`. Chapter editor; branches; revisions; AI continuations; comic/webtoon export (`services/comic_exporter.py`). `StoryReader.jsx` for reading.

**Characters / Personas / Lorebooks / Worlds / Locations / Scenarios / Voices** — CRUD pages under `pages/` + World Vault routes. `Characters.jsx` has `confirmationStore` mock in tests (gotcha: page tests need confirmationStore mock).

**Providers** — `pages/Providers.jsx` + `Providers.realtime.test.jsx`. Fleet dashboard: overview strip, transport grouping, lifecycle chips, VRAM chart, boot times, toasts. Shutdown endpoint + UI control (`POST /api/v2/providers/{id}/shutdown` uses `ValidationError` 400 not `ComfyError` 500). Continuous telemetry polling; telemetry status engine; warm-window lifecycle.

**Notifications** — `react-hot-toast` toasts (top-right, dark theme). `ConfirmationHost`/`ConfirmationModal` + `confirmationStore.js` for destructive actions.

**Global command palette** — `components/GlobalCommandPalette.jsx`; keyboard shortcuts via `useKeyboardShortcuts.js`.

**Jobs / queue** — `components/QueueVisualization.jsx`; realtime via `useJobsRealtime.jsx`, `useJobStatus.js`, `useJobRecovery.js`. Job events over Socket.IO `tnhfantasy_job_events` channel.

---

## 4. Key flows traced end to end

### A. Image generation (UI click → gallery refresh)
1. Frontend generator page (`SimpleGenerator`/`AdvancedGenerator`) builds ComfyUI workflow + metadata from `generatorStore` draft. `useGeneratorJob` wires `handleGenerate`.
2. `api/jobs.js` `POST /api/jobs` `{workflow, metadata, task_type:"image"}` + idempotency key. `frontend_v2/src/api/websocket.js` `cancelJob`, Socket.IO to `/ws`, subscribes to `job.*` events.
3. Backend `api/routes/jobs.py` `create_job` → `JobService.create_job` → validation → DB insert (initial status) → `job_queue.enqueue`.
4. Worker pool claims job → `_process_job` → `_call_provider`: `load_balancer` picks provider (gates on `status=="healthy"`), `engine_factory` builds engine (reads config before fallback; registry `default` seeds `ProviderModal`), engine calls provider worker over network (Modal/Beam HTTP/WebSocket, direct URL, or remote agent). Retries via tenacity (base 1s, max 60s); 400 bypasses retries; `COMFY_JOB_TIMEOUT` (default 3600s) client stream timeout.
5. Images returned → `asset_reconciler` → `/api/files` (thumbnails + blurhash) → `job.status = COMPLETED` → WebSocket event (`emit_job_event`, `CROSS_PROCESS_EVENT_CHANNEL = tnhfantasy_job_events`) → frontend gallery refresh.
6. Error paths: retryable vs non-retryable; job failure states. `enabled:false` on a provider means paused on purpose — never treated as broken.

### B. Roleplay chat turn (send message → state update → image)
1. `ChatWorkspace` `sendMessage` → `POST /api/v2/chats/{chat_id}/messages` → `chats.py` `add_message` → `_send_message`: inserts user message row, loads chat/messages/characters/ctx_overrides, builds pipeline context dict.
2. `pipeline_runner.run_from("triage", ctx)` walks manifest stages (`services/chat_pipeline.py`): triage → act → audit → update → illustrate → chain. Executors in `pipeline_stages.py` resolved by dotted path at call time.
   - **Triage (Laya System 1):** routes speaker, evaluates pacing, Fate & Skill anti-godmoding check.
   - **Act (Actor Agent):** generation by Character/Narrator/Custom Agent with tailored prompt, variant, directive. LLM call via `llm_engine` / `engine_factory` / `load_balancer`.
   - **Audit (Laya System 1):** evaluates completion; audits 16 narrative state gates.
   - **Update (Statekeeper/Updater):** gated — runs only when a `gate_*` probability crosses `UPDATER_GATE_THRESHOLD` (0.55) or manually triggered. Writes JSON state deltas restricted to fired gates. `GATE_FIELD_MAP` + `allowed_updater_fields` (None/wild=all, []=scene_summary). **Affinity written only by updater.**
   - **Illustrate (Illustrator Agent):** if `IMAGE_TRIGGER_THRESHOLD` (0.65) crossed, formulates ComfyUI visual prompt → image job. `IMAGE_TRIGGER 0.65`.
   - **Chain (Laya System 1):** multi-turn conductor deciding next speaker (up to `MAX_AUTONOMOUS_TURNS=4` autonomous turns) or yielding to user. If `updater_job_id` set, chain is deferred to updater job's completion hook.
3. `is_complete`: bands <0.4 incomplete / >0.6 complete else syntax; `snapshot completion_policy` overrides.
4. Continuations: parent job id in `metadata.continuation_of_job_id`; resolved at write to message via `message_metadata.source_job_id`; same-bubble merge; `continuation_job_ids` stamped on parent. `MAX_CONTINUATION_ATTEMPTS=4` total attempts per turn (confirmed by user).
5. Completion → WS event → frontend updates chat transcript. AgentPromptVariant migration 103: globally unique slug, per-agent `is_active`; `resolve_agent()` accepts `variant:<slug>`; overrides prompt+samplers.

### C. Story sandbox edit → chapter revision
`StorySandbox` → story CRUD via `api/routes/world_vault/stories.py`; chapters nested `/stories/{id}/chapters`; revisions via story revision repo. `character_ids`/`lorebook_ids` persisted through `updateStory.mutate` (not transient UI state). Images finalize → `asset_reconciler` → `/api/files`. Comic/webtoon export via `comic_exporter.py`. `reference_cleanup.scrub_entity_references` scrubs Story+Chat references on delete.

### D. Provider lifecycle
Register/update via `services/provider_service.py` `ProviderService` (`create_provider`, `update_provider`; whitelisted fields; `null` clears). `enabled` defaults True. `enabled:false` = paused on purpose. Setup via `provider_lifecycle_service.py` `setup_provider` (requires in-process engine; 30s `wait_for` `engine.setup_models()`). Health: `check_health` config-only; `load_balancer` gates `status=="healthy"`. Telemetry continuous polling; telemetry status engine; warm-window lifecycle; boot times; VRAM chart. Deploy only via `scripts/deploy.sh` {image,tts,llm,beam,all} [--dry-run] from repo root; no deploy route.

### E. WebSocket / realtime
`api/routes/websocket.py` `ws_manager`; Socket.IO app `socket_app` on `/socket.io`; cross-process NOTIFY channel `tnhfantasy_job_events`; each worker's `WebSocketManager` LISTENs and re-broadcasts to local Socket.IO clients. Frontend `api/websocket.js` `cancelJob` + `job.*` subscriptions.

---

## 5. State and data

**Source of truth:** PostgreSQL 16 + pgvector (World Vault). Tables/repos: Character/character_repo, Chat/chat_repo (get only), Message/message_repo, Story/story_repo, StoryChapter/story_chapter_repo, StoryChapterRevision/story_revision_repo, StoryBeat/story_beat_repo (row-based; beats also JSON on chapter), Lorebook/lorebook_repo, LorebookEntry/lorebook_entry_repo, Persona/persona_repo, World/world_repo, Location/location_repo, Scenario/scenario_repo, VoiceModel/voice_model_repo, CharacterMemory. All in `core/entities.py` + `infrastructure/repositories/`.

**Persists:** jobs, providers, characters, chats, messages, stories, chapters, revisions, lorebooks, personas, worlds, locations, scenarios, voices, memories, assets, schema_migrations.

**Does not persist (ephemeral/UI only):** Zustand `useStore` (activeCollection only), `generatorStore` drafts (persisted to localStorage, not DB — a draft survives refresh but not a different device unless synced), `settingsStore`, `confirmationStore`, React Query server cache.

**MutableList gotcha:** in-place dict mutation inside a `MutableList` does not persist — reassign the column.

**Startup recovery:** re-enqueues PENDING and RUNNING jobs (preserve when changing lifecycle code).

---

## 6. Config and external dependencies

**Env vars (`.env.example` canonical):** `COMFY_DATABASE_URL`, `OUTPUT_DIR`, `INPUT_DIR`, `COMFY_PREVIEW_CACHE_DIR`, `HF_TOKEN`, `CIVITAI_TOKEN`, `MODAL_TOKEN_*`, `BEAM_API_KEY`, `COMFY_CORS_ORIGINS`, `COMFY_WORKER_BACKEND_URL`, `COMFY_BACKEND_BIND` (bind address, loopback only), `COMFY_JOB_TIMEOUT`. `PGVECTOR_TEST_URL` for Postgres/pgvector tests (only set in CI).

**External services:** Modal (comfy-modal-stack, comfy-modal-tts, tnh-llm llama.cpp), Beam (comfy-gpu, comfy-storage, comfy-download, comfyui-extractor, comfy-llm, comfy-tts), direct ComfyUI URL, remote agent (ComfyUI host), Civitai API, HuggingFace. `modal_llm` alias `modal_vllm` runs llama.cpp not vLLM.

**What breaks when missing:** DB down → startup fails (migrations can't run); provider down → load balancer excludes it (gates on healthy), `enabled:false` is intentional pause not breakage; Modal/Beam credentials missing → those provider engines can't call workers but others still work.

**Contracts (tests that pin behavior):** `test_deployable_contract.py` AST-parses `services/engines/` vs `deployables/` both directions (do not unify). `test_provider_core_parity.py` pins `deployables/provider_worker_core` ↔ `remote_agent/provider_core` fork (do not unify). `test_api_docs_contract.py` checks `docs/api.md` (generated) for drift — after router changes run `cd backend_v2 && .venv/bin/python ../scripts/generate_api_docs.py`.

---

## 7. Symptom → suspect table

| User symptom | Most likely places to look (in order) |
|---|---|
| "The thing in the sidebar doesn't update" | `constants/navigation.js` `EXPERT_TOOLS` (shared list), `components/Layout.jsx` active-state, React Query invalidation for the page, `useProvidersPageData` |
| "That button does nothing" (generate/send) | `pages/*Generator.jsx` → `api/jobs.js` POST /api/jobs; `ChatWorkspaceContext` `sendMessage` → `chats.py` `_send_message`; check WS `job.*` events / 400 bypassing retries |
| "Data missing after refresh" | `generatorStore` drafts are localStorage-only (not DB); `useStore` activeCollection only; server data is React Query (refetch on invalidate) |
| "Stale view" / gallery not showing new images | WS event path `emit_job_event` → `CROSS_PROCESS_EVENT_CHANNEL` → `WebSocketManager` LISTEN; `useGalleryAutoRefresh`; `useJobsRealtime` |
| "Feels slow after I import" | `services/character_portability.py` / `reference_cleanup` import; `model_sync` interval 300s; provider health checks / load balancer; large context `MAX_CONTEXT_MESSAGES` |
| "Agent doesn't respond / turn hangs" | `pipeline_runner.run_from` stage walk; `DIRECTOR_TIMEOUT_SECONDS=15`; LLM engine/provider load balancer; `halt` key; chain deferral to updater completion hook |
| "Image not generated from chat" | `illustrate` stage + `IMAGE_TRIGGER_THRESHOLD=0.65`; image submission `services/image_submission.py`; `asset_reconciler` |
| "Provider card says broken but it's paused" | `enabled:false` handling — never treat as broken; `provider_service.get_enabled_providers()` |

---

## 8. Fragile or surprising areas

- `MutableList` in-place dict mutation doesn't persist — reassign column (backend convention).
- `edit-tool` substring hazards; re-read after edit (project memory).
- Frontend `vi.mock` factories must enumerate EVERY page hook; page tests need `confirmationStore` mock.
- `test_deployable_contract.py` / `test_provider_core_parity.py` pin engine↔deployable and provider_core forks — do NOT unify.
- `docs/api.md` is generated; drift fails `test_api_docs_contract.py`. Regenerate after router changes.
- No Alembic; migrations appended to `steps.py` and run once at startup with advisory lock.
- `config.json` keys that nothing reads (e.g., `max_concurrent`, `timeout` semantics) — settings page may promise an effect that never happened (config.py notes).
- `comfy.db` SQLite + `config.json` present at repo root of backend_v2 (dev/local).
- `remote_agent/` and `deployables/` are separate trees not imported by backend; engines name every class/function in them.
- `LoadBalancer` keeps class-level state — do not add more shared mutable globals; don't fire async tasks without tracking.
- Known env failure: `test_pre_generation_triage_with_custom_agents` (real Laya picks user); baseline 125 failures `/tmp/opencode/baseline_failures.txt` (2026-10-15).
- ST JSONL: `export?format=jsonl` + import multipart.
- `ValidationError` → 400; `RequestValidationError.errors()` no `include_url`.
- `UpdateStory`/`ChatRequest` explicit allowed-field whitelists — add new fields; `null` clears.
- `test_database` asserts subsets only; migrations recorded on minimal fixtures.

---

## 9. How to run, build, and test

**New host:** `bash scripts/preflight.sh` (creates external `metrics`/`proxy` networks; reports config that silently disables features). Then:
```
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -V -d
```
(`-V` matters in dev; frontend `node_modules` anonymous volume.) Containers: `tnhfantasy-backend`, `tnhfantasy-frontend`, `tnhfantasy-db`. Dev override mounts `./backend_v2:/app` and repo at `/comfyui`; without it code edits don't reach the running backend. Frontend on port **5174**. Backend bound to loopback/named address via `COMFY_BACKEND_BIND`.

**Backend tests (in container):**
```
docker exec tnhfantasy-backend python -m pytest -q tests/test_job_service.py
docker exec tnhfantasy-backend python -m pytest -q tests/test_job_service.py::test_create_job
```
Full suite ~370s / 3900 tests; host OOMs at 18GB — run targeted files, never vitest concurrent with docker pytest. `test_vram*` needs `/comfyui` on PYTHONPATH. `pytest.ini` `addopts = -n auto` (xdist). Postgres/pgvector tests only when `PGVECTOR_TEST_URL` set.

**Backend lint (host):** `cd backend_v2 && ruff check .` (F only; F401 on; `deployables/` has own ruff.toml; repo root ruff reports ~450 unrelated style errors).

**Frontend (bun only; preinstall guard rejects npm/pnpm/yarn):**
```
cd frontend_v2 && bun run lint && bun run test && bun run build   # == bun run verify
bun run test -- src/path/to/file.test.jsx   # single file
bun run test:e2e                             # Playwright, dev server 5174
```

**Backend outside Docker:** `cd backend_v2 && .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8002 --reload`

**Deploy (host CLI only):** `bash scripts/deploy.sh {image,tts,llm,beam,all} [--dry-run]`; Beam from repo root.

---

## 10. Unverified or unclear

- Exact caller in `ChatWorkspaceContext.jsx` that invokes `sendMessage` on Enter vs send button (referenced but not re-read in this session).
- Whether `Backend outside Docker` `.venv` exists in this checkout (`.venv/` directory present but unverified functional).
- Exact line counts / line numbers for most stage executors (map intentionally avoids line numbers).
- Whether `test_pre_generation_triage_with_custom_agents` failure is still current (baseline dated 2026-10-15; may have been addressed in later commits).
- `frontend_v2/src/pages/` role of `WorldVaultHub.jsx` vs `World Architect` page relationship — not traced.
- The `schedule`/`openspec` directory (`openspec/config.yaml`, `changes/`, `specs/`) purpose not investigated beyond a config read.
- `.agents/`, `.claude/`, `.gemini/`, `.kilo/`, `.kilocode/`, `.poolside/` root directories — purpose unknown, not investigated.
- Exact WebSocket path frontend uses (`/ws` vs `/socket.io` vs proxy) not line-verified.
- Whether all 111 migration steps actually exist (last seen `111_...`; count asserted but full list not enumerated).
- `LLMStudio` test file exists (`LLMStudio.test.jsx`) but pipeline-manifest→UI wiring details not re-verified.