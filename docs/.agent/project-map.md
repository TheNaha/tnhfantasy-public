# TNHComfy — Project Map

**Source of truth for this map:** code read at commit `2e954680` (maintenance pass fixes + audit), HEAD of `master`. `git status` is clean. A maintenance pass (commits `0c26f948`…`2e954680`) fixed M1–M5, m8–m10 and m7; those items are marked **[FIXED]** below. Anything I could not confirm is marked "unverified".

This is a read-only briefing document. Do not treat it as executable: verify against the code before assuming anything.

---

## 1. What this is and who uses it

TNHComfy is an **AI fantasy engine** with three pillars sharing one data layer (the **World Vault**):

- **Image generation** — ComfyUI workflows dispatched to serverless workers (Modal, Beam) or a remote ComfyUI sidecar / Direct ComfyUI.
- **Roleplay chat** — SillyTavern-style character chats with an agentic, multi-turn "Director" pipeline (triage → act → audit → update → illustrate → chain).
- **Story sandbox** — an AI Dungeon-style interactive document editor (chapters, branches, beats, illustrations, comic/webtoon export).

The user is a single end user running the stack locally (Docker Compose) or on a private VPN/LAN address. There is **no authentication** — anyone who can reach the API can call every endpoint, including destructive ones (`DELETE /api/jobs`, which deleted 154 job-history rows on 2026-10-01). The stack is deliberately bound to loopback + named addresses only, never `0.0.0.0`.

Documentation entry points: `README.md`, `VISION.md` (product intent), `docs/STATUS.md` (authoritative status + open findings), `docs/architecture.md`, `AGENTS.md` (conventions). `docs/api.md` is generated from `app.openapi()` and drift-checked by `tests/test_api_docs_contract.py` — after any router change run `cd backend_v2 && .venv/bin/python ../scripts/generate_api_docs.py`.

---

## 2. Architecture overview

### Stack at a glance

| Layer | Lives in | Technology | Role |
|---|---|---|---|
| Frontend | `frontend_v2/` | React 19 + Vite + Zustand + React Query | UI, gallery, chat workspace, story sandbox, provider management |
| Backend | `backend_v2/` | FastAPI + SQLModel + Python 3.13 | Orchestrator: routes → services → repositories |
| In-process engines | `backend_v2/services/engines/` | Python (modal/beam SDKs, httpx) | Execute inference against provider workers; never run ComfyUI locally |
| Cloud worker source | `deployables/` | Modal apps + Beam deployments | What runs in Modal/Beam on the other end of engine calls |
| Remote agent sidecar | `remote_agent/` | Python + ComfyUI host | Optional self-hosted GPU rig; backend reaches it through `external_worker` |
| Database | `data/pgdata` (compose `db`) | PostgreSQL 16 + pgvector | The World Vault — jobs, providers, characters, chats, stories, assets |

### Request flow (backend)

```
Client (HTTP / Socket.IO)
    ↓
api/main.py           FastAPI app; lifespan runs startup/shutdown
    ↓
api/app_setup.py      CORS, gzip, security headers, router mounting
    ↓
api/routes/*.py       FastAPI routers; whitelisted request models (extra="forbid" on several)
    ↓
api/deps.py           Depends(get_session) → request-scoped Session; service constructors
    ↓
services/*.py         JobService, JobProcessing, ProviderService, DecisionService (Laya), etc.
    ↓
infrastructure/repositories/  one SQLModel repo per domain table
    ↓
PostgreSQL + pgvector
```

Conventions:
- Services take a request-scoped `Session` and build their own repositories; routes only get deps through `api/deps.py`.
- Errors come from the `ComfyError` hierarchy in `core/exceptions.py`, not ad hoc `HTTPException`.
- Events flow through `core/events.py` (`emit_job_event`) → EventBus → Socket.IO on `/socket.io` → frontend rooms (jobs, downloads, reconciliation, provider).
- Config precedence: `COMFY_*` env vars > `config.json` (runtime-editable via Settings UI, written atomically) > `DEFAULT_CONFIG` in `config.py`.
- No Alembic. Migrations are `MigrationStep(version=..., apply_fn=...)` appended in `infrastructure/migrations/steps.py`, run once at startup, recorded in `schema_migrations`.
- Python models use `metadata_`, aliased to `metadata` on the wire.
- Single uvicorn worker only: `--workers N` is refused at boot because the websocket broadcast, scheduler, and job recovery are all in-process per-process. (Startup says multi-worker is "supported" with advisory locks in `main.py` docstring, but `architecture.md` still says single worker — unverified which is current.)

