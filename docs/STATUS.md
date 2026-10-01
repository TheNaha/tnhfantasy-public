# TNHComfy — Project Status

**The single authoritative status document.** Everything here was verified
against the code on 2026-10-01, not carried over from an earlier plan.

If you are about to make a decision about what to work on next, read this file
and then the **most recent** audit, which is `docs/audit-2026-10-01.md`. Each
audit supersedes its predecessors for everything it marks fixed; reading an
older one tells you about defects that no longer exist. The other planning
documents that used to sit at the repo root are historical and live in
`docs/archive/` — they are kept for provenance, not for guidance.

## What this is

A ComfyUI wrapper with a friendly UI, built on provider containers (Modal, Beam,
direct_url, remote_comfy) that hold their own credentials under a
one-account-one-container policy. Three pillars over one World Vault data layer
(Postgres + pgvector):

1. **Image generation** — the original core. Jobs are dispatched to whichever
   provider the load balancer picks.
2. **Roleplay chatbots** — SillyTavern-style, with autonomous agentic turns
   (scene narration, image generation) and character-card import/export.
3. **Story sandbox** — AI-Dungeon-style chapter editor with comic/webtoon export.

## Architecture in one page

| Layer | Path | Notes |
|---|---|---|
| Backend | `backend_v2/` | FastAPI + SQLModel. Services take a request-scoped `Session` and build repositories internally; routes resolve via `api/deps.py`. |
| Frontend | `frontend_v2/` | React + Zustand (UI state only) + React Query (all server data). |
| Providers | `provider_containers/` | `provider_core` is the shared library; `image_worker`, `llm_worker` and `tts_worker` are the three entrypoints. A new worker kind is "a directory with a Dockerfile in it" — the deploy orchestrator builds it by name, so TTS needed no new provider type and no new credentials. |
| Agents | `remote_agent/` | Optional remote GPU rig, driven over HTTP by the backend. |
| Migrations | `backend_v2/infrastructure/migrations/steps.py` | Ordered `MigrationStep` list, run at startup. No Alembic. |

Conventions live in `AGENTS.md` and are worth reading before changing anything:
error handling via the `ComfyError` hierarchy, `metadata_` in Python and
`metadata` on the wire, config precedence `COMFY_*` env > `config.json` >
`DEFAULT_CONFIG`, and container naming `tnhcomfy-{PROVIDER_ID}`.

## Verified state

All three suites green as of **2026-10-01**:

| Suite | Count | Command |
|---|---|---|
| Backend | **2817 passed, 7 skipped** (306 s) | `cd backend_v2 && .venv/bin/pytest` |
| Frontend | **1326 passed across 141 files** | `cd frontend_v2 && npm test` |
| Providers | **793 passed, 4 skipped** (76-81 s) | `cd provider_containers && venv/bin/python -m pytest` |

All three figures were re-measured on **2026-10-01**, not carried over. The
backend grew by 29 tests and, unlike the 2026-09-29 run, is **fully green** — the
`test_app_boot_smoke.py::test_lifespan_runs_every_declared_startup_phase` flake
that failed on 2026-09-29 passed here. It is still a flake (it has now failed 1
run in 4) and is not fixed.

> **The stack was rebuilt and redeployed during the 2026-10-01 audit and
> verified reachable afterwards:** `http://localhost:5174` → 200,
> `http://localhost:8002/api/health` → 200, all 9 containers healthy.

**A green suite says nothing about whether the container is serving the code under
test.** The 2026-09-27 backend count was wrong precisely because the documented
state had drifted from the measured state while both kept looking authoritative.
The compose defect in the next paragraph is the same failure in a different place:
CI had been green — or red — about a file the suites never read.

