# TNHComfy — Project Status

**The single authoritative status document.** Everything here was verified
against the code on **2026-10-10**, not carried over from an earlier plan.

If you are about to make a decision about what to work on next, read this file
and then the **most recent** audit, which is `docs/audit-2026-10-10.md`. That
audit is a *delta* pass scoped to what the 2026-10-08 engine consolidation left
behind; for anything that predates 10-08, `docs/audit-2026-10-05.md` remains the
reference. Each audit supersedes its predecessors for everything it marks fixed;
reading an older one tells you about defects that no longer exist. The other
planning documents that used to sit at the repo root are historical and live in
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
| Backend | `backend_v2/` | FastAPI + SQLModel. Services take a request-scoped `Session` and build repositories internally; routes resolve via `api/deps.py`. In-process compute engines are the default runtime. |
| Frontend | `frontend_v2/` | React + Zustand (UI state only) + React Query (all server data). Schema-driven provider management, model discovery & live diagnostics. |
| In-Process Engines | `backend_v2/services/engines/` | Primary provider execution engine (Modal, Beam, DirectComfy, LLM, TTS) unified into the backend without container footprint. |
| Agents | `remote_agent/` | Optional remote GPU rig (ComfyUI host), driven over HTTP by the backend. `remote_agent/provider_core/` is the shared HTTP/auth/storage helper library the agent imports. |
| Migrations | `backend_v2/infrastructure/migrations/steps.py` | Ordered `MigrationStep` list, run at startup. No Alembic. |

> Container removal (2026-10-08): the `provider_containers/` tree
> (`image_worker/`, `llm_worker/`, `tts_worker/`, and the shared `provider_core/`)
> and the `--profile providers` compose profile have been removed. Provider
> workers were folded into in-process engines; `provider_core` relocated to
> `remote_agent/provider_core`. `EventType.PROVIDER_CONTAINER_STATUS`,
> `PROVIDER_DEPLOY_*`, the discovery/health/deploy worker HTTP endpoints, and the
> `tnhcomfy-{ID}` container-naming convention are all gone.

Conventions live in `AGENTS.md` and are worth reading before changing anything:
error handling via the `ComfyError` hierarchy, `metadata_` in Python and
`metadata` on the wire, config precedence `COMFY_*` env > `config.json` >
`DEFAULT_CONFIG`, and provider naming derived from the provider row type.

## Verified state

All three suites green as of **2026-10-21**, re-measured after the
consolidation sweep recorded in `docs/audit-2026-10-21.md`:

| Suite | Count | Command |
|---|---|---|
| Backend | **4217 passed, 5 skipped** (~6 min) | `cd backend_v2 && .venv/bin/python -m pytest` |
| Frontend | **2059 passed across 232 files** (~4 min) | `cd frontend_v2 && bun run test -- --run` |
| remote_agent | exports clean (no tests of its own) | covered by `tests/test_in_process_engines.py` contract tests |

`bun run lint` is **0 errors / 3 warnings** and `ruff check .` is clean.

Stack verified live after the changes: `localhost:5174` → 200,
`/api/live` and `/api/ready` → 200, and the negative-`limit` probes that used to
answer a 500 (or an unbounded SQLite dump) now answer 200. The backend container
mounts `backend_v2` at `/app`, so a plain restart picks the changes up.

Both suites were **red** at the start of that pass — 4 failed + 5 errored on the
backend, 2 failed on the frontend, 2 lint errors — all caused by `9a91e6f2`
deleting code without updating its consumers. See the entry below.

> Container removal (2026-10-08): the `provider_containers/` tree
> (`image_worker/`, `llm_worker/`, `tts_worker/`, and the shared `provider_core/`)
> and the `--profile providers` compose profile have been removed. Provider
> workers were folded into in-process engines; `provider_core` relocated to
> `remote_agent/provider_core`. `EventType.PROVIDER_CONTAINER_STATUS`,
> `PROVIDER_DEPLOY_*`, the discovery/health/deploy worker HTTP endpoints, and the
> `tnhcomfy-{ID}` container-naming convention are all gone. `COMFY_USE_IN_PROCESS_ENGINES`
> no longer exists — in-process is the only runtime.

> **The "known flaky" backend test was not flaky.** This section previously carried
> `test_lifespan_runs_every_declared_startup_phase` as a load-sensitive flake that
> "failed in two of four runs". It was deterministic: its `EVENT_BUS_TOPICS` listed
> `"download"`, which has had no `EventType` behind it since the family was removed
> on 2026-10-03, so `assert 0 > 0` could not be satisfied by any correct lifespan.
> It reproduced in 24 s alongside 67 other tests. The list is now derived from
> `EventType`, and the test is green. **There is no known-flaky backend test.**

> **The backend CI job had been red for four days, and that is why local numbers
> were not CI numbers.** `tests/conftest.py` probed every module in `sys.modules`
> with `getattr(module, "get_session_sync", None)`, and `transformers` defines a
> PEP 562 `__getattr__` that resolves an unknown name by *importing the submodule it
> names* — which reached `torchvision`, absent from `requirements.txt`. The
> autouse fixture raised and 1355 of 2832 tests errored in CI while passing
> locally, because the local venv has no embedding stack at all. Fixed by scoping
> the loop to backend modules. **`torchvision` is still missing**, so the embedding
> paths remain uncovered — see §1b item 1.

The frontend count grew by exactly what each pass added, and every new
invariant test file was confirmed to **fail** when its fix is reverted — the only
property that makes an invariant test worth more than the list it replaces.

2026-10-03 added four: `queryErrorInvariants`, `settingsKeysHaveReaders`,
`no_table_class_request_bodies`, and a cross-module await-chain resolver in
`test_event_loop_invariant`.

**2026-10-03b added nine more**, seven frontend and two backend:

| Test | Retires |
|---|---|
| `streamingJobTerminalInvariants` | a terminal event arriving before the submitter's HTTP response |
| `eventContractInvariants` | an `EventType` with no frontend constant, no producer, or no subscriber |
| `hoverRevealInvariants` | a hover-reveal group missing from the touch-device rescue, and a rescue entry nothing uses |
| `chatWorkspaceContextMemo` | a context key published without a matching `useMemo` dependency |
| `vaultQueryKeyInvariants` | a hand-written `['world_vault', …]` key literal |
| `test_batch_endpoint_bounds` | an unbounded batch request body |
| `test_published_story_redaction` | the published export leaking a key the published read withholds |
| `test_like_pattern_escaping` (AST guard) | escaping a LIKE pattern without the `ESCAPE` clause |
| `test_validation_twin_parity` (providers) | the image and LLM sweeps disagreeing on what `indeterminate` means |

Three of the four guards in this table are **generated from the thing they
constrain** rather than hand-maintained: `hoverRevealInvariants` reads every
`group-hover/<name>` out of `src/**`, `eventContractInvariants` parses both event
enums, and `chatWorkspaceContextMemo` parses both sides of the memo. A
hand-maintained list is the defect — the previous pass's `preflight.sh` provider
check and this pass's hover-reveal block both failed by being one.

> **The stack was verified reachable after the 2026-10-03 changes**, which is
> worth stating explicitly because both tiers hot-reload in this dev stack —
> `frontend_v2/src` is bind-mounted into a Vite dev server with `usePolling`, and
> `backend_v2` is bind-mounted with `COMFY_UVICORN_RELOAD=1` — so no rebuild is
> needed for a source change, and a stale-container class of defect cannot occur
> here: `http://localhost:5174` → 200, the backend → healthy with all 9
> containers running.
>
> **There is no `http://localhost:8002` check in that list any more, and that is
> the point.** The backend used to be published on `0.0.0.0:8002`; it no longer
> is, so the host answers `000`. Verify it from inside the container instead:
> `docker compose exec backend_v2 curl -s localhost:8002/api/live`.
>
> That hot-reload is also a hazard worth knowing about: editing
> `infrastructure/database.py` re-resolves the DSN within a second of the save,
> on the live stack, against the environment the container already has.

**A green suite says nothing about whether the container is serving the code under
test.** The 2026-09-27 backend count was wrong precisely because the documented
state had drifted from the measured state while both kept looking authoritative.
The compose defect in the next paragraph is the same failure in a different place:
CI had been green — or red — about a file the suites never read.