### Startup sequence (`api/main.py` lifespan)

1. Initialize database + run schema migrations.
2. Load load-balancer state from DB.
3. Start the async job queue (worker pool, `job_queue.queue_manager`).
4. Recover PENDING/RUNNING jobs (handles restarts; post-processing jobs finalised before the sweep re-enqueues active ones).
5. Start background scheduler (vacuum, reconciliation, preview prefetch, data cleanup, job reaper, idle simulation, CivitAI resync).
6. Mount Socket.IO ASGI app on `/socket.io`.

Shutdown reverses: cancels background tasks, stops scheduler, stops telemetry polling and broadcast, closes the cross-process dispatch listener.

### Providers and engines

The backend **never imports a deployable**, and a deployable never imports the backend — everything crosses the line over the network.

| Tree | Runs where | Engine examples |
|---|---|---|
| `backend_v2/services/engines/` | In-process, in backend container | `ModalEngine`, `BeamEngine`, `DirectComfyEngine`, `OpenAICompatLLMEngine`, `AnthropicLLMEngine`, `GoogleLLMEngine`, `ModalLlamaCPPEngine` (llama.cpp, **not** vLLM), `ModalTTSEngine`, `BeamLLMEngine`, `BeamTTSEngine`, `RemoteLLMEngine`, `RemoteTTSEngine`, `DirectTTSEngine`, `HybridRemoteEngine` |
| `deployables/` | Modal / Beam cloud | `comfy-modal-stack`, `comfy-modal-tts`, `tnh-llm`, Beam apps |
| `remote_agent/` | Self-hosted Docker host | agent sidecar reached via `external_worker` |

Routing: `services/engines/engine_factory.py` resolves provider type via `services/engines/registry.py` (`resolve_provider_type`), checks credentials via `can_create_engine`, caches engines in a TTLCache (`COMFY_ENGINE_CACHE_TTL_SECONDS`, default 1800s). Per-provider credential files `.env.<provider_id>` are searched at the project root (`COMFY_PROVIDER_ENV_PATH`, default `/comfyui`).

Which provider gets a job: `services/load_balancer.py` (circuit breaker on failure streak, `state_id` per task type — image=1, LLM=2, TTS=3), filtered by capability (`provider.serves(task_type)`). Engine selection by type is in `engine_factory.py`. `job_runner.execute_job` runs dispatch/retry/failover/completion/cancellation for both task types; cancellation uses `JobCancellationTracker`-style abort registry on `InProcessEngine` (base.py `_ACTIVE_JOB_ENGINES` + `_job_aborts`), with stream `aclose` as the actual upstream-interrupt lever.

### Frontend architecture

```
React Query (all server data)   ←  api/client.js (fetch wrapper, 30s default timeout, idempotency-key support)
Zustand (UI state only)          ←  useStore.js (activeCollection), worldVaultStore.js (activeChatId), settingsStore.js, confirmationStore.js
Pages (React.lazy chunks)        ←  src/pages/*.jsx
Hooks                            ←  src/hooks/use*.js (one per domain)
WebSocket                        ←  src/api/websocket.js (socket.io-client, joins rooms)
```

Rule: **Zustand holds UI state, drafts, realtime job updates; React Query holds server data. Never store server data in Zustand.** Persist World Vault relationships through mutations (`updateStory.mutate`, etc.), not transient UI state. `frontend_v2/STATE_MANAGEMENT.md` governs state logic.

Dev port 5174 (not 5173). Bun only — preinstall guard rejects npm/pnpm/yarn. In Docker, Vite proxy target is `backend_v2`; fallback chain `VITE_PROXY_TARGET` → `VITE_API_URL` → `http://localhost:8002`.

---

## 3. User-facing glossary

Terms a user might say, mapped to screens/flows/code.

### Screens / pages (`frontend_v2/src/pages/`)

