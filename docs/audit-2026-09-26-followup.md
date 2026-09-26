# Codebase audit — second pass (2026-09-26)

Follow-up to [`audit-2026-09-26.md`](audit-2026-09-26.md), run after that audit's
24-commit hardening wave had landed. Same day, different job: that pass fixed what
it found, this one re-read the *current* state looking for what it missed, for what
its own fixes broke, and for anything it never looked at.

**Method.** Three read-only sweeps over `backend_v2/`, `frontend_v2/src/` and
`provider_containers/` + `remote_agent/` + compose/CI/scripts, each instructed to
read the previous audit first so as not to repeat it and to re-verify that wave's
fixes. Every reported finding was required to come with a `file:line` and a
concrete failure. Fixes were applied in waves, each gated on the full test suite
for that pillar plus a live reachability check.

**Outcome.** 31 defects fixed across the three pillars, 1 architectural
rework of the statistics pipeline, and 1 test-infrastructure fix that had been
silently letting the backend suite touch the developer's real database.

| | before | after |
|---|---|---|
| backend tests | 1931 passed | 1924 passed (+1 file rewritten) |
| frontend tests | 764 passed | 766 passed |
| provider tests | 105 passed | 116 passed |
| `GET /api/statistics/detailed` (cache-cold) | 6.52 s | 2.0–3.0 s |
| `GET /api/statistics` (cache-cold) | ~3.1 s | 1.3 s |
| ↳ of which SQL | 6.3 s | 1.96 s |
| either endpoint (cache-warm) | 0.04 s | 0.006–0.02 s |
| `ruff check` (backend) | F401 globally disabled | clean, F401 on |
| `npm run lint` | 1 pre-existing warning | 1 pre-existing warning |

All three suites green, `docker compose ps` unchanged, and every API surface the
UI uses still answers `200`.

---

## 1. Fixed

### 1.1 P0 — the `.lock` file destroyed model metadata (providers)

`exclusive_path_lock` (added one commit earlier, `67f2089`) creates
`<model>.lock` and never unlinks it. No listing function filtered it and no
validation function skipped it, while `run_reconciliation_v2` calls
`validate_existing(True)` — `delete_invalid` is unconditionally `True`.

A 0-byte lock fails `MIN_MODEL_SIZE`, so validation treated it as a corrupt
model and did `os.remove(full_path)`, then removed:

```python
os.path.splitext(full_path)[0] + ".json"          # → "x.safetensors.json"
os.path.splitext(full_path)[0] + ".preview.png"   # → "x.safetensors.preview.png"
```

`os.path.splitext("x.safetensors.lock")[0]` is `"x.safetensors"`, so **every model
that had ever been downloaded lost its CivitAI/HF metadata and its preview within
two hours**, silently, in all three engines (`modal_app`, `beam_app`,
`remote_agent`).

Two further consequences: the lock was also *listed* as a model, so it became a
permanent junk `ModelFile` row via `register-discovered`; and because validation
unlinked the lock inode while a downloader held an `flock` on it, a second
downloader would `O_CREAT` a new inode and take a *different* lock — restoring
exactly the interleaving corruption the lock was written to prevent. The same
pass deleted in-flight `<path>.<pid>.<hex>.downloading` files, leaving the writer
with a live descriptor whose `os.replace` then failed and was reported as a
failed download.

Fix: one shared predicate instead of a sixth per-engine exclusion list —
`provider_core/utils.py` now owns `is_transient_artifact` / `is_sidecar_artifact`
/ `is_model_file`, and every listing and validation site branches on it. The
destructive `os.remove` of a transient file is gone; a partial is still
*reported*, just never deleted underneath a live writer.
`provider_containers/tests/test_download_artifacts.py` (11 tests) pins the
predicate, and one of them asserts the `splitext` mechanism so the guard cannot be
removed as "unnecessary".

### 1.2 P0 — one failed websocket connect poisoned the session (frontend)