Lint: `ruff check .` clean in the backend. `bun run lint` reports **0 errors and 3
warnings**: `react-hooks/exhaustive-deps` in `src/contexts/ChatWorkspaceContext.jsx`
and `src/pages/BatchGenerate.jsx`, plus one `react-hooks/incompatible-library` each in
`src/hooks/useScrollRoot.js` (TanStack Virtual's `useVirtualizer()`) and
`src/pages/StorySandbox.jsx`. `bun run build` is clean.

Compose: `docker compose config --quiet` (the deprecated `--profile providers` is
gone; provider workers are in-process now) exits 0, and the `app-images` job in
`.github/workflows/provider-tests.yml` renders compose plus a build of the remote agent's
image, the backend, and the frontend (prod + dev). That job goes red on a broken compose
render or a broken image `COPY`/system-package/install — the part of the stack no test
suite covers. A compose `env_file:` with no file seeded next to it used to make it exit 1
on every clean checkout **twice**, for the same reason:

- First (2026-09-28, fixed): compose refuses to render while an `env_file:` is
  missing, and every `.env*` is gitignored, so the step exited 1 and the
  `docker build`s below it never ran.
- Second (until 2026-09-29): `provider-tts-modal-hp196` was added to the
  `providers` profile with `env_file: - .env.tts-modal-hp196` and the seeding list
  was not updated, so the step exited 1 again.

With the containerized workers removed, `docker-compose.yml` no longer carries any
`env_file:` entries beyond the root `.env`, and `preflight.sh` only notes stale
per-worker env files rather than failing on them.

Both times the job was the *only* thing that could have caught the change it
tripped on, and it was not triggered at all by a change to `docker-compose.yml`,
because no workflow watched that path. That is now fixed on both sides: the job
seeds from the compose file's own `env_file:` entries and fails with the missing
name if one is unseeded, and `docker-compose*.yml`, `scripts/**`, `.env.example*`
and `.github/workflows/**` are in its `paths:` filter.

`tts_worker/Dockerfile` was built by no workflow until 2026-09-29, and it is the
image `ProviderDeployOrchestrator` uses for every `task_type="tts"` deploy — so a
broken `COPY` in it broke TTS deployment on every host while every job stayed
green. It was also missing from the `compileall` step until 2026-10-04, so a
syntax error in it reached main whenever the provider tests happened to pass.

`backend_v2/Dockerfile` and `frontend_v2/Dockerfile` were built by **no** workflow
until 2026-10-04. They are what actually runs in production and in every dev `up`,
and a green test suite says nothing about them: `backend-tests.yml` installs into a
host venv and `frontend-tests.yml` runs `bun install --frozen-lockfile` on the host, so neither would
notice that the image no longer builds — a bad `COPY`, a system package the
runtime needs, a requirements pin that no longer resolves. A new `app-images` job
in `provider-tests.yml` builds the backend image and both frontend targets, and the
two Dockerfiles (plus `backend_v2/requirements.txt` and
`frontend_v2/package-lock.json`) are in that workflow's `paths:` filter. It lives
there because GitHub has no job-level `paths:` — `on.<event>.paths` filters the
whole workflow — and it is a few minutes on a Dockerfile change.

`docs/api.md` documents **294 of 297** live paths (98.8%) on the **387**-operation
router. It had 26 endpoints that did not exist until 2026-09-29, including two
whole sections under the wrong URL prefix. It is checked against
`app.openapi()["paths"]`, not against itself — but the check's assertion is
`pair & {real_paths, real_ops}`, so one of the two matching is enough for it to
pass; a stale figure in the prose survived a passing guard. See
`docs/audit-2026-10-05.md` item 17.

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

### The 2026-10-20 character-interchange pass

The card codec was byte-lossless and the PRODUCT was not. `lost_fields` was
hardcoded `[]` and the UI turned that into *"Fully compatible. All reported
card data was imported."* while several SillyTavern features were preserved
and never executed, and one of them crashed the whole import.

**A card could crash the import.** A card carrying
`extensions.voice_model_id` for a voice model this vault does not have was
written straight into a foreign key, so the INSERT failed and the entire
character was lost to a 500. The value is now checked, dropped when it does
not resolve, and REPORTED as lost. A constraint failure on a card-supplied
value is a fact about the card, not a server fault.

**The lorebook entry semantics had nowhere to go.** A ST `character_book`
entry can carry `enabled`, `constant`, `selective` and `secondary_keys`, and
all four were dropped on import. `constant: true` means "always on" in ST,
and this vault's always-on test is a KEYLESS entry — so a constant entry
that also had keys became KEY-GATED and stopped firing. `enabled: false`
activated anyway. `secondary_keys` were thrown away, so `selective` could
not be honoured even if it had been stored. `lorebook_entries.enabled` and
`.secondary_keys` are new (migration 109), and
`rag_pipeline.entry_matches_keys` is now the single definition of the rules.

**The two tag lists stopped sharing a column.** `data.tags` is the card's
CHARACTER metadata ("fantasy", "elf") and `visual_tags` is this app's
IMAGE-GENERATION tag list. They shared one column, so importing a card put
"elf" into the character's own image prompts. The card's tags are now
preserved verbatim and written back as `data.tags`.

**The report stopped lying.** Three buckets instead of one: `lost_fields`
(dropped), `preserved_fields` (kept and written back), and
`preserved_but_inert` (kept, written back, and NOT ACTED ON here, each with
the reason). The third bucket did not exist, which is how a card whose
behaviour differed could still report as fully compatible.

**Expressions, in both directions.** `grep -c expression core/character_cards.py`
was 0. A V3 card carries its expression images in `data.assets` as base64;
they were preserved as inert JSON and never turned into images, so
`Character.expressions` was always empty after an import and an exported card
never carried them back out. They are materialised as real expression files
on import, written back on export, and a CHARX export carries them as
archive members.

**A native bundle, because a character here is bigger than a card.** The
export offered five formats and ALL FIVE were SillyTavern-shaped, so the only
way to move a character with expressions, a voice binding, a world and
chats was to lose most of it, silently. `format=bundle` produces a
`.tnhzip` carrying the character, the card alongside it, and the sections
you ask for.

**Re-import merges instead of duplicating.** Re-importing a card used to
INSERT a second character with the same name, every time, and nothing said so.
A card exported from this app carries the character's id in the app's own
`data.extensions.tnhcomfy`, and SillyTavern preserves unknown extensions —
so a card that has been through SillyTavern still says which character it
is. A re-import UPDATES it.

**One import entry point, with a preview.** The import used to write
immediately, so the only way to find out what a card would do was to do it.
`POST /characters/import/analyze` returns what it would do and writes
nothing; `POST /characters/import/commit` does the writing, with the scope
("just the character" or "into a world", which delegates to the World
Architect) and the match already chosen. The file input takes many cards
and queues them.

**The export can now say what it cannot carry.**
`GET /characters/<built-in function id>/export/preview` lists the features a card cannot
express — the expressions, the voice binding, the world and its
locations, the vault's lorebooks, the gallery, the chats, the memories —
and the export menu shows that list before the download.

### The 2026-10-20 image-generation coherence pass

An audit of the image generation surface — the Simple Generator and its
Enhancements panel, the Advanced Generator, Batch/Img2Img/Inpaint, the
Gallery, the job system, and the model/provider catalogue — found the
backend well-factored and the frontend carrying **four generator surfaces
that each had their own idea of what a generation request is**. The
Enhancements panel was the visible end of it: it is the part of the
Simple Generator that reaches past the guided form into the graph, and it
reached into the graph with a vocabulary the rest of the system did not
share.

**A restart re-paid for generations that had already completed.**
`recover_post_processing_jobs` awaits `finalize_persisted_job_outputs`, and
the finaliser ends in `start_background_task(...)` — so the await returned
before the finalisation ran, the startup sweep moved the still-POST_PROCESSING
job to PENDING with `claimed_at = NULL`, and PENDING-with-no-claim IS the
claim predicate. A live worker then ran the entire **paid** generation
again. The finalisation is awaited now, and the sweep EXCLUDES
POST_PROCESSING, which is a second guard that does not depend on the
ordering at all.

**The dashboard's "Recover" button failed jobs that were running
normally.** `STALE_JOB_TIMEOUT_SECONDS` was a global 300 seconds against a
legal image timeout of 3600, and the route's own docstring said "there is
no frontend consumer" — there is one, and it sent no timeout. Every job
running more than five minutes was marked FAILED. The stale window is now
each job's own task-type timeout, and the route REPORTS what is stale
instead of failing it unless the caller passes `force=true`.

**The job system had three contract systems, and the LLM path was one of
them.** The LLM reducer built its progress payloads by hand and published
them straight to `emit_job_event`: no `task_type` (so the frontend's
global handler dropped every frame), a `status` that was a hand-written
string rather than a `JobStatus`, and a `metadata` that REPLACED the job's
own — so the frontend's background-job guard could not fire, and a
memory-extraction job rendered as a second "X is thinking…" bubble under
the reply it was extracted from. It goes through `update_job` now. `status`
says what the job IS; the LLM sub-state is what it is DOING, and travels
as `phase`.

**`POST /api/generate` accepted two body shapes and the kind was
INFERRED**, so a hand-written ComfyUI graph with a node keyed `prompt` or
`mode` was routed to `options` and rejected by the option schema. The kind
is explicit now, and — the part that mattered — the two kinds get the
SAME treatment. The graph path had no prompt-shortcut expansion, no
embedding check, and no metadata at all: the gallery said "Unknown Model",
"Reuse parameters" restored nothing, and the PNG sidecar carried none of
the allowlisted keys.

**The Batch page was a second request builder**, carrying 15 of the Simple
page's 36 option fields. The missing ones were not cosmetic: a Flux model
was transmitted as `checkpoint` (and a UNET lives in `models/unet/`, not
`models/checkpoints/`, so no provider had it), `modelType` fell back to
`sd15` and gave an SDXL model the SD1.5 FreeU curve, and none of the
enhancements could be expressed at all. It calls the shared builder now,
and it runs the preflight. A partial batch is reported rather than thrown:
the jobs already created are real work, and the old code let the exception
escape, so the client got a 5xx, `setJobIds` never ran, and the Batch Jobs
panel stayed EMPTY while N-1 images were being produced somewhere.

**The Enhancements panel asked the provider nothing.** It hardcoded the
provider's node vocabulary in Python — `FreeU_V2`,
`PerturbedAttentionGuidance`, `FaceDetailer` — and the builder emitted
those nodes whatever the provider had installed, so a FreeU toggle
produced a graph the provider could not run and the job failed at dispatch
with "node type not found". `GET /api/nodes/capabilities` derives the
answer from the provider's OWN node graph, through the same cached
`object_info` the node palette already reads. "Not known" and "not
supported" are different answers, and the difference matters: a provider
that is down is not a provider that cannot do FreeU.

**Every image model read "Partial — 2 of 4 online providers ready."** The
badge's denominator was every online provider, and every provider with an
engine has the runtime state `in_process` — so the LLM and TTS providers
were counted, and they can never have an image model. And the backend wrote
a `pending` status row for every enabled provider BEFORE it worked out
which ones could act on it, so every LLM and TTS provider accumulated a
`pending` row for every image model, forever. Both halves are fixed.

**The scene's hires upscaler asked for a model named "latent."** There
were three vocabularies for it, none matching the others, and the scene's
was passed through untranslated — so the builder's model branch emitted an
`UpscaleModelLoader` with `model_name: "latent"`, for every one of the
scene's three values. The scene's hires fix did not work at all.

**And a config file that could not be parsed was overwritten with the
defaults.** The test suite restored the real `config.json` with a
truncating write, a parallel worker read it in the window, and the next
load replaced the operator's settings with `DEFAULT_CONFIG`. The
unreadable file is moved aside now, with a timestamp, and the restores are
atomic. This repository's own `config.json` was caught by it during this
work and restored from git history.

Also: the inpaint mask grew twice (`GrowMask` by the amount the user
asked for, then `VAEEncodeForInpaint` by a hardcoded 6); the "Inpaint
Masked Only" control was declared, sent, and ignored by a hardcoded
`noise_mask: True`; FreeU and PAG were "ignored for Flux models" in the
help text while the toggle stayed live and the rule lived in the backend,
so the user turned it on and nothing happened; the generator's model lists
are a different cache from the Models Manager's and nothing invalidated
them, so the generator showed a stale list for five minutes after a model
installed; the Providers page invalidated two query keys that matched
nothing, so it did not refresh after a credential edit or a deploy; and
four Gallery call sites fully invalidated an infinite query after a
deletion, which refetches every loaded page to remove one item.

### The 2026-10-20 remote-agent reliability pass

The remote agent was reported as unreliable on its minimum target (an L4, 24 GB
VRAM): "sometimes it oomed, crashed, underperform (because poor vram management
and the layers got loaded on ram instead), long wait (due to improper cache
strategy)".