Lint: `ruff check .` clean in the backend **and** in `provider_containers` (which
now has its own `ruff.toml` selecting `F`, with F401 on and zero blanket ignores).
`npm run lint` reports **0 errors and 12 warnings**: eleven
`react-hooks/exhaustive-deps` in `src/contexts/ChatWorkspaceContext.jsx` and
`src/pages/BatchGenerate.jsx`, plus one `react-hooks/incompatible-library` each in
`src/hooks/useScrollRoot.js` (TanStack Virtual's `useVirtualizer()`) and
`src/pages/StorySandbox.jsx`. `npm run build` is clean.

Compose: `docker compose -f docker-compose.yml -f docker-compose.dev.yml
--profile providers config --quiet` exits 0 once the env files exist, and the
`build` job in `.github/workflows/provider-tests.yml` runs it plus a build of
**four** provider Dockerfiles — `image_worker`, `llm_worker`, `tts_worker` and the
remote agent's. That job went red at its first step on every clean checkout
**twice, for the same reason** — a compose `env_file:` with no file seeded next to
it — and on two different occasions:

- First (2026-09-28, fixed): compose refuses to render while an `env_file:` is
  missing, and every `.env*` is gitignored, so the step exited 1 and the
  `docker build`s below it never ran.
- Second (until 2026-09-29): `provider-tts-modal-hp196` was added to the
  `providers` profile with `env_file: - .env.tts-modal-hp196` and the seeding list
  was not updated, so the step exited 1 again.

Both times the job was the *only* thing that could have caught the change it
tripped on, and it was not triggered at all by a change to `docker-compose.yml`,
because no workflow watched that path. That is now fixed on both sides: the job
seeds from the compose file's own `env_file:` entries and fails with the missing
name if one is unseeded, and `docker-compose*.yml`, `scripts/**`, `.env.example*`
and `.github/workflows/**` are in its `paths:` filter.

`tts_worker/Dockerfile` was built by no workflow until 2026-09-29, and it is the
image `ProviderDeployOrchestrator` uses for every `task_type="tts"` deploy — so a
broken `COPY` in it broke TTS deployment on every host while every job stayed
green. `backend_v2/Dockerfile` and `frontend_v2/Dockerfile` are still built by no
workflow.

`docs/api.md` covers 201 of the **329** live operations and had 26 endpoints that
do not exist until 2026-09-29, including two whole sections under the wrong URL
prefix. It is checked against `app.openapi()["paths"]`, not against itself.

Running the suites is the point. 128 provider tests, 11 frontend tests and 10
backend tests were added by the 2026-09-27 pass alone, and the counts above are
the only trustworthy thing in this file.

> **The counts above were wrong until 2026-09-27 and this table is the reason to
> distrust any status table in a repo that nobody re-runs.** The previous
> revision of this section claimed "all three suites green" with a backend count
> of 1931; the suite actually had **24 failures** and took **18 minutes** rather
> than the 197 s it had taken a week earlier. Nothing had been run.
>
> `docs/audit-2026-09-27.md` is the record of the consolidation pass that
> followed: two P0s (committed live credentials; every unhandled exception
> taking ~22 s to become a 500, which is what had made the suite 5× slower), plus
> a broken faceted-search endpoint, a job-recovery path that failed **open** on a
> database error, a job that could be permanently stranded, a paid LLM call on
> every chat reply, unbounded reads, and roughly forty `async def` handlers doing
> synchronous queries on the event loop. The backend suite went from 1097 s to
> ~250 s as a side effect of fixing the logging defect alone.

Feature-wise the project is **complete against its own ambitions**. An earlier
plan listed sampler controls, story-loop AI actions, chapter revisions, group
chats with speaker attribution, agentic story illustration, SillyTavern
interop and a command palette — all are implemented and wired, not stubbed.
The gap was never missing capability; it was that some things lied about
themselves. See the audit.

> **`docs/audit-2026-09-28.md` supersedes this section for the 2026-09-28
> findings.** The paragraph above is now wrong in three specific ways, which is
> exactly the failure mode it describes. As of that audit:
>
> - **Group chats with speaker attribution were NOT wired.** The roster field was
>   missing from both chat request models and pydantic dropped it silently, and
>   the job-completion event discarded `character_id` before it reached the
>   message — so every AI reply was attributed to the primary character. Both
>   fixed, with regression tests.
> - **Chapter revisions were partially wired.** The autosave path bypassed the
>   revision repository, so the retention limit was never enforced on the path
>   that actually creates revisions — and the same path was destroying the
>   chapter's beat list on every save.
> - **Roughly forty `async def` handlers** became ~196, and only some were
>   fixed. Measured on the running stack: 20 concurrent requests to a 9 ms
>   endpoint take **400 ms**, so effective concurrency is 1×. The high-frequency
>   offenders are fixed; the architectural cause is not.

## What was actually wrong, and is now fixed

The 2026-09-26 hardening pass (24 commits, `83ad704..97271ba`, branched from
`ae3a010`) fixed the classes of bug that make a system untrustworthy. The
notable ones:

- **nginx cached the backend's IP forever**, so any backend restart meant 502 on
  every API route until the frontend was also restarted. Now re-resolved per
  request, and verified by moving the backend to a new IP with the frontend
  untouched.
- **Provider auth failed open** when `PROVIDER_WORKER_TOKEN` was empty, which
  was the shipped default — leaving `/inference` and `/deploy` (which shells
  out to `modal deploy`) open. Now fails closed with 503.
- **The test suite ran with foreign keys disabled**, so dangling references
  Postgres would reject passed CI. Enabling the pragma exposed 15 tests
  seeding rows against parent rows that do not exist.
- **Story chapter auto-save could silently never fire** — its debounce effect
  depended on a `useMutation` result object, which react-query v5 recreates
  every render, so any background re-render restarted the window.
- `jobs.max_concurrent` was editable in Settings and enforced nowhere, so
  throttling paid-GPU spend by lowering it did nothing.

## What is genuinely still open

Verified as real and not yet fixed. Ordered by how much they cost you.
The most recent audit has the full list with file:line detail.

Items 1-6 of the previous list were fixed — see §1b of the follow-up. What remains:

1. **The app has no authentication.** Deliberate — `DEMO_GAPS_PLAN.md` records
   the decision as out of scope for a local single-user studio — but it means
   every destructive endpoint, including the unauthenticated published-story
   export, is reachable by anyone who can reach the port. Do not expose this
   to a network you do not control. Note that the production compose publishes
   **8002 on 0.0.0.0**, and `docs/api.md`'s stated mitigation ("enforce
   authentication at the reverse-proxy layer") has no Traefik router for 8002 —
   the only router is for 5174. The dev override restricts `db` to `127.0.0.1`,
   which makes the omission look accidental rather than intended.
   **This stopped being theoretical on 2026-10-01:** an audit sub-agent's
   in-process probe called `DELETE /api/jobs` and deleted all 154 rows of job
   history. Assets (16,677 rows, 16,342 PNGs) were verified intact, because
   `assets.job_id` is an un-FK'd soft reference nothing joins on — but the loss
   is real and it happened from an ordinary probe. Nothing destructive should be
   pointed at this stack until auth exists.
2. **A 7 GB checkpoint is now servable, but slowly on Modal.** All four engines
   stream instead of buffering, and the backend has a `stream_file` path. Modal is
   the exception: a modal method serialises its return value across RPC, so the
   client pulls fixed 8 MiB ranges — one RPC per slice. Correct, memory-safe, and
   slower than the others. Streaming that engine properly means a presigned URL or
   a volume mount rather than RPC, which is a platform decision.
3. ~~**Provider model downloads still have no resume.**~~ **Fixed** — already
   shipped before this audit: `downloads.py` has `_transfer_with_resume`,
   `_claim_resume_slot`, `Content-Range` parsing, `If-Range`, and a "server
   ignored Range" restart path, pinned by `tests/test_download_resume.py` (29
   tests). The 2026-09-28 audit additionally removed an `os.remove` that sat
   immediately before the atomic `os.replace`, which opened a window where a kill
   left neither the old nor the new model.
