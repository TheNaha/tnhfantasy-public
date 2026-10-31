# API Reference

TNHFantasy exposes REST and WebSocket APIs for job lifecycle, model management, providers, and runtime state.

> **This document is partial, and the OpenAPI schema is the source of truth.**
> It documents 247 of the **249** live paths on the **329**-operation main router (99.2%), chosen for
> the endpoints a caller needs to know about by name. The remaining ~128 are not
> listed here rather than listed wrongly. Read `/openapi.json` (or `/docs`) for
> the whole surface.
>
> Every entry below was checked against `app.openapi()["paths"]` on 2026-09-29,
> after this file was found to carry 26 endpoints that do not exist — two whole
> sections under the wrong URL prefix, plus invented model routes. A green test
> suite says nothing about whether a document matches the code; that check is
> this line, and it is the reason the note is here.

## Base URL

The backend is **published on two host addresses, and neither is a wildcard**:
`127.0.0.1:8002` (loopback) and `${COMFY_BACKEND_BIND:-100.150.0.4}:8002` — the
operator's own VPN/LAN address, which is a NetBird address on this host.

> This paragraph used to say "the backend has **no host port**" and that
> `http://localhost:8002` answers `000`. That was false as of `7a1f1e93`, which
> added the two publishes above, and the doc kept asserting the opposite for
> days. A document that describes a port that is not there is worse than no
> document: it sends the reader looking for a missing service, and it hides a
> real exposure. The *intent* was always right — never publish `0.0.0.0` — and
> it is still enforced: a bare `8002:8002` publishes the entire
> unauthenticated API on every interface the host has, which is how a probe
> deleted 154 rows of job history on 2026-10-01. The publishes are named
> addresses, not wildcards. Verify with `docker compose ps`.

Reach it one of these ways:

| context | base URL |
|---|---|
| browser, through the frontend | `/api` on the frontend's own origin (`http://localhost:5174`, or `https://comfy.lan.thenaha.my.id`) — the Vite/Nginx frontend proxies `/api` to the backend in-process |
| a shell on the host | `http://127.0.0.1:8002`, or `http://${COMFY_BACKEND_BIND}:8002` |
| a shell inside the container | `http://localhost:8002` from `docker compose exec backend_v2`, or from any container on the `tnhfantasy` network |
| a dedicated API hostname | `https://comfy-backend.lan.thenaha.my.id` (Traefik router `comfyui-api`, on the external `proxy` Docker network) |

Which of those is reachable from where is governed by the NetBird ACL on the
reverse proxy. `docs/deployment.md` has the router table.

## Authentication
TNHFantasy is designed for trusted/self-hosted environments. If exposed publicly, enforce authentication at the reverse-proxy layer.

That mitigation is in effect for the shipped compose file, in the sense that
nothing is published: the backend has no host port and is reached by Traefik on
the `proxy` Docker network, under an ACL the reverse proxy enforces. If you add a
host port or a public router, the whole API becomes unauthenticated and reachable
— `PATCH /api/v2/providers/{id}` and `DELETE /api/jobs` included.

## Idempotency-Key

The following endpoints support optional `Idempotency-Key` headers:

- `POST /api/jobs`
- `POST /api/generate`
- `POST /api/generate/batch`

Behavior:

- When the header is provided, identical retries with the same key reuse the same response during a short server deduplication window.
- Deduplication is endpoint-scoped (the same key on different endpoints is treated independently).
- When the header is omitted, each request is treated as a new submission.

## Core Endpoints

### Jobs (`/api/jobs`)

- `GET /api/jobs`: List jobs (supports pagination via `limit` and `offset`).
- `POST /api/jobs`: Create and enqueue one job from a workflow payload.
- `GET /api/jobs/{job_id}`: Fetch one job.
- `DELETE /api/jobs/{job_id}`: Delete one job record.
- `DELETE /api/jobs`: Delete all jobs.
- `POST /api/jobs/{job_id}/retry`: Retry a failed job.
- `POST /api/jobs/validate`: Pre-flight validation for provider/model availability.
- `GET /api/jobs/active`: List active (non-terminal) jobs.
- `GET /api/jobs/queue`: Queue status and ETA hints.
- `GET /api/jobs/stats/summary`: Aggregate job statistics.

### Generation (`/api`)

- `POST /api/generate`: Submit a single generation workflow.
- `POST /api/generate/batch`: Submit multiple workflows in one request.

### Models V2 (`/api/v2/models`)

- `POST /api/v2/models`: Import a model/version selection.
- `PUT /api/v2/models/{model_id}/default-version`: Set model default version.
- `DELETE /api/v2/models/{model_id}`: Delete model and associated status rows.
- `GET /api/v2/models/{model_id}/versions`: List versions for a model.
- `GET /api/v2/models/preview/{model_id}`: Get the model preview image. The `preview` segment comes **before** the id — it is a static prefix, not a sub-resource of the model.
- `PUT /api/v2/models/versions/{version_id}/toggle`: Enable/disable a version. There is no bare update and no delete on a version:

  ```
  PUT /api/v2/models/versions/{version_id}     (does not exist)
  DELETE /api/v2/models/versions/{version_id}  (does not exist)
  ```

Maintenance (`/api/v2/models/maintenance`) — separate verbs on the same models, not a versioned resource:

- `POST /api/v2/models/maintenance/cleanup-orphans`: Remove models that have **no versions** (left behind by a failed import).
- `POST /api/v2/providers/cleanup-orphaned-statuses`: Clean up orphaned provider status records. The `models`-side reverse-reconciliation endpoint that used to sit beside this line was removed on 2026-10-09: it was an unguarded destructive sweep with no caller in the repository.
- `POST /api/v2/models/maintenance/{model_id}/resync`: Re-reconcile one model.
- `POST /api/v2/models/maintenance/{model_id}/check-dependencies`: Report dependents before a delete.
- `POST /api/v2/models/maintenance/resync-all` / `POST /api/v2/models/maintenance/backfill-statuses`: Bulk reconciliation.
- `GET /api/v2/models/maintenance/{model_id}/tags`: List tags for a model.
- `POST /api/v2/models/maintenance/{model_id}/tags`: Add tags to a model.
- `DELETE /api/v2/models/maintenance/{model_id}/tags/{tag}`: Remove a tag. The path parameter is the tag **string**, not a tag id.