An audit (— `docs/audit-2026-10-20-remote-agent-reliability.md`) found four
defects behind those symptoms, each confirmed in the code rather than
suspected:

1. **The workload lease was taken twice and released once.** `in_flight_count`
   settled at 1 permanently after the first chat request, so every later
   IMAGE request saw a conflict, blocked for the full 60 s timeout, and then
   proceeded anyway — killing the llama-server that might have been
   streaming an answer. A deterministic 60 s tax on every image.
2. **The KV-cache type was derived from live free VRAM** and compared against
   the running server's frozen value. Free VRAM swings by ~10 GB as ComfyUI
   takes and releases its checkpoint, so a chat request and an image request
   each decided the 19.5 GB server was misconfigured and reloaded it. The
   cache had become a reload trigger.
3. **A model swap started the replacement while the evicted process was still
   alive and still holding VRAM.** Nothing verified the memory came back, so
   the replacement started with most of its layers on the CPU — the "layers
   got loaded on ram instead" complaint, silently and permanently.
4. **The VRAM reserve was the literal 1800 MB**, calibrated for an 8k context
   at q8_0 when the registry ships `ctx: 32768`. It is now computed from the
   model's real geometry, read out of the GGUF header.

Plus: the agent's stack had no stop path and its servers outlived the agent;
a model that failed to launch killed the worker AT IMPORT (a crash loop);
`is_multi_gpu` was decided by two device indices that might not exist; the
"is ComfyUI generating?" probe failed OPEN, so a timeout evicted a live
generation; the RAM cache was never populated (`prewarm` defaulted to False
and no caller set it) and `/dev/shm` was Docker's default 64 MB with no
`shm_size`; an unrecognised file header was treated as a VALID model; and
the notebook started a SECOND llama-server with the same weights as the
agent's own — two copies of 19.5 GB on a 24 GB card, an OOM by
construction.

The notebook now also **registers its own provider** with the backend instead
of printing credentials for a human to paste, and its dead API path
(`/api/v2/world-vault/llm-config/catalog`, which has never been a route on
any version) is fixed.

Backend suite: 4217 passed, 5 skipped, 0 failed.

### The 2026-10-20 chat-workflow pass — making Laya's decision reach the model

A review of the roleplay subsystem asked one question: does Laya's routing
decision actually reach the model? The answer was **no**, and the gap was
larger than the shape of the system suggested.

**Laya was asked which prompt variant to use, Laya answered, and the answer
was thrown away on the normal chat path.** `resolve_agent` was called without
`variant_slug`, and the character branch never resolved an agent profile at
all — so six seeded variants (three character, three narrator) existed and
none of them could change a prompt a user would see. The autonomous chain
had the mirror-image bug: it put the character variant into
`workflow["character_system_prompt"]`, a key **no engine reads** (the LLM
engines read `workflow["messages"]`, and the character card is already the
first message there). The parameter is now gone rather than left as a no-op,
so the next person cannot make the same mistake.

The character variant is an **overlay**, not a replacement: the seeded
variants read "You are roleplaying as {{char}}. The moment is tense", which
is a mood directive, and replacing the character card with it would throw
the character away. It now goes into the prompt as its own section, after
the character block, through `build_context`.

**The variant axis had no model dimension.** "Many different variations of
system prompts for various LLMs" needs one, and there was none: the only
axis was per-agent, chosen by scene content, and the router picked the model
before the prompt was built. `agent_prompt_variants.model_scope` is now a
nullable model id or role — a scoped variant is only offered to Laya when
the agent it belongs to will actually answer with that model, and it is
applied automatically when it matches. `gate_scope` is the same idea for the
Statekeeper: the schema was already gate-specific, and this is the prompt
half.

**The LLM Studio showed a parallel, not the runtime.** The question list was
a second implementation with hand-written placeholder variant questions whose
only option was `{"default": …}`, and the Director Playground ran a third
list — so an override made in the Studio had no effect on what the
playground ran. All three now go through one builder, and the Studio shows
the real variant slugs. A score question's rubric was also un-overridable:
the override was merged into `options` and the runner reads `rubric`.

**The system-prompt collection could not grow.** It was a fixed set of keys
the code looks up by name — adding one meant editing the config schema,
the validation allow-list and the frontend's copy of the defaults, and there
was no way to remove one. It is now a list, with add, edit and remove.

**Two bugs found while doing it.** `config._split_unset` filtered the
updates with `if isinstance(body, dict)`, so a list-valued section never
reached the validator or the merge — and `update_config` returned success
having written nothing. Every add, edit and remove of a prompt-library entry
was a silent no-op that reported 200. And the event-loop analyser's
`_awaited_names` collected `ast.Await` but not `ast.AsyncFor`, so it could
not see that the LLM call underneath
`async for event in engine.inference(...)` really does suspend on
`await client.post(...)` — it reported eleven world-onboarding routes as
blocking the loop when they do not.

**The Illustrator may now author the scene's parameters** — the sampler,
the resolution, the steps, the LoRA, the hires pass — as a **spec**, not a
raw ComfyUI graph. A raw graph is not safe to accept: there is no node
allow-list anywhere, the workflow dimensions and step counts are unbounded,
and the gallery reads the builder's metadata. The spec is bounded, checked
before the job is created, and falls back to the prompt-text path when the
model's answer is not a spec — so the illustration still happens. It is
opt-in per chat.

**Two numbers were wrong.** The continuation budget was `MAX_CONTINUATIONS
= 4` with the check `continuation_count < 4` — the original plus four
continuations, five generations — while the manifest said "4 repeats". It
now counts attempts, and says so. The "13 Questions" label on the Director
Playground was a third question list's size and is gone; the gate count was
checked and is right (16 in the registry, the other two keys are legacy
aliases).