`api/websocket.js:connect()` had two branches. The `socket && !isConnected` branch
built the shared `connectionPromise` and rejected it after 30 s **without ever
clearing it**. The only other resets were `disconnect` and a `connect_error` guard
that was dead, because it closes over the *first* `connect()`'s `settled`, already
`true` once the initial connect resolved.

Reachable sequence: backend down for 45 s → socket drops (`disconnect` nulls the
promise) → any `useWebSocket()` mount takes the reconnect branch → 30 s later it
rejects and stays assigned → socket.io reconnects, `isConnected` goes `true`, the
UI shows "connected" — and from then on **every** `connect()` returns that same
rejection. `cancelJob()` rejected for every job (Dashboard reported "Failed to
cancel job" while the job kept running) and `subscribe()` threw, so new room
subscriptions incremented their refcount but never emitted. Only a page reload
recovered.

Fix: both branches now go through one wrapper that clears `connectionPromise` on
rejection, guarded by an identity check so an older rejection cannot clear a newer
attempt.

### 1.3 P0 — chapter auto-save silently undid server-side prose rewrites (frontend)

`StorySandbox`'s debounced auto-save depended on `activeChapter?.content`, and its
only guard was "contents match **and** buffer is clean". When they *differed* it
saved regardless. Reordering beats PUTs the new order and the backend rewrites the
chapter prose from the beats; the editor buffer was never updated, so the refetch
tripped the effect and, 2 s later, PUT the pre-reorder prose back over the
rewrite. No user action, no error.

Fix is two-sided, because both halves were wrong:

- Auto-save fires only when `isDirtyRef.current` is true. That ref is set by
  `onEditorChange` alone, so it distinguishes "the user typed" from "the server
  changed the chapter" exactly. `activeChapter?.content` is no longer a dependency.
- A clean editor now *adopts* server content, so after a beat reorder the open
  editor matches what was persisted. Previously only a chapter *switch* seeded the
  editor, so the display diverged too.

### 1.4 Statistics rebuilt as SQL aggregation

The single worst-performing endpoint. `GET /api/statistics/detailed` took **6.52 s
cold** behind a 5-minute cache. It loaded all 16,058 non-deleted assets — 70.5 MB
of `metadata_` jsonb — into Python, `os.stat`'d every file twice, and aggregated
there. Profiling the old `_calculate_detailed_statistics` attributed **2.47 s to
the load** (json decode + ORM instantiation) against **~0.2 s of aggregation**;
nothing else was worth optimising.

Three findings came out of the profiling:

1. `metadata_->>'key'` cannot tell an absent key from a JSON `null`, and
   `CAST(jsonb_text AS NUMERIC)` **raises** in Postgres on a non-numeric value —
   one junk row would have taken down the whole endpoint. Fixed by promoting
   `duration_seconds` to a real column (migration 066) and backfilling behind a
   `~ '^[0-9]+(\.[0-9]+)?$'` guard.
2. Narrowing the select did **not** help (2.28 s): Postgres must still decompress
   and scan the whole document to extract any key. Only in-database aggregation
   avoids the transfer, and only columns avoid the decompression. A multi-column
   expression index was tried and rejected — the planner will not use an index-only
   scan for an aggregate that touches 100 % of rows.
3. `GROUPING SETS` (1.19 s for 7 groupings) measured **identical** to 7 portable
   `GROUP BY` queries (7 × 0.17 s), so the portable form was chosen: every
   expression is built from SQLAlchemy constructs that compile to `->>` on Postgres
   and `JSON_EXTRACT` on SQLite, with no dialect branching, which is what lets the
   test suite exercise the same SQL as production.

Result: `services/statistics_service.py` (new), `api/routes/statistics.py` reduced
from 626 lines of route+logic to 46. The ten groupings are `GROUP BY`s over
rollup columns; a single narrow pass still fetches the LoRA array, prompt text and
resolved timestamps, the only things SQL cannot group. The individual groupings
dropped from **0.25–0.46 s to 0.035–0.045 s** each, and the whole SQL portion of
a detailed request is now 1.96 s of the ~2.0–3.0 s total.

**What is left, honestly.** The residual is not the aggregation, it is the prompt
text: keyword extraction has to see all 16,052 prompts (9.1 MB) and match
1,152,603 word occurrences, which costs ~0.8 s of unavoidable Python plus the
transfer. Three further optimisations were implemented and measured as *not*
worth it, so none were kept:

| attempt | result |
|---|---|
| folding the stop-word list into the regex as a 38-way negative lookahead | **1.4 s vs 0.97 s** — slower, and it also rejected any word that merely *starts* with a stop word ("android") |
| `filter(_STOP_WORDS.__contains__, findall(...))` | 0.62 s but produces the inverse set — wrong |
| a list comprehension feeding `Counter.update` | 0.90 s vs 0.78 s for the generator form |
| a multi-column expression index so the `GROUP BY`s could be index-only scans | the planner will not use one for an aggregate touching 100 % of rows — verified with `EXPLAIN ANALYZE` under `enable_seqscan=off` |

So a further ~2x is available only by changing what the endpoint returns (sampling
prompts, or caching the keyword histogram and updating it incrementally), which is
a product decision rather than a refactor.

The rollup columns (`checkpoint_name`, `sampler`, `scheduler`, `vae`, `steps`,
`cfg`, `seed`, `metadata_version`) are migration 067, derived in exactly one
function — `services/asset_reconciler.derive_stat_columns`, called from
`upsert_asset` — and a test asserts they always agree with the document they
summarise. `api/routes/files.py`'s copy branch constructed `Asset` directly and is
now routed through `upsert_asset`, so there is one write path.

**Payload parity:** `/api/statistics` came back **bit-identical across all 669
leaves**. `/api/statistics/detailed` differs on 36 of 898 leaves, every one an
improvement:

| change | before | after | why |
|---|---|---|---|
| `correlations.model_resolution` | `[]` | 42 rows | declared in the init dict, never populated — dead feature, now implemented |
| `models.checkpoints` | missed 105 rows | counted | the old detailed loop only accepted a dict checkpoint, silently dropping the legacy bare-string form that the *base* endpoint counted — a base/detailed divergence |
| `models.loras[""]` | `""` | `"Unknown"` | same divergence: detailed used `.get("name", "Unknown")`, base used `\| "filename" \| "Unknown"` |
| `performance.success_rate` | **absent** | `0.9902` | `Statistics.jsx` has read this key since it was written; nothing ever produced it, so the card rendered nothing |
| `settings.resolutions["1024x1277"]` | 15,206 rows | `["1024x1272"]` | verified against the file on disk: the PNG is **1024×1272**. The old value was the requested latent size, which ComfyUI rounds down to a multiple of 8 — so 95 % of images were reported at a resolution that does not exist |
| `prompts.lengths` | 16,052-element array | removed | unconsumed; `avg`/`min`/`max` carry the same information. Was most of the 130 KB response |
| `settings.cfg` | `"7"` and `"7.0"` split | one `"7.0"` series | a real `float` column unifies 7 and 7.0; detailed already did this, base did not |

One deliberate, documented difference: `pillars.images` is now the in-range count
rather than the all-time count for a filtered view, consistent with every other
section of the same response.

### 1.5 The backend suite was touching the real database

`tests/conftest.py` redirected `get_session_sync()` only inside `client_fixture`.
Any test exercising a service that opens its own session *without* requesting
`client` — statistics, reconciliation, the load balancer, file cleanup — ran
against the developer's real `data/comfy.db`, saw production rows, and would have
**written** to them had the service written at all. Worse, modules doing
`from api.deps import get_session_sync` bind the function into their own namespace
at import time, so rebinding the attribute on `api.deps` afterwards never reached
them: `api/routes/files.py`'s `_sync_session()` was using the on-disk database.
Surfaced only because the new asset columns are not in that stale file's schema.

Fix: an autouse fixture rebinds the name in **every already-imported module** that
holds it, not just the two that define it.

### 1.6 Backend correctness and performance

| fix | file | failure |
|---|---|---|
| `load_balancer` deref when `None` | `services/job_processing.py:537` | the only production caller passes `None`; an external-worker LLM job returning `tool_calls` raised `AttributeError`, and the hardening commit's new `except` then marked an **already-paid-for, completed** job `FAILED` |
| `.first()` with no `.limit(1)` | `world_vault/chats.py` | `Result.first()` applies no LIMIT and psycopg2 buffers everything, so every `POST /chats/{id}/illustrate` without a prompt transferred and instantiated **every message in the chat**, `content` TEXT included, to use one |
| same | `world_vault/stories.py:1306` | same pattern, smaller table |
| `max_concurrent` not enforced | `services/job_queue.py` | the claim set `claimed_at` but not `status`, and `PENDING` was not in the in-flight list, so N workers polling in one tick all computed `in_flight = 0` and all claimed. Effective bound was `max_concurrent + max_workers` — with `max_concurrent=1` and 3 providers, **3 jobs reached paid providers**. Fixed by counting claimed-but-pending rows and serialising count-against-claim with a transaction-scoped `pg_advisory_xact_lock` |
| `fk_jobs_provider` poisons provider delete | `services/provider_service.py` | migration 063 installs a `NO ACTION` FK, `delete_provider` never touched `jobs.provider_id`, so deleting any provider that had run a job raised `ForeignKeyViolationError` → 500. Now the reference is cleared and the job history kept |
| `DEFAULT_CHECKPOINT` in two places | `config.py`, `core/workflow_builder.py` | config cannot import from `core` (infrastructure imports config), so the constant now lives in `config` and `workflow_builder` re-exports it |
| container-name prefix re-spelled | `infrastructure/providers/runtime.py:14` | the file declares `PROVIDER_CONTAINER_PREFIX` and the comment says "do not re-spell the literal" — then does, two functions below |
| dead `if job is None` | `services/job_runner.py` | `get_job` raises `NotFoundError`; the branch was unreachable and the re-read it guarded cost a `SELECT` per job |
| stale import | `services/job_submission_service.py` | `DEFAULT_CHECKPOINT` imported after its only consumer was deleted |
| `ruff.toml` disabled F401 **globally** | `ruff.toml` | `AGENTS.md` states ruff "catches real bugs like … unused imports (F401)" — the config did the opposite, so the stale import above was invisible. F401 is on now; genuine re-exports are marked individually, and `job_runner.ProviderService` is a `monkeypatch.setattr` target whose removal broke 8 tests, which is precisely why blanket-ignoring was the wrong fix |
| 14 unused imports removed | across 6 files | — |

### 1.7 Frontend

| fix | file | failure |
|---|---|---|
| blob URL leak | `generator/ImageUploader.jsx` | the previous fix compared `previous !== url`, and on every transition both sides were equal, so it revoked nothing — each replaced image leaked for the page's lifetime. `Characters.jsx:96` does it correctly and is the model |
| blob URL leak | `pages/Characters.jsx` | `setPreview(null)` set `previewUrlRef.current = null` **without revoking**, so the unmount cleanup saw `null`. Guaranteed on every save that had a preview |
| dead optimistic update | `hooks/useChats.js` | `CHAT_LIST_KEY` was the 2-element prefix, but the list is stored under the 5-element `buildQueryKey(...)`, so `getQueryData` was always `undefined`: the optimistic rename never appeared and the `onError` rollback was dead code. Now `get/setQueriesData` — with an `Array.isArray` guard, since the *detail* query also lives under that prefix and calling `.map` on it threw |
| context memo defeated | `contexts/ChatWorkspaceContext.jsx` | `useMutation()` returns `{...result, …}` — a fresh object every render — and 20 of them were the dependency list of the context `useMemo`. It recomputed every render, republishing the context, so every consumer re-rendered including `MessageItem` on **every streamed token**. Fixed with `useStableObject`, keyed on all 16 mutable observer fields |
| invisible lightbox | `DashboardOverlays.jsx`, `ImageLightbox.jsx` | `findIndex(...) \|\| 0` — `-1` is truthy, so `\|\| 0` did not fire. `images[-1]` is `undefined`, the lightbox rendered `null` while `useSelectedImageState` still held `document.body.style.overflow = 'hidden'`: an unscrollable page with no lightbox on it |
| dead button | `pages/StorySandbox.jsx` | the only `ParseStoryModal` was inside the `!activeStoryId` branch, but a story is auto-selected as soon as one exists, so "Import & Parse Story" always set `showParseModal` with nothing mounted to react. Moved out of the ternary |
| Escape closed two dialogs at once | `hooks/useEscapeKey.js` | every handler is a listener on the same target, and `stopPropagation()` only stops propagation to *other targets*, not other listeners on this one — so one Escape resolved a `ConfirmationModal` **and** closed the dialog behind it, discarding the form. Added a topmost-registration rule |
| 4 unconditional Escape listeners | 4 story dialogs | `useEscapeKey(onClose, true)` on components mounted unconditionally with an `open` prop: a *hidden* dialog could still react. Now `!!open`, matching `LorebookModal`/`ExportModal` |

### 1.8 Infra

| fix | file | failure |
|---|---|---|
| preflight passed on a clean checkout | `scripts/preflight.sh` | missing provider env files were a `note`, so `warn` stayed 0 and the script printed "Preflight passed" and exited 0 — on exactly the state it exists to catch, where `docker compose up` then aborts with `env file .env.modal-zetsuke not found` for *every* service. Now a hard failure, and the list is derived from compose's own `env_file:` entries (it was also missing `.env.remote-comfy`) |
| invisible provider | `docker-compose.yml` | the `direct-url` service was the only one with no `PROVIDER_ID`/`PORT`/`BACKEND_URL`, so the worker fell back to `direct_url-worker` + `localhost:8000` and posted discovery to its own loopback every 60 s forever, while the backend built `http://tnhcomfy-direct_url-worker:8000` — a name that does not exist. The healthcheck passed anyway, so `docker compose ps` reported it healthy |
| red CI on every provider commit | `.github/workflows/build-agent-binaries.yml` | the verification step ran the binary with no environment, and `remote_agent/server.py` raises at **import time** without `REMOTE_AGENT_TOKEN`. The process exited before the healthcheck. Both matrix legs failed on every push touching `remote_agent/**` or `provider_core/**` — including the two most recent commits |
| quick-start always failed | `remote_agent/agentctl.sh` | PyInstaller writes to `./dist`, but the script looked for the binary one directory above. `README.md:23` and the CI both use `--distpath ./dist` |
| partial downloads never deleted | `modal_app`, `beam_app`, `remote_agent` | `_unique_temp_path` renamed the temp file to `<path>.<pid>.<hex>.downloading`, but all three delete paths still probed the old fixed `.downloading` name, so a crashed download left a multi-GB partial on the volume forever. New `pending_download_paths()` globs it |

---

## 2. Found, not fixed

Ordered by value. All were read and verified by the sweeps; none are speculative.

### Backend

1. **`resolve_provider_runtime()` does blocking Docker-SDK I/O on the event loop**
   (`services/provider_runtime.py:42`) — `containers.get()` + `reload()`, no
   timeout, no `to_thread`. `GET /api/v2/providers/` loops it *serially per
   provider* (`provider_status_service.py:454`), so a slow or dead `DOCKER_HOST`
   blocks the entire event loop for the sum of all connect timeouts. Called from
   8 route modules. The previous audit limited this class to four handlers in
   `files.py`; it is systemic.
2. **`move_asset` was never actually moved off the event loop** — `commit(6a4e4d7)`
   converted three of four handlers in `files.py` and its message claims four.
   `move_asset` still runs `session.get`/`commit` inline and does
   `dst.write(src.read())`, buffering a whole asset in RAM on the loop, and opens a
   second uncommitted `Session` from `_soft_delete_assets`. `copy_file` is
   client-controlled and the app has no auth.
3. **`branches.py` and `GET /memories` load unbounded** — the branches list
   returns every message with full `content` and the `alternates` array; memories
   has no `LIMIT`. `create_branch` then inserts one row per message in a single
   transaction.
4. **`external_worker` mode is dead by construction** — `worker_ws.py` requires
   `provider.config["worker_token"]`, and **nothing in the repo ever writes that
   key** (only tests do). So `is_worker_connected` can never be true, the runtime
   mode is unreachable, and every job on such a provider retries to failure. ~250
   lines, 2 endpoints, and a runtime mode.
5. **`POST /api/v2/memories/reindex` is unauthenticated and unbounded** — runs a
   local embedding model over every memory in-request with one commit at the end.
   No frontend consumer; the UI uses the lorebook reindex.
6. **`world_hub.get_relationships` applies `limit`/`offset` to 1 of 5 sub-queries**
   — the advertised pagination contract is false.
7. **`config.update_config` is a lock-free read-modify-write** of a module global,
   called via `to_thread` from two routes, with a truncate-then-write persist.
   `llm_config.py` was fixed to `mkstemp`+`os.replace`+`fsync`; `config.json` was
   not, so the two config writers now use different durability.
8. **`_track_job` holds the load-balancer lock across the `to_thread`** its own
   comment says it releases — every 20th job blocks all provider selection for a
   thread hop plus a commit.
9. **`agent_simulation.py`**: unbounded `Job` scan with a redundant `status ==
   SENT_TO_PROVIDER` term, and `chat_context_kwargs(...)` is called without
   `session=`, so a chat linked to a Persona row silently loses its persona in the
   idle-sim path only.
10. **`discovery.py`'s loopback/link-local guard never fires** — providers register
    a *hostname* (the container ID), `ipaddress.ip_address()` raises on it, and
    `COMFY_DISCOVERY_ALLOWED_HOSTS` is empty. The RFC1918 restriction is dead code
    for the common case; the token is the only gate.
11. `ruff.toml`'s `tests/**` F811 ignore and the `F405` star-import ignores are
    fine, but `AGENTS.md` should be updated — it still describes the old ruff
    behaviour. *(Partly done: the config is now correct; the doc line is the
    remaining bit.)*

### Frontend

12. **`SamplingControls` PATCHes on every keystroke** and invalidates a 3-key
    prefix per PATCH (4 PATCHes + 16 refetches for typing `0.85`), and a failed
    PATCH rolls the cache back so the character you just typed vanishes.
    `ContextSlider` already gets this right by committing on `onMouseUp`.
13. **`useChatStreaming`/`useMessages`/`useStories` invalidate `['world_vault','chats',id]`
    by prefix**, which also refetches the full system-prompt assembly on every
    completed chat job even though the payload never changes it.
14. **`useProvidersPageData` refcount race** — the consumer cleanup calls
    `realtimeState.cleanup?.()` while init is still in flight, so listeners are
    installed with zero consumers and never removed. `WeakMap`-keyed, so they
    survive every navigation for the life of the tab.
15. **`FeedCard` Img2Img/Inpaint hang forever on a decode failure** —
    `new Promise(resolve => img.onload = resolve)` has no `onerror` and no
    timeout, so the `catch` is never reached and the menu item is simply inert.
16. **Three window-level Escape handlers on `/gallery`** plus a raw
    `addEventListener`; `useKeyboardShortcuts` is registered twice. The `d`/`g`/`m`/`a`
    shortcuts still call `navigate()` twice.
17. **`StorySandbox.collectionsList` is unmemoised** and passed to a
    `React.memo`'d modal, so the memo buys nothing on a page that re-renders per
    streamed token.
18. **The story title can never be cleared** — uncontrolled input + an early
    return on `!newTitle.trim()`, so the DB keeps the old title while the UI shows
    empty.
19. `useBranches(chatId, activeBranch)` — the second parameter is dead, so no
    branch row shows as active on a normal `/chat/:id` entry.
20. `TokenMeter` has no `AbortController` and no response-ordering guard.
21. `StoryEditor`'s Mention insert dereferences `textareaRef.current` in a
    `setTimeout` with no cleanup.

### Providers / infra

22. **Four response dialects remain live across nine engine methods**, all with
    HTTP 200: `{"success": bool}`, `{"status":"error"}`, bare `{"files": [...]}`,
    and raw third-party pass-through. A caller cannot distinguish success from
    failure by status code.
23. **`direct_url.validate_models` discards its whole result** — it passes
    `available=` to `StatusResponse`, which declares no such field, and Pydantic v2
    defaults to `extra='ignore'`.
24. **Google LLM engine leaks the API key into URLs** — `?key=...` in the request
    path, so it lands in proxy logs, in httpx exception text, and in the job record
    via `TaskEvent(message=...)`. `anthropic` correctly uses `x-api-key`.
25. **`/info` and `/provider-stats` are unauthenticated on every provider.**
    `/info` returns the upstream endpoint (a Modal URL here). `/provider-stats`
    fans out to 16 `MODEL_DIRECTORIES` × `list_models` on a `remote_comfy`
    provider — unauthenticated amplification. Neither has a consumer.
26. **A 503 "token not configured" is advertised as `retryable: true`**, so a
    permanently misconfigured provider makes the dispatcher fail the job over to a
    second provider, spending real money on a request that cannot succeed.
27. **`beam_app`'s two FastAPI apps have no auth** while holding the same volume
    as the local worker, which is gated. *(UNVERIFIED whether beta9's gateway
    authenticates the deployment URL independently — not determinable from the
    repo.)*
28. **No `.env.example*` for `.env.direct-url` / `.env.remote-comfy`**, and
    `COMFYUI_URL`, `COMFYUI_API_KEY`, `REMOTE_AGENT_URL`, `REMOTE_AGENT_TOKEN`,
    `MODAL_VOLUME_NAME`, `BEAM_VOLUME_NAME` and
    `RECONCILIATION_DELETE_ORPHANS` — the one variable that arms mass deletion —
    are documented nowhere.
29. **Three fire-and-forget `asyncio.create_task` calls with no retained
    reference** (`remote_comfy`, `direct_url`, `base_client`), so a multi-GB
    download is GC-eligible while in flight. Only `beam` retains its tasks.
30. **`deploy.py` is quadratic** — for each 1 KB chunk of `modal deploy` output it
    re-concatenates the whole buffer and reassigns the state dict.
31. `image_worker/comfy/comfy_server.py` is 189 lines of dead code that also
    cannot run in that image; `llm_worker/Dockerfile` has no `USER` and hardcodes
    `--port 8000`; `llm_worker/worker.py` never starts the reconciliation loop.

---

## 3. Notes for the next pass

- **The statistics rewrite produced a real regression that only the new tests
  caught.** Deriving `models.checkpoints` and `performance.by_model` from the
  *marginal* of the `GROUP BY (checkpoint, sampler)` grouping silently dropped
  every asset generated without a recorded sampler. Single-dimension groupings are
  now separate queries. Worth remembering: the marginal of a joint grouping is not
  the distribution.
- **`setQueriesData` by prefix is not safe when a detail query lives under the
  same prefix.** It matched the chat *detail* entry and `.map` threw, failing the
  whole mutation. The optimistic-update code needs the `Array.isArray` guard and
  the snapshot taken before the detail is patched, or the rollback restores the
  already-optimistic value.
- **Blanket-ignoring F401 was hiding a real bug and would have hidden a worse
  one.** Turning it on immediately found a stale import and broke 8 tests whose
  `monkeypatch.setattr` needs a module-level name — which is the actual reason to
  ignore a rule, spelled out per line instead of per repo.
- **A "fixed in a later commit" claim in a commit message is not evidence.**
  `move_asset` is described as converted and is not. Read the current file.