Not endpoints, despite having been documented as such here — versions are created by import and by provider sync, not by an explicit create call:

```
POST /api/v2/models/{model_id}/versions          (does not exist)
POST /api/v2/models/provider-sync                (does not exist)
GET|POST /api/v2/models/versions/{version_id}/files  (does not exist)
```

### External Models (`/api/v2/models/external`)

- `POST /api/v2/models/external/parse`: Parse a model URL from CivitAI or HuggingFace.
- `GET /api/v2/models/external/civitai`: Search CivitAI.
- `GET /api/v2/models/external/civitai/enums`: CivitAI model-type / base-model enums for the search UI.
- `GET /api/v2/models/external/civitai/tags`: CivitAI tag list.
- `GET /api/v2/models/external/huggingface`: Search HuggingFace.

## World Vault v2 (`/api/v2`)

The World Vault is the single PostgreSQL + pgvector index for TNHFantasy's three fantasy pillars — **Image Generation** (assets), **Roleplay Chat** (chats), and **Story Sandbox** (stories) — plus characters, lorebooks, and scenarios. All endpoints return JSON. Read filters (`workspace`, `character_id`, `story_id`) let the three pillars stay visually/logically separate while sharing one index.

### Assets (`/api/v2/assets`)

DB-backed gallery index (replaces the old in-memory `GalleryIndexer`). The asset's `workspace` (`main` / `roleplay` / `story`) is derived from its source generator at save time by `asset_reconciler._derived_workspace()`.

- `GET /api/v2/assets` — List assets. Query: `limit` (24), `cursor` (keyset pagination), `workspace` (`main|roleplay|story`), `character_id`, `story_id`, `search` (matches `filename` or JSON `metadata_`). Each item carries `id`, `filename`, `relative_path`, `workspace`, `character_id`, `story_id`, `thumbnail` (a ready-to-use image URL served by `GET /api/thumbnail/{size}/{filename}`, e.g. a `medium` thumbnail of `cat.png`), `file_url` (`/api/v2/assets/{id}/file`), `thumb_url` (`/api/v2/assets/{id}/thumb` when a thumbnail exists), `metadata`, dimensions, `blurhash`, `created_at`.
- `GET /api/v2/assets/{asset_id}/file` — Serve the full asset file.
- `GET /api/v2/assets/{asset_id}/thumb` — Serve the asset's (pre-generated) thumbnail; falls back to `/file` when no thumbnail exists.

### Chats (`/api/v2/chats`) — Roleplay pillar

- `GET /api/v2/chats` — List chats. Query: `workspace=roleplay` selects roleplay chats (`chat_type == workspace`); `character_id=<id>` selects the chats a character is in, as the primary character or as one of the additional cast.
- `POST /api/v2/chats` — Create a chat. Body: `{character_id, title?, chat_type?}`; auto-creates a root message.
- `GET /api/v2/chats/{chat_id}` — Fetch a chat + its character.
- `PATCH /api/v2/chats/{chat_id}` — Update chat-level fields (title, chat type,
  the per-chat budgets, and `scene_graph_enabled` / `scene_graph_budget` — whether the
  Illustrator may author a scene's generation PARAMETERS as well as its prompt, and how
  much scene authoring this chat may spend).