| What a user might call it | Actual name / path | What it does | Chain behind it |
|---|---|---|---|
| "the front door", "roleplay home" | `RoleplayWorkspace.jsx` (`/`) | Chat list, story list, world count cards, provider-health banner, first-run onboarding wizard | `useChats`, `useStories`, `useWorlds`, `useWorldVaultDashboard`, `useProvidersHealth`; `GET /api/v2/chats`, `/stories`, `/worlds`, `/llm/providers/health` |
| "the gallery", "image grid" | `Dashboard.jsx` (`/dashboard`) | Image gallery grid, date rail, filters, collections, lightbox, active/failed jobs panel, queue visualization | `useGallery`, `useDashboardItems`, `useActiveJobs`, `useJobsRealtime`; `GET /api/gallery`, `/api/jobs`; Socket.IO job rooms |
| "the chat", "chat workspace" | `ChatWorkspace.jsx` (`/roleplay`) | Message timeline, chat input, scene gallery, character/lorebook/world modals, affinity HUD, stage mode | `useChatWorkspace` context, `useMessages`, `useSendMessage`, `useChatJobs`; `POST /api/v2/chats/{id}/messages`; Socket.IO |
| "the story editor", "AI Dungeon" | `StorySandbox.jsx` (`/story/:storyId`) | Chapter editor, beat input, director deck, illustrations, branches, revisions, export | `useStories`, `useStoryChapters`, `useContinueChapter`, `useAddStoryBeat`, `useStoryAiAction`, `usePublishStory`; `POST /api/v2/stories/{id}/chapters`, `/chapters/{id}/continue` |
| "characters" | `Characters.jsx` | Character list, create/edit, import (SillyTavern card), export (bundle / .tnhzip) | `useCharacters`; `GET/POST/PATCH /api/v2/characters`, `POST /import/analyze`, `/import/commit` |
| "lorebooks" | `Lorebooks.jsx` | Lorebook entries, keys, enabled/constant/selective flags | `useLorebooks`; `GET/POST/PATCH /api/v2/lorebooks` |
| "worlds" | `Worlds.jsx` | World list, create/edit | `useWorlds`; `GET/POST/PATCH /api/v2/worlds` |
| "locations", "scenarios", "personas", "voices" | `Locations.jsx`, `Scenarios.jsx`, `Personas.jsx`, `Voices.jsx` | CRUD for each World Vault entity | corresponding `use*()` hooks + `/api/v2/*` routes |
| "LLM Studio" | `LLMStudio.jsx` | Agent/providers/prompt-variant configuration, Director Playground | `useAgents`, `useProvidersPageData`; `/api/v2/llm/*`, `/api/v2/agents/*` |
| "Providers" | `Providers.jsx` | Provider list, enable/disable toggle, health, lifecycle chips, telemetry, VRAM chart, boot times, shutdown control | `useProvidersPageData`; `GET/PATCH /api/v2/providers/*`, `/load-balancer/stats`, `/providers/health` |
| "Models" | `InstalledModels.jsx`, `DiscoverModels.jsx` | Model catalogue, download, validation, civitai sync | `useModels`, `useCivitaiSearch`; `/api/v2/models/*` |
| "Settings" | `Settings.jsx` | Runtime config (system prompts, checkpoint, roles, rag, tts, memory extraction) | `useSettingsStore`; `GET/PUT/DELETE /api/v2/settings`, config.json |
| "Simple/Advanced/Batch/Img2Img/Inpaint generator" | `SimpleGenerator.jsx`, `AdvancedGenerator.jsx`, `BatchGenerate.jsx`, `Img2ImgGenerator.jsx`, `InpaintGenerator.jsx` | Image generation forms, enhancements panel (FreeU, PAG, FaceDetailer), presets | `useGenerationPreflight`, `useGeneratorCore`, `useGeneratorJob`; `POST /api/jobs`, `/api/generate` |
| "Relationship graph" | `RelationshipGraph.jsx` | Node-based wiki of characters/locations/lorebooks | `useWorldVaultSearch`; `/api/v2/world-vault/*` graph routes |
| "Activity", "Statistics" | `Activity.jsx`, `Statistics.jsx` | Job history, download stats | `useJobsRealtime`, `/api/v2/statistics` |
| "World Vault Hub" | `WorldVaultHub.jsx` | Unified vault entry | `useWorldVaultDashboard` |

### Buttons / controls a user might mention