**One diagnosis in the original review was wrong.** The chain's triage was
reported as asking about "the wrong character's variants". It was not: the
character card has no `slug` column, so the `hasattr` guard always fell
through to the agent slug and the chain did ask the right question. The
constant is now explicit so a Character that grows a `slug` field cannot
change it silently.

### The 2026-10-19 roleplay remediation pass

A review of the roleplay subsystem asked whether the pieces were cohesive
enough. The **data and API layer turned out to be genuinely cohesive** — 21
entities, every one with a route and a live frontend consumer; world
membership normalized under `services/world_ownership.py`; one
`build_context(session, workspace)` serving both chat and story modes; no
`TODO`/`FIXME`/stub marker anywhere in the roleplay layer.

The **agentic pipeline on top of it was half-alive**, and failed silently.
Three defects, each proven by a traceback rather than by reading:

1. **`TypeError` in the Statekeeper's workflow builder.**
   `services/updater_service.py` called `build_llm_workflow()` with
   `temperature=` and `max_output_tokens=`, which its closed keyword-only
   signature does not accept. The `try` in that function starts *after* the
   call, so the error escaped the function and landed in the post-turn hook in
   `services/job_processing.py`, which swallowed it at **DEBUG** level. The
   Updater never ran — and because the same hook aborts at that point, neither
   did memory extraction nor turn chaining. Every chat turn was silently
   losing three of the pipeline's six stages.

2. **`ImportError` in the chain and continuation paths.**
   `services/job_processing.py` imported `render_agent_template` from
   `services.agent_variants`, which does not define it — it lives in
   `services/chat_utils`. The autonomous multi-turn chain and the truncated-
   reply continuation both raised on their first statement.

3. **`GET /api/v2/llm/agents/with-variants` returned HTTP 500.**
   Verified against the running stack, not inferred: the response builder read
   `profile.avatar_path`, and `AgentProfile` had no such column. It was
   copy-pasted from `Character`. Any deployment with agents in the table got a
   500. The existing test could not see it — it guarded with `if body:` and the
   test database has no seeded agents, so the loop that raised never ran.

A fourth defect was a **dead tier**: the Director's Tier 3 generative
fallback read `event == "token"` and `status == "success"`, a dialect **no
engine in the backend emits** (they emit `delta` and `completed`). The tier
always returned `None`, so the cascade fell through to the deterministic
heuristic on every single decision, whatever the provider was doing.

**Why the suite was green.** The post-turn Director block is wrapped in
`except Exception → logger.debug`. That is *why* three defects produced a
passing build. Every one of those log statements is now `logger.warning`, and
`backend_v2/tests/test_chat_pipeline_execution.py` (17 tests) exercises the
stages that had no coverage at all: the Statekeeper's enqueue half, the
autonomous chain, the continuation, the Director's Tier 3, the manifest's
contract with the code, and the agents endpoint with a **seeded** agent.

**What else changed, and why:**

