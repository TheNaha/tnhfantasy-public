# TNHFantasy — Refine, Unify, Polish (Phased Plan)

## Context

TNHFantasy evolved from a ComfyUI image wrapper into an "AI Fantasy Engine" (Image + Roleplay + Story) over a single-user, filesystem + PostgreSQL (`pgvector`) stack. The vision (`VISION.md`) calls for a *Universal Adapter* worker pattern and *unified* TaskEvent protocol, but the current code does **not** match the vision: there are two incompatible worker stream dialects, a dead parallel provider abstraction, no asset index table, roleplay agentic mode is 100% broken, and there is meaningful repo rot.

This plan is **phased** so the site stays reachable after every phase. **Scope (per user):** refine existing systems, fix bugs, dedupe, improve performance, finish the vision's core pillars, and defer Audio/TTS and multi-tenancy auth. Decisions below were confirmed with the user via interview.

The user runs the stack with:
```
docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d
```
Frontend on `:5174`, backend on `:8002`, db `tnhfantasy-db`. All migrations run automatically at backend startup (`infrastructure/migrations/steps.py`).

---

## Phase 0 — Stabilize (make the site work, clean the build)

Goal: fix the breakages that are currently live + remove build-rot that inflates every rebuild. Site must be fully usable after this phase.

### P0 bugs (live right now)
1. **Agentic chat crash (HTTP 500 on every message).** `backend_v2/api/routes/world_vault/chats.py:386` and `:685` do `set(AGENTIC_TOOLS)` where `AGENTIC_TOOLS` is a list of dicts → `TypeError: unhashable type: 'dict'`. Fix: replace `set(AGENTIC_TOOLS)` + comprehension with a pure-list filter:
   ```python
   allowed_tools = [t for t in AGENTIC_TOOLS
                    if chat.allow_image_generation or t["function"]["name"] != "generate_image"
                    if chat.allow_narration or t["function"]["name"] != "narrate_scene"]
   ```
   Extract a single helper `filter_agentic_tools(tools, allow_image, allow_narration)` in `services/orchestrator_service.py` and call it from both `add_message` and `regenerate_reply`. (Note: the bug was introduced by commit `c6b80d0`, 2h before planning; `ChatWorkspace.jsx:908` defaults `agenticMode=true`, so chat is fully broken.)

2. **`narrate=True` is a silent no-op.** In `chats.py` `add_message`, the narrator branch (`:350-371`) builds `workflow`/`metadata` but the `create_job`+`enqueue` (`:399-406`) live only in the `else:` block (`:372`). Move the job creation/enqueue out of `else` so both paths queue. Verify returned `job_id` is non-null.

3. **Story jobs carry `chat_id:null` / wrong metadata.** `services/llm_workflow.py:37-42` never copies `story_id`/`chapter_id` into `metadata`. Add them (the failing test `tests/test_llm_workflow.py::test_build_llm_workflow_story_continue` asserts `metadata["story_id"]`). This is the one currently-failing backend test (1257 pass / 1 fail).

4. **Fake "LLM job failed" after ~30s.** `frontend_v2/src/hooks/useLLMJobResult.js` `defaultMaxPolls=30` × 1000ms rejects on first poll-miss even when WS will deliver. Make WS-primary and only reject after a real timeout (e.g. 300s) — increase `defaultMaxPolls` and, better, stop polling entirely once `getConnectionStatus()` is true (the WS path already resolves). Also surface `JOB_PROGRESS`/`JOB_COMPLETED` reliably.

### P0 hygiene (deletions — authorized by user)
5. **`backend_v2/test_env/` (219MB stray virtualenv)** is not in `.gitignore` *or* `.dockerignore` → shipped into every backend build context. Delete it, and add `test_env/`, `scripts/`, `data/` to `backend_v2/.dockerignore` (not `.gitignore` for `data/` — already root-ignored). `backend_v2/.dockerignore` currently ships `tests/` and `*.md` but NOT `test_env`.
6. **One-off throwaway scripts** in `backend_v2/scripts/`: delete `patch_*.py`, `test_script.py`, `test_script2.py`, `test_docker.py`, `refactor_di.py`, `find_unreachable.py`. **Keep** the real tools: `migrate_*.py`, `backfill_download_urls.py`, `clean_preview_cache.py`, `benchmark_statistics.py`. (Remove also `services/__pycache__/scripts/migrate_v1_to_v2.py` if it reappears.)
7. **`.agents/` (1.4MB agent chatter tracked despite `.gitignore`)**: `git rm -r --cached .agents/` then leave it ignored. Also delete root `check_sqlite.py`, `.jules/`, `.Jules/`.
8. **`.env` footgun**: remove the `COMFY_DATABASE_URL=sqlite:///./data/db/comfy.db` line (compose already overrides with Postgres; dangerous if run outside Docker). Also drop the misleading comment block. **This file contains secrets (.env) — edits must be made by/with the user, or a gitignored copy regenerated.** Flag as a manual step if the implementation agent cannot touch `.env`.
9. **Stale `provider_containers/README.md`** references deleted `modal_worker`/`beam_worker` dirs → rewrite to describe `image_worker`/`llm_worker` + engines.

