# TNHComfy — Project Status

**The single authoritative status document.** Everything here was verified
against the code on 2026-09-26, not carried over from an earlier plan.

If you are about to make a decision about what to work on next, this file,
`docs/audit-2026-09-26-followup.md` and `docs/audit-2026-09-26.md` are the only
three things you need to read. The other planning documents that used to sit at
the repo root are historical and live in `docs/archive/` — they are kept for
provenance, not for guidance.

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
| Providers | `provider_containers/` | `provider_core` is the shared library; `image_worker` and `llm_worker` are the two entrypoints. |
| Agents | `remote_agent/` | Optional remote GPU rig, driven over HTTP by the backend. |
| Migrations | `backend_v2/infrastructure/migrations/steps.py` | Ordered `MigrationStep` list, run at startup. No Alembic. |

Conventions live in `AGENTS.md` and are worth reading before changing anything:
error handling via the `ComfyError` hierarchy, `metadata_` in Python and
`metadata` on the wire, config precedence `COMFY_*` env > `config.json` >
`DEFAULT_CONFIG`, and container naming `tnhcomfy-{PROVIDER_ID}`.

## Verified state

All three suites green as of 2026-09-26:

| Suite | Count | Command |
|---|---|---|
| Backend | 1931 passed, 7 skipped | `cd backend_v2 && .venv/bin/pytest` |
| Frontend | 764 passed across 93 files | `cd frontend_v2 && npm test` |
| Providers | 105 passed | `cd provider_containers && venv/bin/python -m pytest` |

Lint: `ruff check .` clean in the backend, `npm run lint` reports 0 errors
(one pre-existing `react-hooks/exhaustive-deps` warning on a ref read inside a
timeout, which is correct as written).

Feature-wise the project is **complete against its own ambitions**. An earlier
plan listed sampler controls, story-loop AI actions, chapter revisions, group
chats with speaker attribution, agentic story illustration, SillyTavern
interop and a command palette — all are implemented and wired, not stubbed.
The gap was never missing capability; it was that some things lied about
themselves. See the audit.

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
`docs/audit-2026-09-26-followup.md` §2 has the full list with file:line detail.

Items 1-6 of the previous list were fixed — see §1b of the follow-up. What remains:

1. **The app has no authentication.** Deliberate — `DEMO_GAPS_PLAN.md` records
   the decision as out of scope for a local single-user studio — but it means
   every destructive endpoint, including the unauthenticated published-story
   export, is reachable by anyone who can reach the port. Do not expose this
   to a network you do not control.
2. **A 7 GB checkpoint is now servable, but slowly on Modal.** All four engines
   stream instead of buffering, and the backend has a `stream_file` path. Modal is
   the exception: a modal method serialises its return value across RPC, so the
   client pulls fixed 8 MiB ranges — one RPC per slice. Correct, memory-safe, and
   slower than the others. Streaming that engine properly means a presigned URL or
   a volume mount rather than RPC, which is a platform decision.
3. **Provider model downloads still have no resume.** The per-path lock and unique
   temp file landed, so concurrent downloads cannot corrupt a model, and
   `Range`-based resume is in progress.
4. **`world_hub.get_relationships` applies its `limit`/`offset` to one of five
   sub-queries**, so the advertised pagination is not honoured. Everything is
   bounded, so it is a wrong-answer bug rather than a cliff.
5. **Remaining hand-rolled overlays.** The highest-value conversions are done and
   `Modal` is built on `ModalOverlay`; the rest is mechanical and wide.
6. **The embedding model still loads inside the reindex request** — seconds on
   first call. Moving it to startup needs `services/embedding_service.py`.

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
| Know what's left to do | this file, then `docs/audit-2026-09-26-followup.md` §2 |
| Understand the code | `AGENTS.md`, then the module itself |
| Understand the product intent | `VISION.md` |
| Understand a past decision | `docs/archive/` (historical; may be wrong) |
| See what the last audit found | `docs/audit-2026-09-26-followup.md` |
| See the audit before it | `docs/audit-2026-09-26.md` |