- **"Send" / chat input** — `ChatInputContainer` → `useSendMessage` → `POST /api/v2/chats/{id}/messages` with idempotency key. Optimistic `temp-` message inserted into `useMessages` cache; server reply arrives via polling/refetch (chat jobs poll every 5s while active).
- **"Swipe" / "Regenerate" / "Impersonate" / "Narrate"** — message-level actions on `POST /api/v2/chats/{id}/messages/{id}/swipe`, `/regenerate`, `/impersonate`, `/narrate`.
- **"Generate" (image)** — generator page → `useGeneratorJob` → `POST /api/jobs` → job queue → engine → Socket.IO `JOB_PROGRESS` → gallery refresh.
- **"Cancel" (job)** — `cancel_job` → engine abort registry → sets `_cancelled_jobs` flag + `_abort_job` (fetcher `task.cancel` or response `aclose`) → terminal CANCELLED state.
- **"Recover" (stale job)** — `POST /api/jobs/recover` (force flag). Reports stale jobs instead of failing unless `force=true`; stale window is per job's task-type timeout (was a broken global 300s).
- **"Import card" / "Commit"** — `POST /characters/import/analyze` (dry run, writes nothing), `POST /characters/import/commit` (writes). Re-import merges via `data.extensions.tnhcomfy` id.
- **"Export story" / "Publish story"** — story → comic/webtoon/PDF export (comic exporter job events), `GET /published/{token}/export`.
- **"Enable TTS"** — Settings `ai.ttsEnabled` + `PATCH /api/v2/settings` → `TTS_ENABLE_PAYLOAD`.
- **"Force updater" / "Evaluate director"** — `POST /chats/{id}/director/evaluate`.

### Notification / status behaviors

- "Disconnected from server. Trying to reconnect" toast — Socket.IO handshake 400 when the connecting origin is not in `COMFY_CORS_ORIGINS` (e.g. `http://100.150.0.4:5174` vs `https://100.150.0.4`). HTTP still works; realtime is dead.
- "X is thinking…" placeholder — a failed chat reply that arrived after the terminal WS event; fixed so the terminal handler clears the placeholder (store-level fix).
- Provider "enabled=false" — user paused it on purpose (cost/billing/maintenance). Never treated as broken. Five of six providers are disabled by default; `preflight.sh` reports the count.
- "No providers configured" — was a lie when `useProvidersPageData` published `[]` on a failed fetch; now publishes `isError`/`error` and renders `QueryErrorState`.

---

## 4. Key flows traced end to end

### Flow A: Send a chat message (roleplay)