- **The pipeline manifest is authoritative.** `services/chat_pipeline.py` used
  to *describe* a pipeline that lived in `services/job_processing.py`, with
  nothing connecting the two — and the limits disagreed, in four places at
  once (the manifest, the entity column default, the executor's literals, and
  the decision schema's constants). It is now the source of truth: each stage
  names its executor, `next_stages` declares the order, and every limit is
  read from the new leaf module `core/pipeline_limits.py`, which the code
  itself imports. `services/pipeline_runner.py` walks it and
  `services/pipeline_stages.py` holds the executors. `GET /api/v2/llm/pipeline`
  therefore cannot quote a number the pipeline does not enforce.
- **The API surface lost 25 paths and gained one.** The LLM configuration and
  agent routers were mounted **twice**, once under their own prefix and once
  under `/world-vault/*`, giving 23 endpoints two URLs each with no consumer
  of the second copy. `GET /api/v2/llm/traces/{chat_id}` duplicated
  `GET /api/v2/chats/{chat_id}/director-traces`. The three
  `POST`/`PUT`/`DELETE /characters/{id}/expressions` sub-routes were a second
  write path to two columns `PATCH /characters/{id}` already owned, and the
  two disagreed — the renderer had to pick a winner between two shapes of the
  same data at read time. `PATCH` is now the only writer; the GET remains.
  Added: `GET`/`POST /api/v2/agents/{agent_id}/avatar`.
  **This is a breaking change for any consumer of the `/world-vault/llm/*` and
  `/world-vault/agents/*` prefixes.**
- **The gallery code left the World Vault namespace.** `tags.py` (973 lines)
  and `sessions.py` (696) — 24% of `api/routes/world_vault/` — are gallery
  domain, not roleplay. They are now `api/routes/gallery/`. **The URLs are
  unchanged**, so the frontend and every OpenAPI consumer see exactly what
  they saw before.
- **TTS and image no longer share LoadBalancer state.** They were both
  `state_id=1`, so their `provider_failures` and round-robin index were shared
  and a TTS outage could trip the image circuit breaker for a provider that
  serves both. TTS is now `state_id=3`, like LLM's `state_id=2`. No migration:
  `LoadBalancerState` rows are created on demand.
- **The Updater reads its agent profile.** Its system prompt was a hardcoded
  string, so editing the `updater` agent in the LLM Studio changed nothing.
  It now resolves the profile and its active variant, the way every other
  agent type already worked. The "output valid JSON only" instruction is
  appended after the agent's own text, because it is the one requirement a
  prompt rewrite must not be able to break — and the JSON-extraction
  temperature and token ceiling override the agent's own sampling, so a
  variant written for prose cannot make the extractor write prose.
- **The agent slug is editable again.** The Agent Studio's slug field is
  enabled for anything that is not a built-in, and it sends the slug on
  save — but `AgentProfileUpdate` never declared it, so the backend dropped
  it silently and the user's new slug vanished on reload. It is now declared
  and applied, with the same normalisation and collision check the create
  route uses. A built-in agent's slug is refused rather than changed,
  because a built-in is looked up *by* its slug. The request models also
  set `extra="forbid"` now, so a misspelled field is a 422 rather than a
  silent drop — which is only safe because the field the Studio actually
  sends is declared.
- **Chat and story can point at each other.** `Chat.story_id` and
  `Story.chat_id` are nullable provenance columns — two columns, not a link
  table, because each direction is genuinely one-way and a pair is never
  linked both ways.
- **The roleplay UI shows worker health.** `GET /api/v2/llm/providers/health`
  was computed by the backend and requested by nothing, so a user whose only
  LLM provider was down saw a failed job and nothing else. There is now a
  banner and a card on the roleplay front door, and a link to the LLM Studio
  from there. The chat panel also shows **which agent Laya routed the reply
  to** — `context_trace["selected_agent"]` was written by the backend and read
  by nobody — and reads the gate registry from
  `GET /api/v2/llm/director/gates` instead of a hand-copied list.
- **Three dead internal links are fixed.** `/stories?storyId=` and
  `/chats?chatId=` were not routes; `/worlds/${id}` was a route with no
  `:worldId` parameter. A character could not be reached from its own chats
  anywhere, so `GET /api/v2/chats` grew a `character_id` filter and the
  character panel lists its conversations.

**Two of the twelve pre-existing test failures were not what they looked
like.** The eleven world-onboarding routes reported as blocking the event
loop were a **false positive in the analyser**: it collected `ast.Await` but
not `ast.AsyncFor`, so it could not see that the LLM call underneath
(`async for event in engine.inference(...)`, which really does suspend on
`await client.post(...)`) was a genuine suspension. Converting eleven routes
to plain `def` on the strength of that would have changed their concurrency
behaviour for no reason; the analyser was fixed instead, and it still flags
all 23 routes that are registered as known debt. The other was a genuine
second writer for `world_id` in `world_onboarding_service.py`, which now goes
through `link_to_world` like every other member.

### The 2026-10-09 consolidation-cleanup pass

`9a91e6f2` ("remove containerized provider path") was a correct change that
broke both suites, because it deleted code without going through its consumers.
This pass started by measuring that rather than reading for it, then fixed what
the measurement showed.

**Both suites were red at HEAD.** Backend 4 failed / 5 errored (3160 passed was
the ceiling the broken tests allowed); frontend 2 failed (1770 passed).

What was actually broken, in the order it cost the most:

1. **The bootstrap test guarded a module that no longer exists.**
   `test_app_boot_smoke.py` patched `infrastructure.deps._global_container_manager`,
   deleted with the container manager. All 5 boot tests errored, so the lifespan
   — every startup phase, the worker pool, the scheduler registrations, the
   shutdown requeue — had no coverage at all while 3142 tests passed around it.

2. **The env contract had 55 actions wired to nothing and 6 knobs documented
   nowhere.** `.env.example` and `.env.example.provider.engines` still announced
   the container runtime. The fail-open direction was harmless; the fail-closed
   direction was six live settings with no documentation, including
   `ENABLE_MEMORY_SNAPSHOT`.

3. **`docker-compose.yml` still declared six provider services with
   `context: ./provider_containers` — a deleted directory.** `--profile
   providers build` failed outright, while `AGENTS.md` and this file both said
   the profile was removed.

4. **A 703-line module and its nine routes were production-dead.**
   `remote_agent/provider_core/reconciliation.py` had one surviving symbol,
   `determine_download_token`, used by the agent's own download path. Nine
   backend routes served it; none had a caller.

**The correctness bugs behind the dead code:**

- `enable_memory_snapshot` was resolved **twice**, and the two copies had
  already drifted. Worse, `job_runner` read the provider row and passed an
  explicit `bool`, which made `ModalEngine`'s own resolution unreachable — so
  `ENABLE_MEMORY_SNAPSHOT` was a documented setting nothing could read. Now
  there is one helper (`resolve_enable_memory_snapshot`) and the dispatcher
  passes `None` to hand the decision to the engine that owns it.
- `DiagnosticsTab` destructured only `{ data, isLoading }` from its own
  `useQuery`, so a **failed probe rendered a green "All diagnostics clear"
  panel** next to "Credential Ready: Missing" — an actionable lie. The
  `queryErrorInvariants` guard could not see it, because its emptiness shapes
  (`No ... found`) do not match a health claim; its vocabulary now includes
  `All ... clear`, which catches the file when the fix is reverted.
- `Providers.jsx` rendered a failed fetch as **"No providers configured"** with
  a working CTA, because `useProvidersPageData` published `providers: []` and
  no error channel. The hook now publishes `isError`/`error` and the page
  renders `QueryErrorState`.
- `rollback_chat` was the last `async def` route doing synchronous SQLModel
  work on the event loop, including a bulk DELETE over up to 5000 messages.
  Its sync prologue now runs in `asyncio.to_thread`, and the cancel is ordered
  *after* the delete so a reply that lands in between finds nothing to append
  to.
- `RuntimeTab` read `provider.config?.app_name`, `provider.config?.comfy_url`
  and `runtime.last_seen_at` — three keys the status card never emits. The
  ComfyUI root now reaches `deploy_config` via `LEGACY_DEPLOY_CONFIG_FIELDS`.
- `DirectComfyEngine.delete_file` used `except (RuntimeError, Exception) as
  exc:` — a **one-element tuple**, since `RuntimeError` is a subclass of
  `Exception` and the second entry only ever matches the exact class. The
  `isinstance` re-check inside it then re-raised, and the catch-all after it
  swallowed both. Against a 404 from the agent the method answered `False`,
  identical to "the file was already gone". Both paths now re-raise.
- `translate_legacy_image_update` applied a `value <= 1` fraction heuristic and
  then **declared `value_unit="percent"`**. A canonical percent producer's
  `value == 1` — one percent done, the first step of every image job — came out
  as 100, in the one number the user watches. The heuristic is gone; a real
  fraction is declared on the wire, and the reducer honours it.
- The prompt-cache key used `string_agg` with **no ORDER BY**, so the same
  table produced two different hashes depending on the query plan, and the
  cache missed on unchanged data — the entire 1.4s rebuild paid for a key that
  was read once.
- No `search`/`q`/`tags` parameter had a `max_length`, so a 1 MB ILIKE term
  ran against `metadata_` (~4 KB of ComfyUI workflow per row) unauthenticated.
  Every search parameter is now bounded, plus the three list routes that had no
  page ceiling at all.

**The dead contracts that were not dead:**

- `MODEL_SYNC_*` was a four-member event family with four frontend toasts and
  **one producer: a route nothing called**. Rather than delete a UI that already
  exists, `in_process_reconciliation` now emits all four as it works — the
  `download.*` failure mode that the project removed a week earlier, one level
  up. `progress` is the fraction of the *queue*, labelled `progress_scope:
  "batch"`, because `download_file` has no per-byte callback and a per-file
  fraction is not observable.

**Verification.** Every fix above has a test that fails when the fix is
reverted — reverted and confirmed, not assumed. The guard tests that were
themselves blind (the `provider_containers` root that silently narrowed what
`test_env_contracts` could see; the `refetchPage` skip; the empty-state
vocabulary that could not read a health claim) are fixed first, because a guard
that cannot see the code it guards is the same failure as no guard.

### The 2026-10-10 delta pass

The 10-08 consolidation was correct and left the tree with dead code, duplicated
copies of deleted constants, and several silently-dead subsystems. Six read-only
sub-agents swept disjoint scopes, and every candidate was reproduced by hand
before it was accepted — five candidates were disproved that way and are
recorded in the audit's §3 so they are not re-reported.

**Fixed** (full register with `file:line` in `docs/audit-2026-10-10.md`):

- **Failover was unreachable for pinned jobs** (`load_balancer.get_next_provider`
  answered `None` when the pinned provider was already exhausted, which
  `job_runner.select_next_provider` reads as "all providers failed").
- **The upload cap inverted** — `PROVIDER_UPLOAD_MAX_BYTES=0`, the documented way
  to *disable* the cap, made every upload fail. Unified into one predicate,
  `encoded_upload_over_cap`, in `services/engines/base.py`.
- **A timeout was reported as a user cancellation** in the Anthropic and Google
  LLM engines: their `except asyncio.CancelledError` swallowed the timeout
  carrier instead of re-raising.
- **Nested model files never matched**, so they were re-marked pending and
  reported as orphans on every reconcile tick.
- **The model-availability cache had no invalidation path at all** — its
  `clear_available_models_cache` had zero production callers.
- **Routes accepted impossible input**: negative `limit`s, an unbounded search
  term, and a tag vocabulary that returned `limit + 1` rows.
- **Request bodies with fields the handlers ignored** (`scenarios`,
  `characters`, `stories/parse`), and a dead `modal.vllm` config block.
- **Two test guards that could not fail**: the LIKE-escaping sweep's attribute
  set was computed as `".like(".lstrip(".")` → `"like("`, so it collected zero
  calls and passed vacuously against every unescaped pattern in the tree; and
  the `job_queue` restart-reset statement was never executed under SQLite.
- **Runtime drift**: six import-time `int()`/`float()` env reads that crash the
  process on a typo, a silently-truncated Modal stream on a short read, a leaked
  Modal client on `close()`, an unbounded agent stream, and a hardcoded 64 MiB
  TTS cap shadowing the documented `PROVIDER_GET_FILE_MAX_BYTES`.
- **Frontend query keys**: a missing invalidation that left the old default
  wearing its badge, per-second polling on top of a live WebSocket, a settings
  toggle that the global realtime handler ignored, and a bare `['gallery']`
  prefix invalidation that walked every loaded page.

### The 2026-10-10 in-process-engine pass

A second pass, scoped to the compute tier `9a91e6f2` made the only execution path
(`services/engines/`, plus `engine_factory`, `load_balancer`,
`in_process_reconciliation`, `job_runner`, `job_queue`, `api/lifecycle`). See
`docs/audit-2026-10-10b.md` for the full register.

- **Startup re-generated paid jobs on every restart.** The recovery phases ran in
  the order the call site's own comment forbade: the claim sweep includes
  POST_PROCESSING in `ACTIVE_JOB_STATUSES`, so it reset mid-finalization rows to
  PENDING before the recovery pass that looks for exactly those rows. Reordered
  into a named `_run_job_recovery_phase()`.
- **A cancelled Direct-ComfyUI job was finalised as a success.** ComfyUI answers
  `/interrupt` with the same `executing {node: null}` frame a finished prompt
  emits, so the loop broke as "Completed" and fell through to `completed` with the
  artifacts persisted.
- **The no-agent Direct rig's whole model tree looked orphaned.** Its `list_models`
  emitted paths without the `models/` prefix every consumer keys on, so
  discovery matched nothing and every file counted as an orphan.
- **Anthropic rejected any history with parallel tool calls** — consecutive
  same-role turns are a permanent (non-retryable) 400, which is the agentic
  roleplay path.
- **Engine clients were closed never correctly.** `clear_engine_cache()` had no
  production caller, `invalidate_engine` closed a client an in-flight job was
  streaming on, and the close task was dropped without a reference.
- **A cancel that did not reach the provider.** `cancel_job` set a flag and called
  a no-op `_on_cancel` on every engine but DirectComfy, and the flag is checked
  *between* stream items — so a quiet provider (a long denoise, a model still
  loading, an LLM thinking before its first token) kept generating, and billing,
  until the next frame or the caller's timeout. One abort registry on the base
  class now: each engine's loop publishes its interrupt (a fetcher-task cancel for
  the four task engines, `response.aclose` for the three SSE engines, which
  terminates the HTTP request — the only lever that actually stops an upstream
  generation), `cancel_job` awaits it, and a test drives each engine's loop to
  assert it registered. ModalTTS moved to the fetcher shape the other Modal
  engines already used, because that is what gave it a lever at all.