### P0 validation
- `docker compose ... up --build -V -d`
- Backend: `python -m pytest -q` → 0 failures (currently 1).
- Frontend: `npx vitest run` → 0 failures (currently 311/311), `npm run lint` clean.
- Manual: open `:5174`, send a roleplay message (agentic default on) → reply streams; toggle Narrate → narrator message appears; toggle a story continue → chapter grows.
- Confirm build context shrank (no `test_env` in `docker build` context).

---

## Phase 1 — Unify (one worker protocol + roleplay correctness)

Goal: replace the two-dialect worker stream with a single `TaskEvent` schema, delete the dead provider abstraction, and make the roleplay/story pillars correct and traceable.

### 1A. Unified TaskEvent protocol (clean cut, no back-compat shim)
- Define `TaskEvent` in `provider_containers/provider_core/models.py`:
  ```python
  class TaskEvent(BaseModel):
      event: Literal["started","progress","delta","artifact","completed","failed","cancelled"]
      job_id: str
      seq: int
      node: str | None = None          # image: executing node
      value: float | None = None        # progress fraction 0..1
      text: str | None = None           # llm: token delta
      tool_calls: list | None = None    # llm: accumulated tool calls (on completed)
      artifacts: list | None = None     # image: [{relative_path, ...}]
      status: str | None = None
      message: str | None = None
  ```
