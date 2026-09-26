# TNHComfy — Project Status

**The single authoritative status document.** Everything here was verified
against the code on 2026-09-26, not carried over from an earlier plan.

If you are about to make a decision about what to work on next, this file and
`docs/audit-2026-09-26.md` are the only two things you need to read. The other
planning documents that used to sit at the repo root are historical and live
in `docs/archive/` — they are kept for provenance, not for guidance.

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

1. **`/api/statistics/*` aggregates in Python, not SQL.** Each of `/` and
   `/detailed` loads all 16k `assets` rows, so a cold request takes ~5s.
   Warm requests are 0.04s thanks to the 5-minute cache. Fix is
   `GROUP BY metadata_->>'checkpoint'` plus `date_trunc`.
2. **Model fetch materialises the whole file in RAM.** The backend proxy and
   the Beam engine both load the entire checkpoint into memory (Beam
   base64-decodes it). A 7 GB SDXL checkpoint cannot survive this. Needs a
   ranged/streaming transport across four engines and the proxy.
3. **Provider model downloads have no resume.** A dropped connection 6 GB into a
   large checkpoint restarts from zero. The per-path lock and unique temp file
   landed, so concurrent downloads can no longer corrupt a model, but
   `Range`-based resume and retries are still absent.
4. **~45 hand-rolled modal overlays.** `useEscapeKey` and `ModalOverlay` now
   exist and cover `ConfirmationModal` plus all 9 story dialogs, so those
   dismiss with Escape; the chat, model-manager, provider and page-level
   overlays have not been converted. The remaining work is mechanical but
   wide, and a `components/common/Modal.jsx` still exists alongside
   `ModalOverlay.jsx` — merging them is a follow-up, not a prerequisite.
5. **`CharacterCard` is implemented twice** (`pages/Characters.jsx`,
   `pages/AvatarGallery.jsx`) with divergent props, tag limits, and
   drag-and-drop.
6. **The app has no authentication.** Deliberate — `DEMO_GAPS_PLAN.md` records
   the decision as out of scope for a local single-user studio — but it means
   every destructive endpoint, including the unauthenticated published-story
   export, is reachable by anyone who can reach the port. Do not expose this
   to a network you do not control.
7. **Deferred unification items** from the August plan, still untouched:
   `inference_loop` extraction from the providers, full `worker_ws` protocol
   unification, e2e helper dedup.

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
| Know what's left to do | this file, then `docs/audit-2026-09-26.md` |
| Understand the code | `AGENTS.md`, then the module itself |
| Understand the product intent | `VISION.md` |
| Understand a past decision | `docs/archive/` (historical; may be wrong) |
| See what the last audit found | `docs/audit-2026-09-26.md` |