**Open after the pass** — the audit's §2. Its top item is
`remote_agent/provider_core/downloads.py:899`, which puts the CivitAI token in
the URL query string where the rest of the flow uses `Authorization: Bearer`;
§3 records the six candidates that did not survive verification, including two
that pointed at files the 10-08 consolidation had already deleted.

### The second 2026-10-04 pass

Same method again — four parallel read-only passes (backend, frontend,
provider/worker tier, cross-seam wiring), every candidate reproduced by hand
before it was accepted, then fixed in batches with a revert-verified test each.
Baselines before: backend 2988 + 1 fail, frontend 1467 + 1 fail, providers 844.
After: **3054 / 1604 / 1012**, and both pre-existing failures are fixed. Full
register with `file:line`: `docs/audit-2026-10-04b.md`.

Three things in it outrank the rest:

- **The backend CI job had been red on all five runs of the previous four days.**
  Not a flaky test: `tests/conftest.py` probed every module in `sys.modules` with
  `getattr(module, "get_session_sync", None)`, and `transformers` has a PEP 562
  `__getattr__` that resolves a miss by importing the submodule it names — reaching
  `torchvision`, which is not in `requirements.txt`. 1355 of 2832 tests errored in
  CI and all of them passed locally. **Every "verified green" number in the passes
  above was a local observation.**
- **The frontend re-published the whole API on `0.0.0.0:5174`.** It is a reverse
  proxy to the backend, so publishing it publishes the unauthenticated API —
  measured `curl http://192.168.1.28:5174/api/ready → 200`. Now bound to
  loopback plus an optional named address; `preflight.sh` fails on a wildcard.
  The backend itself publishes `127.0.0.1:8002` and
  `${COMFY_BACKEND_BIND:-100.150.0.4}:8002` — named addresses, never `0.0.0.0`.
- **Five declared indexes were never created on a fresh install**, including the
  HNSW vector index on `character_memories(embedding)` — so semantic memory search
  had no index at all on any new deployment. `create_all` cannot emit an
  operator-class index, and the migration that would have created it early-returns
  because `create_all` made the table first.

The recurring shape was, again, **a control that renders, persists and reports
success while the value goes nowhere** — a failed gallery fetch rendered as "No
images yet" with a generate button, four settings sections are served and stored
but rejected by their own `PUT`, and `jobs_cleanup`'s three controls reach an
endpoint that does nothing. Five guard tests were also found that **could not
fail**, each because a hand-maintained list or a regex that matches nothing had
drifted from the thing it constrains.

### The 2026-10-04 pass

Same method again — five parallel read-only passes (backend, frontend,
provider/worker tier, cross-seam wiring, and a live browser sweep), plus direct
measurement of the live database, the live API, the production CSS bundle and
`preflight.sh`. Baselines before: backend 2953, frontend 1464, providers 833.
After: **2989 / 1468 / 844**. Every fix is revert-verified — each new test was
confirmed to fail when its fix was reverted. Full register with `file:line`:
`docs/audit-2026-10-04.md`.

Two of these are worth reading the audit for, because both were invisible to a
green suite and one was invisible to a *desktop browser*:

- **The whole mobile stylesheet was applying at desktop width.** A stray `}`
  closed `@media (max-width: 768px)` eighty lines early, so 55 phone-only rule
  groups shipped top-level. Measured on the running stack at 1440px: every
  slider was 44px with `touch-action: none` (so the page could not be scrolled by
  dragging a slider), every `.max-w-6xl/7xl` collapsed to `max-width: 100%`, and
  every glass panel had lost its blur. Introduced by `295f8888` in the previous
  pass, while fixing a different finding. **All 15** pre-existing
  `mobileLayoutInvariants` tests passed against it, because they regex the
  stylesheet and never check block membership.
- **An unauthenticated `GET /api/thumbnail/{size}/{filename}` soft-deleted
  unrelated gallery rows.** The basename match had no path-separator boundary, so
  a request for `abc.png` also matched `notabc.png` and `xabc.png`. The
  function had no tests at all.

Also fixed: the e2e CI job could not have been green (14 call sites requested
routes that do not exist, because the harness prefixed `/api/v2` onto
unversioned paths — and `docs/api.md` documented the resulting typo and invented
a reason for it); every artifact fetch from a `remote_comfy` provider raised
`AttributeError`; `REMOTE_AGENT_ALLOW_INSECURE` bound an unauthenticated *write*
API to `0.0.0.0` because `agentctl.sh` exported an empty `HOST` that the clamp
read as loopback; TTS cancellation was dead (`/cancel-job` returned 500); LLM and
TTS providers sat at "reconciling" for three hours per trigger; a TTS provider's
card claimed to track 525 image models; the 9 mobile Playwright tests ran in **no**
CI workflow; and `docs/api.md` is now generated from `app.openapi()` and
drift-checked in both directions.

### The 2026-10-03b pass

Same method as its predecessor — five parallel read-only passes, one of which
drove all 35 routes in a real browser against the running stack. Baselines
before: backend 2824, frontend 1352, providers 793. After: **2953 / 1464 / 833**.
19 revert checks; every new invariant test was confirmed to fail when its fix
was reverted.

The consolidation was again **not** the problem and there were again **no
stubs**. What is real is one recurring shape: *a control that renders, persists
and reports success while the value goes nowhere.*

- **A failed chat reply left a permanent "Ilse Vondt is thinking…".** The
  submitter learns its job id from the HTTP response; the terminal WebSocket
  event arrives first. Measured: `job.failed` at t=6174 ms, the POST returning
  200 at t=6230 ms. The failure was handled against an empty store, then the
  response inserted a placeholder whose only removers had already fired. All
  seven insertion sites share the shape; the fix is in the store, so a new
  terminal handler cannot forget it.
- **`/advanced` could not build a workflow at all.** It asked whichever provider
  sorted first — `direct_url`, registered `enabled=false`. The proxy returned
  HTTP **200 carrying an error body**, so the hook cached the error object as
  the node definitions for 24 hours and rendered a palette with one category
  named `unknown`.
- **The event-loop invariant test was blind.** Its search path contained
  `backend_v2/api/infrastructure`, which does not exist, so
  `backend_v2/infrastructure/` and `core/` were never indexed — and the resolver
  scored every unresolvable await as a pass. A guard that cannot see the code is
  not a guard. Six newly-visible offenders converted; `jobs.py:151 create_job`
  deleted from the register because it is genuinely fixed.
- **One invisible-but-tappable *destructive* control** survived the previous
  pass's touch-device rescue: `group-hover/card` was missing from a
  hand-maintained list, so the ControlNet delete button was laid out,
  hit-testable and invisible on touch. The list is now generated from the source
  by a test that also fails on names nothing uses.
- **A `<select>` with three vocabularies rendered blank.** `ui.defaultViewMode`
  was both the live gallery view and the persisted default, and `timeline` and
  `session` were writable with no matching `<option>`.
- **`generatorStore.autoApplyModelSettings` was permanently `true` with no
  control anywhere** — the setter, field and test all existed; only the toggle
  was missing. Same shape as the `models.autoRemoveDownloads` switch deleted
  hours earlier.
- **A transient embedding failure destroyed a good vector** with NULL, and
  **a Docker failure reported "stopped"** — both now leave state alone and
  signal a degraded result.
- **`reconciliation.failed` was emitted and handled nowhere**;
  **`model.sync_progress` was emitted on every download heartbeat and dropped**;
  and the entire **`download.*` event family** had zero producers and zero
  subscribers on both sides, so it was removed rather than left looking like
  push-based progress already works. One invariant test now asks all three
  questions of every backend `EventType`.
- **`preflight.sh`'s provider check was dead** — it curled the host port the
  previous pass removed, and its fallback was `note` not `bad`. It now reads
  from inside the container and fires: *"5 of 6 registered providers are
  switched off."*
- **`docs/deployment.md` told the operator to bind 8002 to `0.0.0.0`** — advice
  that would have reopened the exact hole the previous pass closed.
- `/providers` route closure **−86 kB gzip** (a charting library replaced with an
  8-line SVG for a sparkline), and `socket.io-client` moved out of the eager
  entry chunk. The charting library itself is still there, correctly lazy: it is
  `vendor-charts`, 361.61 kB raw / 107.16 kB gzip, and absent from
  `dist/index.html`'s eager set.

Four claims of the previous audit did not survive re-measurement and are
corrected in its §6 — including that its `job_service.py` naive-datetime example
was the one site that was **correct**.

`docs/audit-2026-10-03b.md` has the full register for that pass, and
`docs/audit-2026-10-04b.md` for the most recent one; both carry `file:line` on
every item.

### The 2026-10-03 pass

The headline is that **the consolidation was not the problem and there were no
stubs**. Grep for `TODO`/`FIXME`/`onClick={() => {}}`/`console.log`/`alert`
across all non-test frontend source returns zero hits, and every route in the
intended roleplay information architecture exists and is wired. What was real:

- **Seven pages — including `/roleplay`, the front door — rendered a failed fetch
  as a genuinely empty vault.** `/characters` showed *"You haven't created any
  characters yet. **Create one** to start roleplaying."* with a working Create
  button, next to a vault holding three characters; clicking it makes a duplicate.
  Confirmed by force-500 on the live stack. Fixed with a shared
  `QueryState` primitive, verified 8/8 live, and pinned by an invariant test that
  a page shipping empty-state copy must handle the error state.
- **`models.autoRemoveDownloads` was a labelled switch that could not do
  anything** — four references, all of them the UI and the store default, zero
  readers, backend included. Deleted, and pinned by a test that walks every
  settings key and fails on any key nothing reads.
- **Seven routes took a SQLModel table class as their request body**, which made
  the primary key client-writable and turned a missing required field into a
  **500** instead of a 422 (verified on the live stack for all five that lacked
  a hand guard). Fixed with seven `extra="forbid"` DTOs and pinned by a
  structural test over `api/routes`.
- **iOS auto-zoom on 21 fields.** Every generator's prompt box computed at 14px,
  so Safari zoomed the viewport on focus and never zoomed back — the first thing
  anyone does on this app. The existing 44px tap-target pass could not have
  caught it: the fix had to be unlayered, because `text-sm` lives in
  `@layer utilities` and beats `@layer base`.
- **`image_processing.embed_metadata_in_png`** was an editable toggle in Settings
  that the PNG writer never consulted, and **`ipAdapters[].stopAt`** was a live
  slider whose value pydantic discarded — both success toasts, no behaviour.
- **A malformed provider *success* payload was declared retryable**, costing up
  to four paid inferences per provider plus one per failover to fail with the
  same error.
- **Five of six providers are registered disabled**, so the load balancer has
  one, the free local GPU path is off, the local LLM is off, and five Modal apps
  are billed as idle. See §1a — this one is yours to decide.
- **Six control groups were invisible *and still swallowed taps*** on any touch
  device at ≥640px. The `@media (hover: none)` rescue in `index.css` listed only
  the unprefixed `.opacity-0.group-hover:opacity-100`, and six sites emit the
  `sm:`-prefixed pair — different class names, so the rule never matched. They
  computed to `opacity: 0; pointer-events: auto`, and a real CDP touch tap in a
  gallery thumbnail's corner was delivered to the invisible favourite button
  instead of opening the image.
- **`/story` collapsed its "story beat" input to 0px at 640–900px** (34px measured,
  7 sibling overlaps, 9 controls off-screen; a tap 125px outside the viewport
  delivered no event). **`/advanced` had a 54px graph canvas at 360px** against
  240px nodes. **`/statistics` had 17px of its active tab permanently
  off-screen** behind a mobile gutter that double-counted one `Layout.jsx`
  already provides. All three measured before and after.
- **iOS auto-zoomed the viewport on 21 fields** under 16px — the prompt box on
  every generator. Plus **~40 WCAG AA contrast failures across 15 routes** from
  one shared hex, and no skip link on any of the 25 routes, and 24 controls with
  a `placeholder` as their only accessible name (the previous audit's "4" was a
  viewport-scope artifact, not a fix).

Re-measured across 25 routes at 360/390/768 after the fixes: **0 dead controls,
0 invisible-but-tappable controls, 0 text inputs under 16px, 0 sibling
overlaps.** What is left is in §1b of the audit — the biggest is the 81px
transient occlusion of the aspect-ratio presets by the fixed action bar on
`/generate`, which is real but recoverable by scrolling.

`docs/audit-2026-10-03.md` has the full register with `file:line` on every item,
the measured numbers, and the corrections to the previous audit — including two
claims from this pass's own sub-agents that did not survive verification.

### The 2026-09-26 hardening pass

The 2026-09-26 hardening pass (24 commits, `83ad704..97271ba`, branched from
`ae3a010`) fixed the classes of bug that make a system untrustworthy. The
notable ones:

- **nginx cached the backend's IP forever**, so any backend restart meant 502 on
  every API route until the frontend was also restarted. Now re-resolved per
  request, and verified by moving the backend to a new IP with the frontend
  untouched.
- **Provider auth failed open** when the shared provider token was empty, which
  was the shipped default — leaving `/inference` and `/deploy` (which shells
  out to `modal deploy`) open. Now fails closed with 503.

  This was two variables (`PROVIDER_WORKER_TOKEN` for backend → container,
  `COMFY_DISCOVERY_TOKEN` for container → backend) and is now one,
  `COMFY_PROVIDER_TOKEN`, used in both directions as `X-Provider-Token`. Both
  ends still fail closed. Having two is what caused a real outage on
  2026-10-02: the discovery one was empty while the management one was set, so
  every provider failed to register and the only symptom was
  `discovery_token_not_configured` in the container logs. `scripts/preflight.sh`
  now reports it before `compose up`.
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

Items 1-6 of the previous list were fixed — see §1b of the follow-up.

### 1a. Five of six providers are disabled and the flag that did it was not a security control

> **Resolved 2026-10-03, later the same day.** `COMFY_DISCOVERY_ALLOW_NEW_PROVIDERS`
> is **deleted**. It was gone from the code, `.env.example` and
> `scripts/preflight.sh`, and — found still live on 2026-10-03, injected on every
> `up` — also had to come out of `docker-compose.yml:106`. It survives nowhere
> now. A new provider registers enabled. All six providers share one bearer
> token, so the token is the entire boundary and cannot tell an impostor from
> `modal-zetsuke`; the flag only ever set `enabled` on *new* rows and was never
> consulted on the update path, which overwrites `discovery_url`
> unconditionally — and dispatch prefers `discovery_url`. So it protected nothing
> the token did not already protect, and a default of `0` only produced a silent
> capacity and billing surprise.
>
> What remains true: `enabled` is sticky by design, so the five registered
> providers each need a one-time toggle on the Providers page. `preflight.sh` now
> reports that count unconditionally.
>
> **The real hole is closed.** The backend published `8002:8002` on `0.0.0.0`
> with no authentication, so `PATCH /api/v2/providers/{id}` was open to anyone on
> the network. It now publishes **named addresses only** — `127.0.0.1:8002` and
> `${COMFY_BACKEND_BIND:-100.150.0.4}:8002`, never a wildcard — so the hole is
> closed while LAN/VPN reachability survives. Traefik reaches it over the
> `proxy` network, verified from inside the Traefik container. Measured on the
> host's LAN IP: **200 → 000** on `0.0.0.0`, **200** on the named addresses.
> Reachability is now governed by the NetBird ACL on the reverse proxy. See the
> audit for the two compose traps found on the way.

Every registered provider reports discovered, connected and healthy, heartbeating
within the same second. Five are `enabled=false`, which is a per-provider field
the Providers page owns rather than an environment variable:
`/api/v2/providers/load-balancer/stats` reports `total_providers: 1`.

Consequences: no failover for image jobs; `direct_url` (the free local GPU path)
is off; `llm-local` is off, so every chat turn bills a remote model while five
Modal apps sit idle and are billed for it.

**Nothing in the environment will bring them back.** The discovery *update*
branch deliberately never re-asserts `enabled`, because an operator who turned a
provider off in the UI means it. Each provider needs the Providers-page toggle or
`PATCH /api/v2/providers/{id} {"enabled": true}`.

What was fixed is the invisibility: `scripts/preflight.sh` reports how many
registered providers it is currently keeping off the balancer. **That check was
dead until 2026-10-03** — it curled `http://localhost:8002`, which the removal
of the host port turned into a permanent `000`, and the unreachable case was a
`note`, so preflight exited 0 while saying nothing. It now reads the list from
inside the container and an unreadable one is a failure. Your `.env` was
deliberately left alone — this is a capacity and billing decision, not a bug fix.

### 1b. The rest

0. **The embedding stack has no CI coverage.** `sentence-transformers` is in
   `requirements.txt`, `torchvision` is not, and the local venv cannot import
   `transformers` at all. So the paths that load the embedding model, build the
   vector index and serve semantic memory search are never executed by any suite —
   locally or in CI. This is the same gap that hid the conftest bug in the entry
   above for four days, and it is the first thing worth fixing next.