4. ~~**`world_hub.get_relationships` applies its `limit`/`offset` to one of five
   sub-queries.**~~ **Fixed** — the route now clamps `limit` (1-1000) and
   `offset` (>=0) and windows every sub-query; its docstring records the fix, and
   `tests/test_world_hub_relationship_pagination.py` pins it.
5. **Remaining hand-rolled overlays.** The highest-value conversions are done and
   `Modal` is built on `ModalOverlay`; the rest is mechanical and wide. A
   one-line `@media (hover: none)` rule now also makes all 30 hover-revealed
   action rows reachable on touch, which had made nine roleplay dialogs and every
   per-message action unusable on a phone.
6. **The embedding model still loads inside the reindex request** — seconds on
   first call. Moving it to startup needs `services/embedding_service.py`. (The
   two *inference* call sites are now off the event loop; this one is not.)
7. ~~**The two `worker.py` bootstraps share ~35 lines.**~~ **Fixed** —
   `provider_core/worker_bootstrap.py` exists and both entrypoints import from
   it. Residual duplication is ~35 lines of env-parsing preamble in each, plus
   the four "method not supported" tails and the four hand-rolled SSE parsers on
   the LLM side.

### Added by the 2026-09-28 audit

`docs/audit-2026-09-28.md` is the full list. The four that changed behaviour
rather than tidying:

- **The LLM Modal provider deleted every model on its volume every two hours.**
  A magic-byte table was unpacked backwards, so `bytes` was compared to a format
  name — always false — and reconciliation swept the directory as "invalid".
  Only the LLM twin re-implemented a check the shared helper already owned.
- **Chapter autosave destroyed the beat list, silently, every few seconds.** The
  PUT body deserialised into a SQLModel *table* model, which FastAPI does not
  validate, so an absent field arrived as `[]` and the guard read it as "clear".
- **The job-completion event dropped the job's metadata.** A shallow merge meant
  a three-key `event_extra` replaced the whole dict, which is why group-chat
  attribution and swipe alternates never worked.
- **The gallery virtualizer measured `window` while the app scrolls an inner
  pane**, so it rendered the first viewportful and never advanced — on every
  desktop visit. It survived a green suite because being bound to `window` meant
  it always had a height, so it always rendered *something*.

The heaviest frontend chunk also went from 1281.92 kB to 311.46 kB (`index-*.js`),
with `StorySandbox` at 253.17 kB: the story editor was shipping all 594 of
`refractor`'s syntax grammars to render prose. The bundle is not split into one
small set of chunks — a 290 kB `LineChart` and a 311 kB entry chunk sit alongside
25 kB route chunks — so "the heaviest chunk" is now a fact about a different file
each time the router moves.

### Dropped after investigation, not overlooked

`inference_loop` extraction was on the deferred list for months. It was
investigated and is not worth doing as described:

- The named loops do not exist. `image_worker/worker.py` and
  `llm_worker/worker.py` are app entrypoints with only `reconciliation_loop` and
  `auto_discovery_loop` — model *discovery*, not job dispatch.
- The shared lifecycle already exists, once, in the backend. Claim is
  `job_queue._worker`; dispatch, retry, failover, completion and cancellation are
  `job_runner.execute_job`, a single function that already serves both task types
  and switches only at the point where the engine-specific call is injected.
  Cancellation is one `JobCancellationTracker` singleton. Extracting this would be
  a rename.
- A module at `backend_v2/services/inference_loop.py` is unreachable from both
  engines anyway: neither Dockerfile copies `backend_v2`, so the shared code would
  have to live in `provider_core`.

## Running it

```bash
# First time on a host, or after pulling — creates the external networks and
# reports the config that silently disables features.
bash scripts/preflight.sh

docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile providers up --build -d
```

The frontend serves on **:5174** (not 5173) and proxies `/api` and
`/socket.io` to the backend on :8002. See `AGENTS.md` for the rest.

## Where things live

| I want to… | Look in |
|---|---|
| Know what's left to do | this file, then the most recent audit's open-findings table |
| Understand the code | `AGENTS.md`, then the module itself |
| Understand the product intent | `VISION.md` |
| Understand a past decision | `docs/archive/` (historical; may be wrong) |
| See what the last audit found | `docs/audit-2026-10-01.md` |
| See earlier audits | `docs/audit-2026-09-29b.md`, then `docs/audit-2026-09-29.md` (each superseded by the next) |