- **Split InferenceRequest** into a typed payload: image job → `{workflow: <comfy graph>, filename_prefix, ...}`; llm job → `{messages, tools?, model, ...}`. Stop smuggling `messages` inside `workflow`. `provider_core` `InferenceRequest` is currently ComfyUI-shaped (`models.py:11`) and the LLM worker stuffs `messages` into `request.workflow`.
- All workers emit `TaskEvent` NDJSON: `image_worker/*/client.py` (status/progress/executing/success/error → TaskEvent) and `llm_worker/*/client.py` (type=progress/completed/error + tool_calls → TaskEvent). The `image_worker/engines/modal/client.py:88-112` remotes are *proxied locally*, so changing the emitted format only requires rebuilding the **local** worker containers — **no `modal deploy` needed** (confirmed with user).
- Backend: one `stream_task_events(worker_url, payload, job_id, ...)` reader in `services/provider_client.py` replacing `call_image_provider` (`provider_client.py:210`) and `call_llm_provider` (`provider_client.py:91`) — both currently re-implement NDJSON line parsing and expect different fields (`status` vs `type`, `images` vs `outputs`). Thin per-task reducers on top: image → node/progress + final `artifacts`; llm → token `delta` stream + `tool_calls` capture.
- Keep `infrastructure/providers/ndjson.py` only as a low-level line splitter if needed; otherwise delete (it's currently unused dead code).

### 1B. Delete dead provider abstraction (authorized)
- `ServerlessProvider.run_inference` (`infrastructure/providers/modal_provider.py:121`, `beam_provider.py`, `direct_url_config.py`) is **never called** — all inference routes through `job_runner.py:319/329` → `provider_client.py`. Delete `modal_provider.py`, `beam_provider.py`, `direct_url_config.py` (plus `ndjson.py`), and remove `run_inference` from `*_config` classes.
- Collapse `infrastructure/providers/{modal,beam,direct_url,openai_compat,modal_llm}_config.py` into **one** declarative `provider_types.py` descriptor: `{engine, required_env, deploy_hook, worker_type}`. Keep `ProviderRegistry` for env-building/deploy metadata only.
- Delete the **orphaned `runpod` engine** (`image_worker/engines/runpod/client.py`, `166` lines) — worker code exists but has zero backend registration (`provider_registry.py:72` only a docstring reference) and no compose service.

### 1C. Roleplay / story correctness (authorized: fix + transcript now, branching later)
- **Message `kind` column**: add `kind` to `Message` (`core/entities.py:750`) — values `user | char | narrator | system | image | tool`. Currently narrator + agentic image messages are stored as `role=SYSTEM` (`world_integration_service.py:286,213`), which `context_builder.py:143-151` excludes from pruning → they silently eat the context window. Map: narrator→`kind='narrator'`, agentic image→`kind='image'`, keep `role='system'` for true system. Render each `kind` distinctly in `ChatWorkspace.jsx`.
- **Persist tool_calls**: when `completed` carries `tool_calls`, create a `kind='tool'` Message (so agentic activity has a transcript and an inline chip in the UI). `Message` schema needs a `tool_calls` JSONB column.
- **Workspace tagging on ALL image jobs**: set `metadata["workspace"]` for agentic image (`orchestrator_service.py:463`), chat image (`_tool_generate_image` metadata), story illustration (`stories.py:249`), and scene/image chains. Today only LLM jobs set `workspace` (`chats.py:785/914/993`, `orchestrator_service.py:598`), so roleplay/story images leak into the main gallery — VISION #13 violation. Use the new assets table (Phase 2) to enforce scoping server-side.
- **Narrator pruning**: exclude only true `system` from pruning; cap narrator share of budget in `prune_context` (`context_builder.py:142`).
- **Lorebook keyword fallback** (`context_builder.py:381`): `keyword_only[:_TOP_K]` drops entries past 5 — scan all `keyword_only`, not just first 5.
- Remove dead imports `core.events.wait_for_job_completion` in `chats.py:9` and `stories.py:9`.

### 1D. VISION.md reconciliation (authorized)
- Amend #5 → describe the real `TaskEvent` schema. Amend #7 → backend owns context assembly (frontend sends text + flags; pgvector retrieval is server-side). Amend #8 → assets table + `/{user_id}/` (Phase 2). Mark Audio/TTS and multi-tenancy (#9) as **explicitly deferred**. Append an "Implemented vs Planned" status table.
- Also update `non_AGENTS.md` (keep its filename) stale content: it still says SQLite and `docker compose up -d`.

### 1 validation
- `python -m pytest -q` + `npx vitest run` green.
- Send an agentic roleplay message that triggers `generate_image`; confirm: image job created with `workspace='roleplay'`, a `kind='image'` message appears inline, and the final chat reply arrives (no 500). Confirm a Narrate message appears and is pruned correctly when context is long.
- Build + run a worker container; watch its NDJSON stream is `TaskEvent`-shaped; backend reads it via the single reader.

---

## Phase 2 — Asset layer + frontend consolidation + perf

Goal: kill the 15s startup scan, enable workspace/scoped galleries, dedupe the frontend, fix perf.

### 2A. DB-backed asset index + `/{user_id}/` (authorized)
- Add `assets` table (`core/entities.py` + migration): `id, user_id (default 'default_user'), filename, relative_path, kind (image/text/audio/video), created_at, job_id, workspace, character_id, story_id, width, height, blurhash, metadata JSONB`. GIN index on metadata, keyset index on `(user_id, created_at DESC)`, partial indexes for workspace/character/story.
- **Path abstraction**: `storage_root(user_id='default_user')` in `config.py` → `OUTPUT_DIR/{user_id}/...`. Update `image_processor.get_output_path` (`infrastructure/image_processor.py:17-41`) and `image_service` to inject `/{user_id}/`. Move existing `data/output/YYYY/MM/...` → `data/output/default_user/YYYY/MM/...` (same-device rename, instant — 13.7k files).
- **Indexer**: replace the pure in-memory `gallery_indexer` (`services/gallery_indexer.py`'s `_perform_initial_scan` is 15.24s/13704 files, full `sorted()` re-sort on every image) with a reconciler that upserts rows into `assets` and a watchdog that upserts/soft-deletes. Gallery reads become SQL with keyset pagination + workspace/character/story filters.
- **Serving** (`api/routes/files.py`): scope by `user_id` (default `default_user`); add soft-delete + tombstone handling so re-scans don't resurrect deleted files (`DeletedFileTombstone` exists but is only used for model files).

### 2B. Frontend consolidation (authorized: targeted)
- **One `useJobStatus(jobId)`** hook (WS-primary, polling fallback only when WS down) replacing `useTrackJob`, `useTrackGenerationJob`, and the 30-poll timeout in `useLLMJobResult`. Keep `useActiveJobs` for the list, `useJobsRealtime` for invalidation, `useStreamingJobs` for token text.
- **One `assetUrl(filename, {thumb})` / `thumbUrl()` helper** replacing the 5+ copies (`SceneGallery.jsx:5-15`, `ChatWorkspace.jsx:509/540`, `GroupedDashboardContent.jsx`, `StorySandbox.jsx:943`, `useSelectedImageState.js:11`).
- **Virtualize `SceneGallery`** (`components/SceneGallery.jsx`, 101 lines, plain mapped grid shared by Chat/Characters/Story) — window the grid.
- **Keyset gallery pagination** against the `assets` table (replaces OFFSET in `useGallery.js`).
- **Shared `<GeneratorShell>`**: `SimpleGenerator`, `Img2ImgGenerator` (~459/459 lines), `InpaintGenerator` (575) currently duplicate the whole settings/sections stack. Extract a shell; keep only the source-image/mask differ.
- **Nav coherence**: surface Img2Img/Inpaint in the sidebar (`Layout.jsx:190-205`) and add Advanced to `GeneratorTabs`.
- Route the 3 direct `navigator.clipboard.writeText` calls (`FeedCard`, `PromptCard`, `ModelDetailsModal`) through `utils/clipboard.js`.

### 2 validation
- Restart backend: startup no longer blocks 15s on scan (or scan is backgrounded + asset table populated). `data/output/default_user/...` exists.
- Gallery + SceneGallery scroll smoothly at 20k files; workspace filter shows only that workspace's images; character-scoped gallery works.
- Image generation from any workspace lands in the correct gallery (no cross-leak).
- `npm run lint` + `vitest run` green.

---

## Phase 3 — Vision gaps (lowest risk, last)

- **Story branching**: add `parent_beat_id` to `StoryChapter.beats`/messages; `add_beat` supports forking; UI "retry from here" in `StorySandbox.jsx`. (Authorized: Phase 3, not earlier.)
- **Chat "Illustrate" button** in `ChatWorkspace.jsx` (matching `StorySandbox`'s `useIllustrateChapter`), with the character's `checkpoint`/`lora` injected (already wired in `_tool_generate_image`, `orchestrator_service.py:390-480`).
- **Cross-workspace asset moves** via collections `workspace` column (migration 028 exists; verify end-to-end DB→API→frontend).
- Confirm agentic tool-calling transcript renders as inline chips; add `update_world_state` tool UI if desired.

### 3 validation
- Branch a story at a beat, diverge, return — both branches persist.
- Click "Illustrate" in chat → image job → appears in roleplay gallery tagged to the character.

---

## Cross-cutting risks / notes
- **Multi-process**: `core/events.py` `EventBus` is in-memory; `LoadBalancer` TTL caches and `pending_job_futures`/`connected_clients` are module globals (`provider_client.py`, `load_balancer.py`). Fine for single backend container (current deploy). Document as a known limit; do **not** introduce `uvicorn --workers N` without moving to Redis pub/sub.
- **Token counting** is a heuristic (`estimate_tokens`, `context_builder.py:21`, CHARS_PER_TOKEN=3.5). Acceptable for single user; note in VISION status.
- **`.env` edits** (step 0.8) involve secrets — leave to user if agent can't safely touch. Everything else is rebuildable via the compose command.
- **Provider alive-check**: VISION #4 — backend only health-checks the local worker, not the remote engine. Keep as-is (already the design); add a manual "Test Connection" button if missing.

## Manual intervention required from user
- `.env` line removal (step 0.8) — secrets file; implementation agent should flag, not auto-edit, or do it with the user present.
- `git rm -r --cached .agents` (step 0.7) is safe but is a repo-state change; confirm before push.

## Suggested order for implementation agent
Phase 0 → verify site → Phase 1 (1A protocol, 1B dead code, 1C roleplay, 1D docs) → verify → Phase 2 (2A asset, 2B frontend) → verify → Phase 3. After each phase: `docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -V -d`, run both test suites, and confirm `:5174` loads.