1. **The app has no authentication.** Deliberate — `DEMO_GAPS_PLAN.md` records
   the decision as out of scope for a local single-user studio — but it means
   every destructive endpoint, including the unauthenticated published-story
   export, is reachable by anyone who can reach the API. Do not expose this
   to a network you do not control. **The shipped compose file does not:** the
   backend publishes `127.0.0.1:8002` and
   `${COMFY_BACKEND_BIND:-100.150.0.4}:8002` — named addresses, never `0.0.0.0`.
   Traefik reaches it on the external `proxy` Docker network through the
   `comfyui-api` router on `comfy-backend.lan.thenaha.my.id`, and reachability
   is governed by the
   NetBird ACL on the reverse proxy. `docs/deployment.md` has the router table
   and `docs/api.md` the base-URL options. The dev override restricts `db` to
   `127.0.0.1`, which makes the backend's omission look deliberate too.
   **The frontend is now held to the same boundary** — it proxies `/api`, so
   publishing it published the API; see the second 2026-10-04 pass above.
   **This stopped being theoretical on 2026-10-01:** an audit sub-agent's
   in-process probe called `DELETE /api/jobs` and deleted all 154 rows of job
   history. Assets (16,677 rows, 16,342 PNGs) were verified intact, because
   `assets.job_id` is an un-FK'd soft reference nothing joins on — but the loss
   is real and it happened from an ordinary probe. Nothing destructive should be
   pointed at this stack until auth exists. **A second instance of the same class
   was found on 2026-10-03:** `GET /published/{token}/export` resolved the same
   public token as the narrowed `GET /published/{token}` and then returned the
   *unfiltered* owner export, so an unauthenticated caller got every internal id,
   every chapter's private `beats` outline and the whole lorebook list. Both
   routes now build the same projection, and the export cannot become wider than
   the read without a test failing.
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
   `Modal` is built on `ModalOverlay`; **16 of 33 overlay declarations** still
   hand-roll their backdrop and sit outside the `useEscapeKey` registry, so
   stacked dialogs close together — the exact defect `common/Modal.jsx:24-27`
   records. Mechanical, but it needs a per-route screenshot pass, and
   `ModalOverlay` still has no focus trap (⚠️ do not touch its `role`: a previous
   attempt broke 8 tests and was reverted). A one-line `@media (hover: none)`
   rule already makes all 30 hover-revealed action rows reachable on touch.
6. **The embedding model still loads inside the reindex request** — seconds on
   first call. Moving it to startup needs `services/embedding_service.py`. (The
   two *inference* call sites are now off the event loop; this one is not.)
7. ~~**The two `worker.py` bootstraps share ~35 lines.**~~ **Fixed** —
   `provider_core/worker_bootstrap.py` exists and both entrypoints import from
   it. Residual duplication is ~35 lines of env-parsing preamble in each, plus
   the **seven** "method not supported" tails and the **three** hand-rolled SSE
   parsers on the LLM side. The tails are four in
   `image_worker/engines/direct_url/client.py` (download_model :283, delete_model
   :304, delete_file :342, upload_file :349 — the first is a 501, the rest 405)
   and three in `llm_worker/engines/openai_compat/client.py` (get_file :305,
   delete_file :309, upload_file :313; all 404). The SSE parsers are now **one**
   function, `provider_core/sse.py:iter_sse_data`, which also owns the
   cancellation probe the three copies each re-implemented; each engine keeps only
   its payload→TaskEvent mapping. That consolidation fixed a live bug: all three
   copies read `line.startswith("data: ")` and `line[6:]`, and SSE permits
   `data:{...}` with no space, so a frame in that form was dropped whole,
   mid-stream, with no error — a silently truncated answer.
8. **33 inline empty states against one shared `EmptyState`.** The shared
   component has no error slot, which is *why* all 33 hand-rolled ones had to
   decide where errors go — and all 33 chose nowhere, which is how seven pages
   ended up reporting an outage as an empty vault. Adding an error slot and
   migrating them is the largest line-count reduction available and structurally
   prevents that class from recurring. This is the **first** thing to do next.
9. **29 more routes block the event loop**, the same shape as the four converted
   on 2026-10-03, now enumerated in `SYNC_CHAINED` in
   `tests/test_event_loop_invariant.py` with each one's service method named. A
   new test now resolves awaited callees across modules and fails on any *new*
   offender, so the list can only shrink deliberately.
10. **65 backend routes have no frontend caller**, four of them returning the same
    1.5 MB model dump (`/api/v2/models/all`,
    `/api/v2/providers/model-cache`, `/api/v2/gallery`) in four separate
    implementations. Removing them is an API-surface decision, not a cleanup.

### Added by the 2026-10-20 image-generation audit

The full audit covered the Simple Generator and its Enhancements panel, the
Advanced Generator, Batch/Img2Img/Inpaint, the Gallery, the job system, and
the model/provider catalogue. The pass above fixed the parts that cost
money, killed live work, or made a request fail for a reason the user could
not see. These are the ones it found and did NOT fix, in the order they are
worth doing:

1. **The capability gate is build-time only.** The builder now skips what the
   target provider cannot do and says so in the job's metadata — but there is
   no DISPATCH-time filter, so a graph that reaches the provider with a node
   it lacks still fails with "node type not found" rather than being pruned.
   The prune is strictly better than the failure, but it changes the output,
   so it needs a home of its own: one "prepare this workflow for this
   provider" step, with what it removed recorded in the job's diagnostics.

2. **There is no provider picker.** The Enhancements panel asks about the
   first ENABLED image provider, which is the target in every current
   deployment — `load-balancer/stats` reports `total_providers: 1`, five of
   six being disabled. With two enabled providers the panel would describe
   one and the balancer might run the other. The plumbing is already there:
   `preferred_provider_id` is honoured end to end by the backend
   (`job_submission_service` → the job's metadata → the load balancer), and
   the request model has the field. What is missing is the UI, and the
   Advanced Generator's silent `providers.filter(p => p.enabled)[0]` for its
   `object_info` should become that same selection.

3. **The gallery drops a completed job.** `dashboardItems.js` returns
   without pushing when a job is completed but not yet indexed, and the
   filter then excludes it because it is `completed` — so a job that
   finished between two polls vanishes from the gallery instead of
   appearing. The desktop polling gap is the same shape: with the socket
   down, the active-jobs list is never polled on desktop.

4. **`file.path` does not exist in the `/api/files` projection**, so the
   Provider Status list always filters the LLM providers out
   (`ModelDetailsModal.jsx`). The projection is in `api/routes/files.py`.

5. **The badge and the submit-time gate still answer different questions.**
   The badge uses the model-level aggregate and the gate uses the exact
   `(directory, filename)` pair, and they disagree about the same row. One
   function — "can this provider run this exact file, right now" — used by
   both, would settle it.

6. **There is no integrity verification anywhere.** The `.sha256` sidecar IS
   read (`image_worker/comfy/models_utils.py`), but it holds a locally
   computed hash that is never compared to the upstream one, and
   `ProviderVersionStatus.verified_at` has zero writers. The download gate
   is size plus magic bytes. `ModelFile.hash_sha256` also conflates the
   upstream expected hash with the provider's local one in a single column.

7. **`jobs_cleanup` has zero consumers**, so the `jobs` table grows without
   bound, and **`get_pending_downloads` has no per-provider assignment
   filter**, so every provider converges on the whole catalogue. Coherent as
   a policy, but undocumented.

8. **`/api/v2/models/catalog` returns the LLM registry, not models.** An
   API-surface decision rather than a cleanup.

### Added by the 2026-10-21 consolidation sweep

9. **The `charGen*` prompts are never seeded from the server.** Eight
   server-owned generation prompts are mirrored into the generator settings
   store (`frontend_v2/src/store/settingsStore.js`) and exposed on the
   Characters page, but nothing reads them from `config.json`, so editing them
   there has no effect and the Settings page reports success while the value
   goes nowhere. An inert control.
10. **Three orphaned scripts.** `backend_v2/scripts/{backfill_download_urls,
    benchmark_statistics,clean_preview_cache}.py` (286 lines) are referenced
    from nothing but a `.kilo/plans` file. Safe to delete once that plan file
    is retired.

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

The story editor was shipping all 594 of `refractor`'s syntax grammars to render
prose; `refractor` is now absent from the `StorySandbox` chunk and
`StorySandbox` is at 242.36 kB raw / 70.89 kB gzip.

Current build, 2026-10-05 (re-measured, because the figures in the previous
revision of this paragraph were wrong in both directions):

| chunk | raw | gzip |
|---|---|---|
| `vendor-charts` (recharts, lazy) | 361.61 kB | 107.16 kB |
| `index-*.js` (entry) | 273.92 kB | 85.88 kB |
| `StorySandbox` | 242.36 kB | 70.89 kB |
| `index-*.css` | 237.26 kB | 30.43 kB |
| `AdvancedGenerator` | 180.69 kB | 58.00 kB |
| **eager total** (8 files in `dist/index.html`) | **756.2 kB** | **198.0 kB** |
| **all JS + CSS** (79 files) | **2782.5 kB** | **790.1 kB** |

The bundle is split and every route is `React.lazy`; "the heaviest chunk" is a
fact about a different file each time the router moves. `vendor-motion`
(framer-motion, 113.1 kB raw / 37.3 kB gzip) is eagerly preloaded and is 19% of
the gzip eager payload — it is not removable, 60 source files import it.

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

docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
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
| See what the last audit found | `docs/audit-2026-10-04b.md` |
| Rebuild the frontend | `cd frontend_v2 && bun run build` |
| Re-measure mobile after a layout change | `cd frontend_v2 && bun run test:e2e` |
| See earlier audits | `docs/audit-2026-09-29b.md`, then `docs/audit-2026-09-29.md` (each superseded by the next) |