- `DELETE /api/v2/chats/{chat_id}` — Delete a chat (cascades messages).
- `GET /api/v2/chats/{chat_id}/messages` — All messages (DB-backed conversation; `metadata_` JSON + `tool_calls` columns).
- `POST /api/v2/chats/{chat_id}/messages` — Append a user message; server-side context assembled by `context_builder` (backend-owned, per VISION #7) → enqueues an LLM task and returns the created message.
- `DELETE /api/v2/chats/{chat_id}/messages/{message_id}` — Delete a message.
- `GET /api/v2/chats/{chat_id}/system-prompt` — Resolved system prompt (character card + active lorebook context).
- `POST /api/v2/chats/{chat_id}/impersonate` — Generate an assistant turn without a user message (`no_reply`).
- `POST /api/v2/chats/{chat_id}/suggest` — Suggest a user reply (RAG over lorebooks).
- `POST /api/v2/chats/{chat_id}/scene` — Generate the next scene/continuation.
- `POST /api/v2/chats/{chat_id}/illustrate` — Illustrate the current turn (queues an image-generation task into the `roleplay` workspace).
- `GET /api/v2/chats/{chat_id}/images` — Gallery of images attached to this chat's messages.
- `GET /api/v2/chats/{chat_id}/jobs` — List jobs tied to a chat.
- `POST /api/v2/chats/{chat_id}/messages/{message_id}/swipe` — Swipe to a regenerated variant (returns `Message`).
- `POST /api/v2/chats/{chat_id}/rollback` — Rollback the conversation to a prior message.
- `POST /api/v2/chats/{chat_id}/regenerate` — Regenerate the last assistant turn.
- `GET /api/v2/chats/{chat_id}/director-traces` — The Laya System 1 decision trace for every turn of this chat.
- `POST /api/v2/chats/{chat_id}/director/evaluate` — Run one Director decision (triage, audit or chaining) against the chat's current state and return it.
- `PATCH /api/v2/chats/{chat_id}/state-snapshot` — Replace the chat's `state_snapshot`.
- `POST /api/v2/chats/{chat_id}/export-story` — Create a story from this chat. The new story records `chat_id`, so the two stay linked.

> Agentic mode: the orchestrator (`MAX_AGENTIC_DEPTH = 5`) exposes one tool, `generate_image`. A chat turn may issue tool calls that fan out to image jobs; remaining depth is surfaced in the transcript. The tool is offered only when the job's metadata says `agentic` — the swipe and scene routes stamp that, and the plain send path does not, because the Laya pipeline routes the turn instead of letting the model reach for a tool.
>
> `chat.story_id` records that a chat was started FROM a story, and `story.chat_id` that a story was exported FROM a chat. Each direction is one-way and the pair is never linked both ways: starting a chat from a story and exporting it back produces a NEW story, not a cycle.

### Stories (`/api/v2/stories`) — Story pillar

- `GET /api/v2/stories` — List stories.
- `POST /api/v2/stories` — Create a story. Body: `{title, description, genre?}`.
- `GET /api/v2/stories/{story_id}` — Fetch a story.
- `PUT /api/v2/stories/{story_id}` — Update title/description/genre.
- `DELETE /api/v2/stories/{story_id}` — Delete (cascades chapters + assets).
- `GET /api/v2/stories/{story_id}/chapters` — List chapters (ordered).
- `POST /api/v2/stories/{story_id}/chapters` — Create a chapter (server-side context assembled by `context_builder` → LLM task).
- `GET /api/v2/stories/{story_id}/chapters/{chapter_id}` — Fetch a chapter.
- `PUT /api/v2/stories/{story_id}/chapters/{chapter_id}` — Update a chapter.
- `DELETE /api/v2/stories/{story_id}/chapters/{chapter_id}` — Delete a chapter.
- `POST /api/v2/stories/{story_id}/chapters/{chapter_id}/continue` — Continue the story (enqueues LLM continuation; `metadata_["workspace"] == "story"`).
- `POST /api/v2/stories/{story_id}/chapters/{chapter_id}/beats` — Add a story beat.
- `POST /api/v2/stories/{story_id}/chapters/{chapter_id}/branch` — Branch the chapter from a message index (returns the new `StoryChapter`).
- `GET /api/v2/stories/{story_id}/images` — Gallery of images across the story's chapters (workspace-scoped).
- `POST /api/v2/stories/{story_id}/chapters/{chapter_id}/illustrate` — Generate a chapter illustration (queues an image-generation task).

### Lorebooks (`/api/v2/lorebooks`)

pgvector-backed semantic knowledge entries (`LorebookEntry.embedding` is `Vector(384)`).

- `GET /api/v2/lorebooks` — List lorebooks.
- `POST /api/v2/lorebooks` — Create a lorebook.
- `GET /api/v2/lorebooks/{lorebook_id}` — Fetch a lorebook.
- `PUT /api/v2/lorebooks/{lorebook_id}` — Update a lorebook.
- `DELETE /api/v2/lorebooks/{lorebook_id}` — Delete (cascades entries).
- `GET /api/v2/lorebooks/{lorebook_id}/search` — **Semantic search** (pgvector cosine similarity over `embedding`); query `q` + optional `top_k`.
- `GET /api/v2/lorebooks/{lorebook_id}/entries` — List entries.
- `POST /api/v2/lorebooks/{lorebook_id}/entries` — Create an entry (embedding computed server-side).
- `PUT /api/v2/lorebooks/{lorebook_id}/entries/{entry_id}` — Update an entry.
- `DELETE /api/v2/lorebooks/{lorebook_id}/entries/{entry_id}` — Delete an entry.

### Characters (`/api/v2/characters`)

- `GET /api/v2/characters` — List characters.
- `POST /api/v2/characters` — Create a character (character-card JSON).
- `POST /api/v2/characters/import` — Import a character card (PNG, JSON, CHARX) or a TNHComy bundle. Re-importing a card this app exported UPDATES that character — the card carries the character's id in `data.extensions.tnhfantasy`, which SillyTavern preserves — instead of creating a second one.
- `POST /api/v2/characters/import/analyze` — What importing this card would do: the fields it holds, whether it matches a character that already exists, and the scopes on offer. **Writes nothing.**
- `POST /api/v2/characters/import/commit` — Import, with the scope and the match already chosen. Form: `scope` (`character` or `world`), `match_action` (`auto`, `update` or `create`).
- `GET /api/v2/characters/{character_id}` — Fetch a character.
- `PUT /api/v2/characters/{character_id}` — Update a character.
- `DELETE /api/v2/characters/{character_id}` — Delete a character.
- `POST /api/v2/characters/{character_id}/avatar` — Upload/set an avatar.
- `GET /api/v2/characters/{character_id}/avatar` — Serve the avatar.
- `POST /api/v2/characters/{character_id}/clone` — Clone a character (returns `Character`).
- `GET /api/v2/characters/{character_id}/export` — Export a character. `format`: `default`/`v2` (PNG), `v3` (PNG), `json`, `charx`, or `bundle` (the TNHComy bundle, which carries what a card cannot). `include` names the bundle's optional sections: `expressions`, `voice`, `generation`, `world`, `lorebooks`, `chat`.
- `GET /api/v2/characters/{character_id}/export/preview` — What an export of this character can and cannot carry. The export is a PNG or an archive, so it has nowhere to say this; the export menu asks here first.

### Scenarios (`/api/v2/scenarios`)

- `GET /api/v2/scenarios` — List scenarios.
- `POST /api/v2/scenarios` — Create a scenario.
- `GET /api/v2/scenarios/{scenario_id}` — Fetch a scenario.
- `PUT /api/v2/scenarios/{scenario_id}` — Update a scenario.
- `DELETE /api/v2/scenarios/{scenario_id}` — Delete a scenario.

### LLM Config (`/api/v2/llm`)

The prefix is `/llm`, not `/llm-config`; this file used to document both, and the wrong one.

- `GET /api/v2/llm/default-provider` — Currently configured default LLM provider for roleplay/story.
- `PUT /api/v2/llm/default-provider` — Set the default LLM provider.
- `GET /api/v2/llm/available-models` — Models exposed by the configured LLM provider.
- `GET /api/v2/llm/providers` — Available LLM providers for chat/story narration.
- `GET /api/v2/llm/providers/health` — Aggregate health of every LLM/hybrid provider, probed in parallel. Returns `{providers, healthy_count, total_count}`.
- `POST /api/v2/llm/providers/{provider_id}/test` — **Test Connection**: instantiates the provider's in-process engine and runs its `health`/`object_info`/list path, returning liveness and available models (no remote worker URL involved).
- `GET /api/v2/llm/agents/with-variants` — Every agent profile with its prompt variants and its resolved active variant, in one response. The Agent tab uses this instead of one request per agent.
- `GET /api/v2/llm/pipeline` — The roleplay chat pipeline manifest: the stages, their order, their executors and their limits. The numbers come from `core/pipeline_limits`, which the code also imports, so this cannot quote a limit the pipeline does not enforce.
- `GET /api/v2/llm/director/gates` — The canonical Statekeeper gate registry: the categories, the gates, the fields each gate unlocks, and the activation threshold. The chat panel renders this rather than a hand-copied list.
- `GET /api/v2/llm/decisions/evaluate` — Evaluate a Director decision against a supplied context.

### Agents (`/api/v2/agents`)

Agent profiles are the Laya routing targets: the Character, Narrator, Updater, Illustrator, Continuation and custom agents, each with a system prompt and a set of prompt variants.

- `GET /api/v2/agents` — List agent profiles. Query: `include_disabled`.
- `POST /api/v2/agents` — Create an agent profile.
- `GET /api/v2/agents/{agent_id}` — Fetch one agent profile.
- `PUT /api/v2/agents/{agent_id}` — Update an agent profile.
- `DELETE /api/v2/agents/{agent_id}` — Delete an agent profile.
- `GET`, `POST` `/api/v2/agents/{agent_id}/avatar` — Fetch or upload an agent's avatar. The column is `agent_profiles.avatar_path`; it was accepted by the API from the day the API was written and the model never had the column, so the field was dropped on create, raised on update, and made `GET /api/v2/llm/agents/with-variants` return HTTP 500 for any deployment that had agents in the table.
- `GET`, `POST` `/api/v2/agents/{agent_id}/variants` — List and create prompt variants.
- `GET`, `PUT`, `DELETE` `/api/v2/agents/{agent_id}/variants/{variant_id}` — Read, update and delete a variant.
- `POST /api/v2/agents/{agent_id}/variants/{variant_id}/activate` — Make a variant the active one.
- `POST /api/v2/agents/simulate` — Run a workflow simulation against an agent.

A variant may carry two scopes, and they are what make the sub-variant system
answer to "a different prompt for a different LLM" and "a prompt for the mood
that just changed":

- `model_scope` — the model (or model **role**, e.g. `rp`) the variant is
  FOR. `null` means "any model". A scoped variant is only offered to Laya
  when the agent it belongs to will actually answer with that model, and it
  is applied automatically when it matches — the scope IS its activation.
  An unscoped, inactive variant is never auto-applied: the built-in
  sub-variants are seeded that way on purpose, as examples Laya picks by
  name.
- `gate_scope` — the Statekeeper gate the variant is FOR. `null` means "any
  gate". The Updater's *schema* was already gate-specific — an unfired
  gate's field is absent from the JSON the model is shown, and anything
  smuggled in is dropped on the way back. This is the prompt half: the
  extractor is told in words what shifted.

A variant with no `selection_hint` and no `description` is never offered to
Laya, so it can only be used by naming it. The LLM Studio marks those.

### Worlds (`/api/v2/worlds`)

- `GET /api/v2/worlds` — List worlds.
- `POST /api/v2/worlds` — Create a world.
- `GET /api/v2/worlds/{world_id}` — Fetch a world.
- `PUT /api/v2/worlds/{world_id}` — Update a world.
- `DELETE /api/v2/worlds/{world_id}` — Delete a world.
- `GET /api/v2/worlds/{world_id}/dashboard` — Aggregate dashboard payload for one world (counts and recent activity across the pillars it contains).

### Personas (`/api/v2/personas`)

- `GET /api/v2/personas` — List personas.
- `POST /api/v2/personas` — Create a persona.
- `GET /api/v2/personas/{persona_id}` — Fetch a persona.
- `PUT /api/v2/personas/{persona_id}` — Update a persona.
- `DELETE /api/v2/personas/{persona_id}` — Delete a persona.

### Voices (`/api/v2/voices`)

TTS voices. Synthesis and voice design are `task_type="tts"` jobs routed to the `tts-*` provider; the CRUD here is the catalogue they are chosen from.

- `GET /api/v2/voices` — List voices.
- `POST /api/v2/voices` — Create a voice record.
- `GET /api/v2/voices/{voice_id}` — Fetch a voice.
- `PUT /api/v2/voices/{voice_id}` — Update a voice.
- `PATCH /api/v2/voices/{voice_id}` — Partial update.
- `DELETE /api/v2/voices/{voice_id}` — Delete a voice.
- `POST /api/v2/voices/{voice_id}/preview` — Get a voice preview clip.
- `POST /api/v2/voices/design` — Generate new voice designs (enqueues a TTS job).

  There is no `POST /api/v2/voices/speak`. It duplicated
  `POST /api/v2/voices/{voice_id}/preview`, which is the route the frontend
  calls, and it was removed on 2026-10-21.

### Timeline (`/api/v2/timeline`)

- `GET /api/v2/timeline` — Chronological events across the World Vault.

  There is no `/api/v2/timeline/timeline`. This file previously documented one and
  offered a reason for it ("the router mounts at `/api/v2/timeline` and the route
  itself is `/timeline`") which was simply false: `world_vault/__init__.py`
  includes `timeline_router` with no prefix, and `app.openapi()` lists only
  `/api/v2/timeline`. `e2e/activity.spec.js` then requested the doubled path,
  404'd, and threw. One wrong belief here, one broken test there — which is why
  `tests/test_e2e_endpoint_contract.py` now checks every endpoint the specs
  request against the real route table.

### Gallery

There is no `GET /api/v2/gallery`. It was a second URL for the gallery
listing — byte-identical to `GET /api/files`, which the frontend calls — and
it existed for exactly one reason: it called the gallery route handler as a
plain Python call, so FastAPI never resolved the callee's
`Query(..., ge=1, le=MAX_BATCH_ITEMS)` default and `?limit=100000000`
materialised the whole assets table. The alias was removed on 2026-10-21; the
paginated, filterable, DB-backed listing is `GET /api/v2/assets`.

## Files & Media

- `GET /api/view/{path:path}` — Serve a source/output file (URL-decoded server-side).
- `GET /api/thumbnail/{size}/{filename:path}` — Serve a pre-generated thumbnail (`size=medium`); falls back to the full image.

## WebSocket / Socket.IO (`/socket.io`)

Real-time job lifecycle, downloads, reconciliation, and provider status (replaces SSE for these streams).

- `job.progress` / `job.completed` / `job.failed` / `job.cancelled` — per-`job_id` updates (primary transport for `useJobStatus` / `useLLMJobResult`; JS polling fallback).
- `provider.status` — live provider-worker alive checks (worker-only, per Vision #4).
- `reconciliation.update` — asset-reconciliation progress.
- `download.progress` — file download progress.

### Providers (`/api/v2/providers`)

- `GET /api/v2/providers`: List all configured providers.
- `POST /api/v2/providers`: Register a new provider.
- `GET /api/v2/providers/{id}`: Get provider details.
- `PUT /api/v2/providers/{id}`: Update provider config/credentials.
- `PATCH /api/v2/providers/{id}`: Update provider (alias for PUT).
- `DELETE /api/v2/providers/{id}`: Remove provider.
- `GET /api/v2/providers/config/load-balancing`: Current load-balancer configuration with stats.
- `PUT /api/v2/providers/config/load-balancing`: Update load-balancer configuration.
- `POST /api/v2/providers/{id}/reconcile`: Trigger model sync for a provider.
- `GET /api/v2/providers/{id}/reconciliation-status`: Get reconciliation status for a provider.
- `POST /api/v2/providers/{id}/reconciliation-event`: Trigger a reconciliation event.
- `GET /api/v2/providers/{id}/modal-stats`: Provider storage/model counts (cached 30s).
- `GET /api/v2/providers/{id}/sync-status`: V2-backed sync counts for a provider.
- `GET /api/v2/providers/{id}/models`: Provider models grouped by directory.
- `DELETE /api/v2/providers/{id}/models`: Delete a model file from a provider.
- `POST /api/v2/providers/models/custom`: Create a custom model entry and trigger downloads.
- `POST /api/v2/providers/{id}/setup`: Run provider setup (initialize directories).
- `POST /api/v2/providers/cleanup-orphaned-statuses`: Clean up orphaned provider status records.
- `POST /api/v2/providers/state/cleanup`: Maintenance cleanup for provider state.

### Collections (`/api/v2/collections`)

The prefix is `/api/v2/collections`. This file previously documented `/api/collections`, which does not exist — every entry in the section 404'd.

- `GET /api/v2/collections`: List all collections.
- `POST /api/v2/collections`: Create a new collection.
- `GET /api/v2/collections/{collection_id}`: Get collection details.
- `PUT /api/v2/collections/{collection_id}`: Update a collection.
- `DELETE /api/v2/collections/{collection_id}`: Delete a collection.
- `POST /api/v2/collections/{collection_id}/images`: Add images to a collection.
- `DELETE /api/v2/collections/{collection_id}/images`: Remove images from a collection.
- `POST /api/v2/collections/move`: Move images between collections.
- `GET /api/v2/collections/by-character/{character_id}`: Get the collection for one character.
- `GET /api/v2/collections/by-characters`: Batch lookup for several characters at once.
- `POST /api/v2/collections/import`: Import collections.
- `GET /api/v2/collections/export`: Export collections.

The Characters, Chats, Lorebooks, Scenarios, Stories and LLM Config sections above cover those families; this file used to carry a second, thinner copy of each one further down, with a different prefix for two of them. The duplicates were removed and their three unique entries folded into the sections above (`PATCH /api/v2/chats/{chat_id}`, `POST …/chapters/{chapter_id}/illustrate`, and the fourth LLM endpoint).

### Prompts (`/api/prompts`)

- `GET /api/prompts`: List prompts (supports search, pagination).
- `POST /api/prompts`: Create a prompt.
- `GET /api/prompts/{prompt_id}`: Get a prompt.
- `PUT /api/prompts/{prompt_id}`: Update a prompt.
- `DELETE /api/prompts/{prompt_id}`: Delete a prompt.
- `POST /api/prompts/{prompt_id}/use`: Increment usage count.
- `POST /api/prompts/import`: Import prompts.
- `GET /api/prompts/categories`: List prompt categories.
- `GET /api/prompts/favorites`: List favorite prompts.
- `GET /api/prompts/most-used`: List most-used prompts.

### Settings (`/api/settings`)

- `GET /api/settings`: Read runtime settings.
- `PUT /api/settings`: Persist runtime settings.
- `GET /api/settings/schema`: Get settings JSON schema.
- `POST /api/settings/reset`: Reset settings to defaults.
- `GET /api/settings/branding`: Get branding configuration.
- `POST /api/settings/branding`: Update branding configuration.
- `GET /api/settings/session`: Get current session info.
- `POST /api/settings/session`: Update session info.
- `GET /api/settings/presets`: List saved presets.

### Statistics (`/api/statistics`)

- `GET /api/statistics`: Retrieve usage and metadata statistics.
- `GET /api/statistics/detailed`: Detailed statistics.
- `GET /api/statistics/summary`: Summary statistics.

### Files

- `GET /api/files`: List files in output directory.
- `DELETE /api/files/{filename}`: Delete one file.
- `GET /api/view/{path}`: Serve an output image by relative path.
- `GET /api/thumbnail/{size}/{filename}`: Serve a thumbnail by size and filename.
- `POST /api/upload`: Upload an image file.
- `POST /api/upload/input`: Upload an input file.
- `POST /api/upload/mask`: Upload a mask file.
- `POST /api/batch/delete`: Batch delete files.
- `POST /api/files/batch-download`: Batch download as an archive.
- `POST /api/files/metadata/batch`: Get metadata for multiple files in batch.

There is no provider file proxy. This file documented one; no such route exists, and provider files are reached through `GET /api/v2/assets/{asset_id}/file` instead.

```
GET /api/files/proxy/{provider_id}/{path}    (does not exist)
```



### Health

- `GET /api/live`: Liveness — the process is up. Checks nothing else, by design.
- `GET /api/ready`: Readiness — includes a database query (`SELECT 1`).

This was three endpoints: `/api/health` was a second name for the constant that
`/api/live` returns, with no callers outside a test, while the provider workers
exposed `/live` and the compose healthcheck used `/api/ready`. The provider

### Metrics

- `GET /metrics`: Prometheus metrics endpoint.

### WebSocket

- Endpoint: the socket.io path on the same origin as the frontend —
  `ws://localhost:5174/socket.io` locally, `wss://comfy.lan.thenaha.my.id/socket.io`
  through Traefik. There is no `ws://localhost:8002`, because the backend has no
  host port (see "Base URL").
- Clients subscribe to job/provider events and receive real-time updates (created, progress, completed, failed, cancelled).

---

## Route index (generated)

<!-- BEGIN GENERATED ROUTE INDEX -->

<!-- Generated by scripts/generate_api_docs.py. Do not edit by hand. -->

The live surface is **295 paths / 383 operations**. Everything below is
derived from `app.openapi()`, so it cannot name a route that does not exist.

### Characters

- `GET`, `POST` `/api/v2/characters`
- `POST` `/api/v2/characters/import`
- `POST` `/api/v2/characters/import/analyze`
- `POST` `/api/v2/characters/import/commit`
- `POST` `/api/v2/characters/reorder`
- `GET`, `PUT`, `PATCH`, `DELETE` `/api/v2/characters/{character_id}`
- `GET`, `POST` `/api/v2/characters/{character_id}/avatar`
- `POST` `/api/v2/characters/{character_id}/avatar/animate`
- `POST` `/api/v2/characters/{character_id}/clone`
- `GET` `/api/v2/characters/{character_id}/export`
- `GET` `/api/v2/characters/{character_id}/export/preview`
- `GET` `/api/v2/characters/{character_id}/expressions`
- `POST` `/api/v2/characters/{character_id}/expressions/generate`

### Chats

- `GET`, `POST` `/api/v2/chats`
- `POST` `/api/v2/chats/import`
- `GET`, `PATCH`, `DELETE` `/api/v2/chats/{chat_id}`
- `GET`, `POST` `/api/v2/chats/{chat_id}/branches`
- `GET` `/api/v2/chats/{chat_id}/director-traces`
- `POST` `/api/v2/chats/{chat_id}/director/evaluate`
- `GET` `/api/v2/chats/{chat_id}/export`
- `POST` `/api/v2/chats/{chat_id}/export-story`
- `POST` `/api/v2/chats/{chat_id}/illustrate`
- `GET` `/api/v2/chats/{chat_id}/images`
- `POST` `/api/v2/chats/{chat_id}/impersonate`
- `GET` `/api/v2/chats/{chat_id}/jobs`
- `GET`, `POST` `/api/v2/chats/{chat_id}/messages`
- `PATCH`, `DELETE` `/api/v2/chats/{chat_id}/messages/{message_id}`
- `GET` `/api/v2/chats/{chat_id}/messages/{message_id}/alternates`
- `POST` `/api/v2/chats/{chat_id}/messages/{message_id}/generate-swipe`
- `POST` `/api/v2/chats/{chat_id}/messages/{message_id}/narrate`
- `PATCH` `/api/v2/chats/{chat_id}/messages/{message_id}/pin`
- `POST` `/api/v2/chats/{chat_id}/messages/{message_id}/swipe`
- `POST` `/api/v2/chats/{chat_id}/regenerate`
- `POST` `/api/v2/chats/{chat_id}/rollback`
- `POST` `/api/v2/chats/{chat_id}/scene`
- `PATCH` `/api/v2/chats/{chat_id}/state-snapshot`
- `POST` `/api/v2/chats/{chat_id}/suggest`
- `GET` `/api/v2/chats/{chat_id}/system-prompt`

### Stories

- `GET`, `POST` `/api/v2/stories`
- `POST` `/api/v2/stories/parse`
- `GET` `/api/v2/stories/published/{token}`
- `GET` `/api/v2/stories/published/{token}/export`
- `GET`, `PUT`, `DELETE` `/api/v2/stories/{story_id}`
- `POST` `/api/v2/stories/{story_id}/adopt-worldbuilding`
- `GET`, `POST` `/api/v2/stories/{story_id}/chapters` — List a story's chapters.
- `POST` `/api/v2/stories/{story_id}/chapters/reorder` — Reorder the chapter list.
- `GET`, `PUT`, `DELETE` `/api/v2/stories/{story_id}/chapters/{chapter_id}` — Read or replace one chapter.
- `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/ai-action`
- `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/beats`
- `PATCH`, `DELETE` `/api/v2/stories/{story_id}/chapters/{chapter_id}/beats/{beat_id}`
- `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/beats/{beat_id}/select-alternate`
- `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/branch`
- `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/continue`
- `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/discover-worldbuilding`
- `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/export-comic`
- `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/illustrate`
- `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/narrate`
- `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/retry-last`
- `GET`, `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/revisions`
- `POST` `/api/v2/stories/{story_id}/chapters/{chapter_id}/revisions/{revision_id}/restore`
- `GET` `/api/v2/stories/{story_id}/export`
- `GET` `/api/v2/stories/{story_id}/images`
- `POST` `/api/v2/stories/{story_id}/publish` — Publish a story to a token URL.
- `POST` `/api/v2/stories/{story_id}/start-chat`
- `POST` `/api/v2/stories/{story_id}/unpublish`

### Worlds

- `GET`, `POST` `/api/v2/worlds`
- `GET`, `PUT`, `DELETE` `/api/v2/worlds/{world_id}`
- `GET` `/api/v2/worlds/{world_id}/dashboard`

### World Vault (aggregates)

- `GET` `/api/v2/world-vault/entities`
- `POST` `/api/v2/world-vault/estimate-tokens`
- `GET`, `POST` `/api/v2/world-vault/graph-edges`
- `DELETE` `/api/v2/world-vault/graph-edges/{edge_id}`
- `GET`, `PUT`, `DELETE` `/api/v2/world-vault/graph-layout/`
- `POST` `/api/v2/world-vault/onboarding/analyze-card`
- `POST` `/api/v2/world-vault/onboarding/analyze-character/{character_id}`
- `POST` `/api/v2/world-vault/onboarding/analyze-document`
- `POST` `/api/v2/world-vault/onboarding/analyze-story-text`
- `GET` `/api/v2/world-vault/onboarding/archetypes`
- `POST` `/api/v2/world-vault/onboarding/commit`
- `POST` `/api/v2/world-vault/onboarding/commit-canon/{chat_id}`
- `POST` `/api/v2/world-vault/onboarding/compile-story/{chat_id}`
- `POST` `/api/v2/world-vault/onboarding/crossover-preview`
- `POST` `/api/v2/world-vault/onboarding/enrich-field`
- `POST` `/api/v2/world-vault/onboarding/extract-scenarios`
- `POST` `/api/v2/world-vault/onboarding/extract-statekeeper`
- `POST` `/api/v2/world-vault/onboarding/extract-visual-tags`
- `POST` `/api/v2/world-vault/onboarding/extract-world-lore`
- `POST` `/api/v2/world-vault/onboarding/fast-travel/{chat_id}`
- `POST` `/api/v2/world-vault/onboarding/ingest-story-chained`
- `POST` `/api/v2/world-vault/onboarding/reverse-vision/{chat_id}`
- `POST` `/api/v2/world-vault/onboarding/visualize-item/{chat_id}`
- `POST` `/api/v2/world-vault/onboarding/world-tick/{world_id}`
- `GET` `/api/v2/world-vault/relationships`
- `GET` `/api/v2/world-vault/search`

### Lorebooks

- `GET`, `POST` `/api/v2/lorebooks`
- `GET`, `PUT`, `DELETE` `/api/v2/lorebooks/{lorebook_id}`
- `GET`, `POST` `/api/v2/lorebooks/{lorebook_id}/entries`
- `POST` `/api/v2/lorebooks/{lorebook_id}/entries/bulk-delete`
- `PUT`, `DELETE` `/api/v2/lorebooks/{lorebook_id}/entries/{entry_id}`
- `GET` `/api/v2/lorebooks/{lorebook_id}/export`
- `POST` `/api/v2/lorebooks/{lorebook_id}/import`
- `POST` `/api/v2/lorebooks/{lorebook_id}/reindex`
- `GET` `/api/v2/lorebooks/{lorebook_id}/search`

### Locations

- `GET`, `POST` `/api/v2/locations`
- `GET` `/api/v2/locations/search`
- `GET`, `PUT`, `PATCH`, `DELETE` `/api/v2/locations/{location_id}`
- `POST` `/api/v2/locations/{location_id}/image`

### Sessions

- `GET`, `POST` `/api/v2/sessions` — List generation sessions.
- `POST` `/api/v2/sessions/detect`
- `GET`, `PATCH`, `DELETE` `/api/v2/sessions/{session_id}`
- `GET`, `POST` `/api/v2/sessions/{session_id}/assets`
- `DELETE` `/api/v2/sessions/{session_id}/assets/{asset_id}`
- `POST` `/api/v2/sessions/{session_id}/merge`
- `POST` `/api/v2/sessions/{session_id}/split`

### Timeline

- `GET` `/api/v2/timeline`

### Memories

- `GET`, `POST` `/api/v2/memories`
- `GET` `/api/v2/memories/character/{character_id}`
- `POST` `/api/v2/memories/reindex` — Re-embed every memory. Expensive.
- `GET` `/api/v2/memories/search/semantic`
- `GET`, `PUT`, `DELETE` `/api/v2/memories/{memory_id}`

### Collections

- `GET`, `POST` `/api/v2/collections`
- `GET` `/api/v2/collections/by-character/{character_id}`
- `GET` `/api/v2/collections/by-characters`
- `GET` `/api/v2/collections/export`
- `POST` `/api/v2/collections/import`
- `POST` `/api/v2/collections/move`
- `GET`, `PUT`, `DELETE` `/api/v2/collections/{collection_id}`
- `POST`, `DELETE` `/api/v2/collections/{collection_id}/images`

### Assets

- `GET` `/api/v2/assets`
- `POST` `/api/v2/assets/auto-tag`
- `GET` `/api/v2/assets/dates`
- `GET` `/api/v2/assets/facet`
- `GET` `/api/v2/assets/{asset_id}/file`
- `POST` `/api/v2/assets/{asset_id}/move`
- `GET` `/api/v2/assets/{asset_id}/thumb`

### Models

- `POST` `/api/v2/models/`
- `POST` `/api/v2/models/autopopulate-all`
- `POST` `/api/v2/models/autopopulate-candidates/batch`
- `GET` `/api/v2/models/autopopulate-pending`
- `GET` `/api/v2/models/autopopulate-status`
- `GET` `/api/v2/models/catalog`
- `POST` `/api/v2/models/check-installed/batch`
- `GET` `/api/v2/models/check-installed/{civitai_model_id}`
- `GET` `/api/v2/models/directory/{directory}`
- `GET` `/api/v2/models/external/civitai`
- `GET` `/api/v2/models/external/civitai/enums`
- `GET` `/api/v2/models/external/civitai/tags`
- `GET` `/api/v2/models/external/huggingface`
- `POST` `/api/v2/models/external/parse`
- `POST` `/api/v2/models/maintenance/backfill-statuses`
- `POST` `/api/v2/models/maintenance/cleanup-orphans`
- `POST` `/api/v2/models/maintenance/resync-all`
- `POST` `/api/v2/models/maintenance/{model_id}/check-dependencies`
- `POST` `/api/v2/models/maintenance/{model_id}/resync`
- `GET`, `POST` `/api/v2/models/maintenance/{model_id}/tags`
- `DELETE` `/api/v2/models/maintenance/{model_id}/tags/{tag}`
- `GET` `/api/v2/models/preview/{model_id}`
- `DELETE` `/api/v2/models/providers/{provider_id}/reset-status`
- `GET` `/api/v2/models/providers/{provider_id}/sync-manifest`
- `GET` `/api/v2/models/search`
- `GET` `/api/v2/models/search/tag/{tag}`
- `GET` `/api/v2/models/sync-manifest`
- `PUT` `/api/v2/models/versions/{version_id}/toggle`
- `GET`, `DELETE` `/api/v2/models/{model_id}`
- `POST` `/api/v2/models/{model_id}/autopopulate`
- `GET` `/api/v2/models/{model_id}/autopopulate-candidates`
- `GET` `/api/v2/models/{model_id}/autopopulate-search`
- `PUT` `/api/v2/models/{model_id}/default-version`
- `GET` `/api/v2/models/{model_id}/generation-info`
- `GET` `/api/v2/models/{model_id}/versions`

### Providers

- `GET`, `POST` `/api/v2/providers/`
- `POST` `/api/v2/providers/cleanup-orphaned-statuses`
- `GET`, `PUT` `/api/v2/providers/config/load-balancing`
- `POST` `/api/v2/providers/deploy`
- `GET` `/api/v2/providers/deploy/targets`
- `POST` `/api/v2/providers/models/custom`
- `GET` `/api/v2/providers/schemas`
- `POST` `/api/v2/providers/state/cleanup`
- `POST` `/api/v2/providers/test-connection`
- `GET`, `PUT`, `PATCH`, `DELETE` `/api/v2/providers/{provider_id}`
- `GET`, `PUT` `/api/v2/providers/{provider_id}/credentials`
- `DELETE` `/api/v2/providers/{provider_id}/credentials/{key}`
- `GET` `/api/v2/providers/{provider_id}/diagnostics`
- `POST` `/api/v2/providers/{provider_id}/free-vram`
- `GET` `/api/v2/providers/{provider_id}/live-metrics`
- `GET` `/api/v2/providers/{provider_id}/logs`
- `GET` `/api/v2/providers/{provider_id}/modal-stats`
- `GET`, `DELETE` `/api/v2/providers/{provider_id}/models`
- `GET` `/api/v2/providers/{provider_id}/models/discovered`
- `POST` `/api/v2/providers/{provider_id}/models/download`
- `POST` `/api/v2/providers/{provider_id}/models/sync`
- `POST` `/api/v2/providers/{provider_id}/ping`
- `POST` `/api/v2/providers/{provider_id}/reconcile`
- `POST` `/api/v2/providers/{provider_id}/reconciliation-event`
- `GET` `/api/v2/providers/{provider_id}/reconciliation-status`
- `POST` `/api/v2/providers/{provider_id}/setup`
- `POST` `/api/v2/providers/{provider_id}/shutdown`
- `GET` `/api/v2/providers/{provider_id}/sync-status`
- `POST` `/api/v2/providers/{provider_id}/test`
- `POST`, `DELETE` `/api/v2/providers/{provider_id}/worker-token`

### Voices

- `GET`, `POST` `/api/v2/voices`
- `POST` `/api/v2/voices/design`
- `GET` `/api/v2/voices/presets`
- `GET`, `PUT`, `PATCH`, `DELETE` `/api/v2/voices/{voice_id}`
- `POST` `/api/v2/voices/{voice_id}/preview`

### Scenarios

- `GET`, `POST` `/api/v2/scenarios`
- `GET`, `PUT`, `DELETE` `/api/v2/scenarios/{scenario_id}`
- `POST` `/api/v2/scenarios/{scenario_id}/apply`

### Jobs

- `GET`, `POST`, `DELETE` `/api/jobs`
- `POST` `/api/jobs/acknowledge-all`
- `GET` `/api/jobs/active`
- `GET` `/api/jobs/breakdown`
- `GET` `/api/jobs/failed`
- `GET` `/api/jobs/queue`
- `POST` `/api/jobs/reconcile-chat-replies` — Rewrite chat replies against their jobs.
- `POST` `/api/jobs/recover`
- `GET` `/api/jobs/search`
- `GET` `/api/jobs/stats/summary`
- `POST` `/api/jobs/validate`
- `GET`, `DELETE` `/api/jobs/{job_id}`
- `POST` `/api/jobs/{job_id}/acknowledge`
- `POST` `/api/jobs/{job_id}/cancel`
- `GET` `/api/jobs/{job_id}/diagnostics`
- `POST` `/api/jobs/{job_id}/retry`

### Files

- `GET` `/api/files`
- `POST` `/api/files/batch-download`
- `POST` `/api/files/cleanup-inputs`
- `POST` `/api/files/metadata/batch`
- `DELETE` `/api/files/{filename}`

### Settings

- `GET`, `PUT` `/api/settings`
- `GET`, `POST` `/api/settings/branding`
- `GET`, `POST` `/api/settings/favorites`
- `GET` `/api/settings/presets`
- `POST` `/api/settings/reset`
- `GET` `/api/settings/scheduler`
- `GET` `/api/settings/schema`
- `GET`, `POST` `/api/settings/session`
- `GET`, `PUT` `/api/settings/system-prompts`
- `GET`, `POST` `/api/settings/system-prompts/library`
- `PUT`, `DELETE` `/api/settings/system-prompts/library/{key}`

### Statistics

- `GET` `/api/statistics`
- `GET` `/api/statistics/detailed`
- `GET` `/api/statistics/summary`

### Prompts

- `GET`, `POST` `/api/prompts`
- `GET` `/api/prompts/categories`
- `GET` `/api/prompts/export`
- `GET` `/api/prompts/favorites`
- `POST` `/api/prompts/import`
- `POST` `/api/prompts/magic`
- `GET` `/api/prompts/most-used`
- `GET`, `PUT`, `DELETE` `/api/prompts/{prompt_id}`
- `POST` `/api/prompts/{prompt_id}/use`

### Generation

- `POST` `/api/generate`
- `POST` `/api/generate/batch`
- `POST` `/api/generate/interrogate`

### Nodes

- `GET` `/api/nodes/capabilities`
- `GET` `/api/nodes/object_info`

### Upload

- `POST` `/api/upload`
- `POST` `/api/upload/input`
- `POST` `/api/upload/mask`

### Other

- `GET` `/`
- `POST` `/api/batch/delete`
- `GET` `/api/live`
- `GET` `/api/ready`
- `GET` `/api/thumbnail/{size}/{filename}`
- `GET`, `POST` `/api/v2/agents`
- `POST` `/api/v2/agents/simulate`
- `GET`, `PUT`, `DELETE` `/api/v2/agents/{agent_id}`
- `GET`, `POST` `/api/v2/agents/{agent_id}/avatar`
- `GET`, `POST` `/api/v2/agents/{agent_id}/variants`
- `GET`, `PUT`, `DELETE` `/api/v2/agents/{agent_id}/variants/{variant_id}`
- `POST` `/api/v2/agents/{agent_id}/variants/{variant_id}/activate`
- `GET`, `POST` `/api/v2/asset/{asset_id}/tags`
- `DELETE` `/api/v2/asset/{asset_id}/tags/{tag}`
- `GET` `/api/v2/llm/agents/with-variants`
- `GET` `/api/v2/llm/available-models`
- `GET` `/api/v2/llm/catalog`
- `PUT` `/api/v2/llm/catalog/active`
- `POST` `/api/v2/llm/decisions/evaluate`
- `GET`, `PUT` `/api/v2/llm/default-provider`
- `GET` `/api/v2/llm/director/gates`
- `GET` `/api/v2/llm/pipeline`
- `GET` `/api/v2/llm/providers`
- `GET` `/api/v2/llm/providers/health`
- `POST` `/api/v2/llm/providers/{provider_id}/test`
- `GET` `/api/v2/llm/questions`
- `POST` `/api/v2/llm/questions/{stage}/custom`
- `PUT`, `DELETE` `/api/v2/llm/questions/{stage}/{key}`
- `GET` `/api/v2/llm/routing`
- `GET` `/api/v2/llm/runtime-defaults`
- `GET`, `POST` `/api/v2/personas`
- `GET`, `PUT`, `DELETE` `/api/v2/personas/{persona_id}`
- `GET` `/api/v2/tags`
- `GET` `/api/view/{path}`
- `GET` `/metrics`

<!-- END GENERATED ROUTE INDEX -->