1. User types in `ChatInputContainer`, hits send → `useSendMessage` mutation → `POST /api/v2/chats/{chatId}/messages` with idempotency key (collapses retries across tabs into one server execution).
2. Optimistic `temp-` message written into React Query `MESSAGES` cache; `api/client.js` posts to backend.
3. Backend `api/routes/world_vault/chats.py` → chat service → **6-stage pipeline** via `services/pipeline_runner.py` walking `services/chat_pipeline.py` manifest:
   - **Triage** (Laya, inline): `DecisionService.evaluate_pre_generation_triage` — picks agent/variant, pacing directive, Fate & Skill check. 4-tier cascade: remote agent → in-process `LayaRunner` → generative JSON fallback → deterministic heuristic (`decision_service.py`, `decision_schema.py`). 15s timeout (`DIRECTOR_TIMEOUT_SECONDS`).
   - **Act** (actor, a job): chosen persona generates the reply through the LLM router / job system.
   - **Audit** (Laya, inline): completion check; truncated replies continue inline (continuation budget `MAX_CONTINUATION_ATTEMPTS=4` counts attempts). Continuation is a branch OUT of audit — illustrate/update/chain do not run on a continuation.
   - **Update** (updater, a job): Statekeeper writes gated state deltas (mood, inventory, clock, location, relationships) strictly to gates that fired (≥ `UPDATER_GATE_THRESHOLD=0.55`). Gate-scoped via `GATE_FIELD_MAP` + `allowed_updater_fields`; affinity written only by updater.
   - **Illustrate** (illustrator, optional job): Illustrator agent authors a bounded scene spec (sampler, resolution, steps, LoRA, hires — not a raw ComfyUI graph) when `IMAGE_TRIGGER_THRESHOLD=0.65` crossed. Opt-in per chat.
   - **Chain** (Laya, deferred to updater's completion hook): up to 4 autonomous turns (`MAX_AUTONOMOUS_TURNS=4`) or yield to user. Deferred so it reads the post-update snapshot.
4. Limits all read from `core/pipeline_limits.py`; manifest served at `GET /api/v2/llm/pipeline`.
5. Frontend refetches messages; new assistant message appears; Socket.IO job events carry `task_type` and `phase` (LLM sub-state travels as `phase`, not `status`).

### Flow B: Generate an image

1. Generator page → `useGeneratorJob` → preflight (`useGenerationPreflight`) → `POST /api/jobs` → `JobService.create_job` → `job_queue.enqueue`.
2. Worker coroutine picks job → `execute_job()` (`job_runner.py`) → load balancer picks provider (capability-filtered, circuit-breaker aware) → `engine_factory.get_engine` → `InProcessEngine.inference` streams TaskEvents (`started`, `node`, `progress`, `completed`, `failed`, `cancelled`).
3. Provider runs ComfyUI over HTTP/WebSocket; ComfyUI ends prompt with `execution_success`, not `executing{null}`.
4. Results saved → `asset_reconciler` (`asset_reconciler.py`) writes thumbnails, blurhash, `assets` row → `job.status = COMPLETED` → `emit_job_event(EventType.JOB_PROGRESS)` → Socket.IO → frontend gallery refresh (`refetchNewestGalleryPage`).
5. Retries: tenacity exponential backoff (base 1s, max 60s); 4xx permanent, 5xx/429/408 transient. Failover to next healthy provider via `job_runner.select_next_provider`.
6. Post-processing background hook `_process_image_background` announces thumbnails done (now carries full job payload with `task_type`, otherwise the frontend realtime handler drops it).

### Flow C: Story action (continue / rewrite / expand / illustrate)

1. Story editor → `useContinueChapter` etc. → `POST /api/v2/stories/{id}/chapters` or `/chapters/{id}/continue` → LLM router + job system (same as chat Act stage).
2. Result written as chapter text; branches and beats tracked; revisions retained with a limit (autosave path previously bypassed the revision repository — fixed).
3. `Story.chat_id` / `Chat.story_id` are nullable provenance columns, one-way each direction; `useExportChatToStory` links a chat to a story.

### Flow D: Provider / model management

1. `Providers.jsx` → `useProvidersPageData` → `GET /api/v2/providers` + health + load-balancer stats.
2. Toggle enabled → `PATCH /api/v2/providers/{id}` → `ProviderService` → `invalidate_engine(provider_id)` (drops cached engine, defers close if a job is streaming, clears load-balancer health cache and object-info cache).
3. Model download → `model_downloader.py` with resume (`Content-Range`, `If-Range`, "server ignored Range" restart path, 29 tests in `test_download_resume.py`).
4. Reconciliation tick (`in_process_reconciliation`, `model_reconciliation`) validates model files, emits `MODEL_SYNC_*` events (4 toasts), marks orphans.

---

## 5. State and data

### Source of truth
- **PostgreSQL 16 + pgvector** is the single source of truth for all World Vault entities: `characters`, `chats`, `messages`, `lorebooks`, `lorebook_entries`, `stories`, `story_chapters`, `story_revisions`, `branches`, `personas`, `worlds`, `locations`, `scenarios`, `voice_models`, `memories`, `jobs`, `providers`, `assets`, `load_balancer_states`, `schema_migrations`. World membership is one indexed `world_id` per member table (migration `090_world_membership_fks`), owned by `services/world_ownership.py`.
- **pgvector** powers semantic search over `LorebookEntry.embedding` (`Vector(384)`) and character memories. Cosine-distance cutoff `ai.ragMaxDistance` (default 0.6) applied to both character-memory and lorebook search. **The embedding stack has no CI coverage** (`sentence-transformers` present, `torchvision` absent, local venv cannot import `transformers`) — unverified whether semantic search works end to end in test.

### Frontend state
- **React Query**: all server data. Query keys follow `buildQueryKey(QUERY_KEYS.*)` in `src/constants/queryKeys`. Chat list key is `chatListKey()` (distinct per workspace/limit/offset/query/character_id to avoid prefix-collision invalidations). Messages keyed per `([messages, chatId, limit, offset, branch, search, tail])`.
- **Zustand**: UI state only — `useStore.js` (activeCollection), `worldVaultStore.js` (activeChatId), `settingsStore.js`, `confirmationStore.js`. Streaming job state was migrated to React Query (`useStreamingJobs.js`).
- **localStorage**: `isSetupComplete` gates the first-run onboarding wizard (unverified whether it also persists other prefs).

### Persistence boundaries
- **config.json** (path via `COMFY_CONFIG_PATH`, default `backend_v2/config.json`): runtime-editable settings. In the container the default resolves to `/app/config.json` (the writable layer) unless `COMFY_CONFIG_PATH` points to `/data/config.json` — production compose sets it there. `_seed_config_file` copies defaults on first boot only. `update_config` / `reset_config` write atomically (mkstemp + fsync + os.replace) under `_config_lock`. Blank string means "unset" only for `generator.default_checkpoint`.
- **Images / assets**: filesystem under `data/output/{user_id}/{workspace}/YYYY/MM/DD/`; `assets` table is the source of truth for gallery — **no filesystem scans at startup**. Thumbnails + blurhash generated by asset reconciler. `.sha256` sidecar is read but never compared to an upstream hash (no integrity verification).
- **Jobs**: `jobs` table grows without bound — `jobs_cleanup` has zero consumers (unverified whether intended).

### What does NOT persist
- Nothing beyond the above is explicitly transient; draft messages live in React Query cache only until sent.

---

## 6. Config and external dependencies

### Environment variables (`COMFY_*` prefix; `.env.example` is the canonical reference)

| Var | Role | Breaks when missing |
|---|---|---|
| `COMFY_DATABASE_URL` (assembled from `POSTGRES_HOST/PORT/USER/PASSWORD/DB`) | DB DSN | Backend won't start; every provider waits on the backend healthcheck |
| `COMFY_CONFIG_PATH` | Where config.json lives | Defaults to `backend_v2/config.json` — in a container that's the writable layer, Settings changes are lost on recreate |
| `COMFY_CORS_ORIGINS` | Socket.IO + CORS origins | Wrong/missing origin → handshake 400 → permanent "Disconnected... reconnecting" toast while HTTP works |
| `COMFY_BACKEND_BIND` / `COMFY_FRONTEND_BIND` | Named bind addresses (never wildcard) | `0.0.0.0` exposes the unauthenticated API to the LAN |
| `COMFY_PROVIDER_TOKEN` / `X-Provider-Token` | Backend↔provider auth (single bearer token) | Empty → auth failed open historically; now fails closed with 503 |
| `HF_TOKEN`, `CIVITAI_TOKEN` | Model download auth | Downloads fail for gated models |
| `MODAL_TOKEN_ID/SECRET`, `BEAM_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_BASE` | Provider credentials | Engine not constructible (`can_create_engine` → False) |
| `PROVIDER_UPLOAD_MAX_BYTES` (0 = disabled) | Upload size cap | `encoded_upload_over_cap` treats 0 as "refuse all uploads" (fixed to `bool(cap) and ...`) |
| `PROVIDER_GET_FILE_MAX_BYTES` | Get-file stream cap | Default 512 MiB |
| `COMFY_ENGINE_CACHE_TTL_SECONDS` | Engine cache TTL | Credential rotation self-heals at worst one TTL late |
| `COMFY_JOB_TIMEOUT`, `jobs.timeout` (3600) | Client-side stream timeout for image jobs | Lowering below the worker's timeout abandons a running workflow |

### External services / providers
- **Modal** (`comfy-modal-stack`, `comfy-modal-tts`, `tnh-llm`): `modal_llm` alias `modal_vllm` runs **llama.cpp**, not vLLM. Modal serialises return values across RPC → 8 MiB range slices, slower than other engines for large checkpoints (unverified fix: presigned URL or volume mount).
- **Beam**: serverless REST + websocket; no modal package.
- **Direct ComfyUI / remote_comfy**: `http://localhost:8188` default; `remote_comfy` defaults agent URL to `http://localhost:8001` with a loud warning.
- **Hosted LLM**: Anthropic, Google, OpenAI-compat (incl. Ollama).
- **Remote agent**: optional self-hosted rig on the machine hosting ComfyUI; `remote_agent/provider_core/` is a deliberate fork of `deployables/provider_worker_core` — **do not unify** (contract test `test_provider_core_parity.py`).

### What breaks when missing
- DB down: backend fails healthcheck, frontend retries forever (5xx), everything stops.
- Provider down / `enabled=false`: load balancer skips it; no failover if only one provider (five of six are disabled by default — a capacity/billing decision, not a bug).
- Modal package absent (`HAS_MODAL` False): Modal engines not constructible.
- `transformers`/`torchvision` absent: embedding paths never executed by any suite (local or CI).

---

## 7. Symptom → suspect table

Ordered by likelihood for each user-visible symptom.

| Symptom | Most likely places to look (in order) |
|---|---|
| "The thing in the sidebar doesn't update" | React Query key prefix collision (`chatListKey` / `useChats` invalidation), `invalidateVaultAggregates`, `useWorldVaultResource`; optimistic writes in `useSendMessage`/`useEditMessage`/`useDeleteMessage`; check `settingsStore` vs `useSettingsStore` (two settings stores — unverified if both still writable) |
| "It feels slow after I import" | `reference_cleanup` scrubs Story+Chat on import; `invalidateVaultAggregates` refetches aggregates; chat list refetch; `useChatJobs` 5s polling while active |
| "That button does nothing" | `extra="forbid"` request model dropping a misspelled field (silent 200 before the fix — now 422); mutation with no `onSuccess` invalidation (e.g. `enableTts` mutation swallows errors); invisible-but-tappable overlay (`useEscapeKey` registry, 16 of 33 overlays still hand-rolled) |
| "Data missing after refresh" | React Query cache cold + failed fetch rendered as empty vault (`QueryState` primitive fixed 7 of 8 pages); `useProvidersPageData` publishing `[]` on error; `assets` table is source of truth (no FS scan) |
| "Stale view" | `useGalleryAutoRefresh` per-second polling on top of live WS; bare `['gallery']` prefix invalidation walking every loaded page; engine cache TTL (1800s) serving stale credentials/object_info; `invalidate_object_info_cache` only called from `invalidate_engine` |
| "Slow" (image generation) | Modal RPC 8 MiB slicing for 7GB checkpoints; provider cold start; `DIRECTOR_TIMEOUT_SECONDS=15` per Director decision; sync routes blocking the event loop (`SYNC_CHAINED` in `test_event_loop_invariant.py`, 29 routes) |
| "Job stuck generating" | Job reaper sweep every 300s (`JOB_REAPER_INTERVAL_SECONDS`); stale window per task-type timeout; `cancel_job` abort not reaching a quiet provider (fixed via abort registry) |
| "500 on import" | Card-supplied `extensions.voice_model_id` written to a FK (fixed: check/drop/report as lost); table-class request bodies (fixed with DTOs) |
| "Empty vault with working Create button" | Failed fetch rendered as empty state (fixed with `QueryState` on 8/8 pages) |
| "Gallery badge says wrong provider count" | Denominator was every online provider incl. LLM/TTS (fixed); badge vs submit-time gate answer different questions (unverified fix) |
| "Reimport creates a duplicate" | Card lacks `data.extensions.tnhcomfy` id; re-import should UPDATE via that id |

---

## 8. Fragile or surprising areas (do not touch blindly)

- **`docs/api.md` drift** — generated; router changes must regenerate or `test_api_docs_contract.py` fails. The check's assertion is `pair & {real_paths, real_ops}` (one match suffices), so stale prose can pass.
- **No authentication** — every destructive endpoint reachable by anyone who can reach the API. `DELETE /api/jobs` deleted 154 rows on 2026-10-01. Assets survived (un-FK'd soft reference).
- **Five of six providers disabled by default** — `enabled=false` is sticky (operator-turned-off); discovery-update branch never re-asserts `enabled`. `preflight.sh` reports the count. Not a security control; a capacity/billing decision.
- **Config.json durability trap** — production compose mounts only `./data:/data`; default `config.json` path is `/app/config.json` (writable layer, lost on recreate). Must set `COMFY_CONFIG_PATH=/data/config.json`.
- **MutableList in-place dict mutation doesn't persist** — reassign the column (AGENTS.md).
- **`update_config` / `reset_config`** — read-modify-write of module global under `_config_lock`; called via `asyncio.to_thread` from two routes. **[FIXED]** (`1f19f049`): `reset_config` restores + re-raises on save failure; lazy `_config` load moved inside the lock. Settings routes additionally hold an asyncio lock across their read-modify-write; `llm_config` `set_default_provider`/`set_active_models` use a threading lock.
- **`_split_unset` previously filtered non-dict sections** — list-valued `system_prompt_library` was a silent no-op (fixed).
- **Event swallowing** — post-turn Director block wrapped in `except Exception → logger.debug` historically hid three defects; now `logger.warning`.
- **`docs/archive/`** — historical, documents contradict each other; not guidance.
- **Half-finished / unverified** — scene graph budget (`scene_spec_cost`) is a ceiling not a price (unverified enforcement); dispatch-time provider prune not implemented (build-time only); no provider-picker UI; `file.path` missing from `/api/files` projection (Provider Status list filters LLM providers out — `ModelDetailsModal.jsx`); `jobs_cleanup` zero consumers; `get_pending_downloads` no per-provider filter.
- **Tight coupling** — `engine_factory` imports `api.routes.nodes` and `services.load_balancer` internals inside functions to avoid cycles; `base.run_inference` finally calls `drain_pending_engine_closes`.
- **Frontend lint** — **[FIXED]** (`5426f17b`): 0 errors / 0 warnings. Removed unused eslint-disable directives and unnecessary `filters` deps.
- **Mobile layout** — one stray `}` previously closed a media query 80 lines early; all 15 `mobileLayoutInvariants` tests passed against it (they regex the stylesheet, never check block membership).
- **Test OOM risk** — full backend suite (~3900 tests, ~6 min) has OOM'd the 18GB host; run targeted files; never vitest concurrent with docker pytest. `test_vram*` needs `/comfyui` on PYTHONPATH.

---

## 9. How to run, build, and test

### Backend
- In container (preferred, right deps + `/comfyui` mount + Postgres):
  `docker exec tnhcomfy-backend python -m pytest -q tests/<file.py>` or `::test_name`
- Host (SQLite by default, different DB than compose):
  `cd backend_v2 && .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8002 --reload`
- Lint (host, from `backend_v2/`): `ruff check .` (F only, F401 on; every `# noqa: F401` needs a reason). Repo root ruff reports ~450 unrelated errors — run from `backend_v2/`.
- Full suite is heavy; run targeted files. Postgres/pgvector tests need `PGVECTOR_TEST_URL`.

### Frontend
- `cd frontend_v2 && bun run lint && bun run test && bun run build` (`bun run verify`, CI order).
- Single file: `bun run test -- src/path/to/file.test.jsx`.
- E2E (Playwright): `bun run test:e2e` — starts its own dev server on 5174; **never run vitest concurrent with backend pytest**.
- Bun only; preinstall guard rejects npm/pnpm/yarn.

### Stack
- New host: `bash scripts/preflight.sh` (creates external `metrics`/`proxy` networks, reports config that silently disables features).
- `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -V -d` (`-V` renews the anonymous frontend `node_modules` volume; lockfile bumps are invisible without it).
- Frontend on port 5174; backend publishes `127.0.0.1:8002` and `${COMFY_BACKEND_BIND:-100.150.0.4}:8002` only. Verify backend from inside container: `docker compose exec backend_v2 curl -s localhost:8002/api/live`.
- Deploy cloud workers (host CLI only): `bash scripts/deploy.sh {image,tts,llm,beam,all} [--dry-run]`. No deploy HTTP route.

### CI workflows
- `backend_v2/**` or `docs/api.md` → `backend-tests.yml` (Python 3.13, ruff, pytest, pgvector service).
- `frontend_v2/**` → `frontend-tests.yml` (lint, vitest, build).
- `frontend_v2/**` or `backend_v2/**` → `frontend-e2e.yml`.
- `remote_agent/**`, `scripts/**`, `docker-compose*.yml` → `provider-tests.yml`.
- Any path → `secret-scan.yml` (gitleaks).

---

## 10. Unverified or unclear

- Whether multi-worker uvicorn is actually supported (docstring in `main.py` says yes with advisory locks; `architecture.md` says single worker only).
- Whether semantic memory search works end to end (no CI coverage for `transformers`/`torchvision`).
- Whether `useSettingsStore` and `useUpdateSettings` are both writable paths or one is legacy.
- Whether `jobs_cleanup` having zero consumers is intentional policy.
- Whether the badge vs submit-time gate model-availability disagreement is fixed (one function for both was proposed, not confirmed done).
- Whether `file.path` absence from `/api/files` projection is fixed.
- Whether scene-graph budget is enforced at dispatch time (proposed, not confirmed).
- Whether the gallery "drops a completed job" bug (`dashboardItems.js` not pushing completed-but-unindexed jobs) is fixed.
- Whether `useEscapeKey` focus trap in `ModalOverlay` is safe to touch (a previous attempt broke 8 tests and was reverted).
- Whether all 9 mobile Playwright tests run in any CI workflow (previously ran in none).