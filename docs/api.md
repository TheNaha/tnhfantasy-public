# API Reference

TNHComfy exposes REST and WebSocket APIs for job lifecycle, model management, providers, and runtime state.

> **This document is partial, and the OpenAPI schema is the source of truth.**
> It documents 201 of the **329** live operations on the main router, chosen for
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
Typically `http://localhost:8002`.

## Authentication
TNHComfy is designed for trusted/self-hosted environments. If exposed publicly, enforce authentication at the reverse-proxy layer.

Note that the production compose publishes the backend on `0.0.0.0:8002` and there is no Traefik router on that port, so that mitigation is not in effect until you add one.

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

- `GET /api/v2/models`: Grouped model listing.
- `GET /api/v2/models/all`: Flat model listing.
- `POST /api/v2/models`: Import a model/version selection.
- `PUT /api/v2/models/{model_id}/default-version`: Set model default version.
- `DELETE /api/v2/models/{model_id}`: Delete model and associated status rows.
- `GET /api/v2/models/{model_id}/versions`: List versions for a model.
- `GET /api/v2/models/all-storage-paths`: All expected storage paths from the database.
- `GET /api/v2/models/preview/{model_id}`: Get the model preview image. The `preview` segment comes **before** the id — it is a static prefix, not a sub-resource of the model.
- `PUT /api/v2/models/files/{file_id}/providers/{provider_id}/status`: Report one file's status on one provider.
- `PUT /api/v2/models/versions/{version_id}/toggle`: Enable/disable a version. There is no `PUT /api/v2/models/versions/{version_id}` and no `DELETE` on a version.

Maintenance (`/api/v2/models/maintenance`) — separate verbs on the same models, not a versioned resource:

- `POST /api/v2/models/maintenance/cleanup-orphans`: Remove models that have **no versions** (left behind by a failed import).
- `POST /api/v2/models/cleanup-orphaned`: Remove models whose files have **no active provider status** — the reverse-reconciliation direction, and a different set. Two similarly named endpoints, two different questions.
- `POST /api/v2/models/maintenance/{model_id}/resync`: Re-reconcile one model.
- `POST /api/v2/models/maintenance/{model_id}/check-dependencies`: Report dependents before a delete.
- `POST /api/v2/models/maintenance/resync-all` / `POST /api/v2/models/maintenance/backfill-statuses`: Bulk reconciliation.
- `GET /api/v2/models/maintenance/{model_id}/tags`: List tags for a model.
- `POST /api/v2/models/maintenance/{model_id}/tags`: Add tags to a model.
- `DELETE /api/v2/models/maintenance/{model_id}/tags/{tag}`: Remove a tag. The path parameter is the tag **string**, not a tag id.

Not endpoints, despite having been documented as such here: `POST /api/v2/models/{model_id}/versions`, `POST /api/v2/models/provider-sync`, and any `GET`/`POST` on `/api/v2/models/versions/{version_id}/files`. Versions are created by import and by provider sync, not by an explicit create call.

### External Models (`/api/v2/models/external`)

- `POST /api/v2/models/external/parse`: Parse a model URL from CivitAI or HuggingFace.
- `GET /api/v2/models/external/civitai`: Search CivitAI.
- `GET /api/v2/models/external/civitai/enums`: CivitAI model-type / base-model enums for the search UI.
- `GET /api/v2/models/external/civitai/tags`: CivitAI tag list.
- `GET /api/v2/models/external/huggingface`: Search HuggingFace.

## World Vault v2 (`/api/v2`)

The World Vault is the single PostgreSQL + pgvector index for TNHComfy's three fantasy pillars — **Image Generation** (assets), **Roleplay Chat** (chats), and **Story Sandbox** (stories) — plus characters, lorebooks, and scenarios. All endpoints return JSON. Read filters (`workspace`, `character_id`, `story_id`) let the three pillars stay visually/logically separate while sharing one index.

### Assets (`/api/v2/assets`)

DB-backed gallery index (replaces the old in-memory `GalleryIndexer`). The asset's `workspace` (`main` / `roleplay` / `story`) is derived from its source generator at save time by `asset_reconciler._derived_workspace()`.

- `GET /api/v2/assets` — List assets. Query: `limit` (24), `cursor` (keyset pagination), `workspace` (`main|roleplay|story`), `character_id`, `story_id`, `search` (matches `filename` or JSON `metadata_`). Each item carries `id`, `filename`, `relative_path`, `workspace`, `character_id`, `story_id`, `thumbnail` (`/api/thumbnail/medium/{relative_path}`), `file_url` (`/api/v2/assets/{id}/file`), `thumb_url` (`/api/v2/assets/{id}/thumb` when a thumbnail exists), `metadata`, dimensions, `blurhash`, `created_at`.
- `GET /api/v2/assets/{asset_id}/file` — Serve the full asset file.
- `GET /api/v2/assets/{asset_id}/thumb` — Serve the asset's (pre-generated) thumbnail; falls back to `/file` when no thumbnail exists.

### Chats (`/api/v2/chats`) — Roleplay pillar

- `GET /api/v2/chats` — List chats. Query: `workspace=roleplay` selects roleplay chats (`chat_type == workspace`).
- `POST /api/v2/chats` — Create a chat. Body: `{character_id, title?, chat_type?}`; auto-creates a root message.
- `GET /api/v2/chats/{chat_id}` — Fetch a chat + its character.
- `PATCH /api/v2/chats/{chat_id}` — Update chat-level fields (title, chat type).
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

> Agentic mode: the orchestrator (`MAX_AGENTIC_DEPTH = 5`) exposes tools `generate_image` / `narrate_scene` / `update_world_state`. A chat turn may issue tool calls that fan out to image + lorebook updates; remaining depth is surfaced in the transcript.

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
- `POST /api/v2/characters/import` — Import a character from a URL/card.
- `GET /api/v2/characters/{character_id}` — Fetch a character.
- `PUT /api/v2/characters/{character_id}` — Update a character.
- `DELETE /api/v2/characters/{character_id}` — Delete a character.
- `POST /api/v2/characters/{character_id}/avatar` — Upload/set an avatar.
- `GET /api/v2/characters/{character_id}/avatar` — Serve the avatar.
- `POST /api/v2/characters/{character_id}/clone` — Clone a character (returns `Character`).
- `GET /api/v2/characters/{character_id}/export` — Export a character card.

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
- `POST /api/v2/llm/providers/{provider_id}/test` — **Test Connection**: pings the provider worker's local health endpoint (Vision #4: checks the LOCAL worker `worker_url`, never a remote engine) and returns health + available models.

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
- `POST /api/v2/voices/speak` — Synthesise speech with a voice (enqueues a TTS job).

### Timeline (`/api/v2/timeline`)

- `GET /api/v2/timeline/timeline` — Chronological events across the World Vault. Note the doubled segment: the router mounts at `/api/v2/timeline` and the route itself is `/timeline`.

### Gallery (`/api/v2/gallery`)

- `GET /api/v2/gallery` — The v2 gallery index. The paginated, filterable, DB-backed listing is `GET /api/v2/assets`; this is the gallery-shaped view over it.

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
- `POST /api/v2/providers/wake`: Warm/ensure providers are ready.
- `GET /api/v2/providers/load-balancing`: Current load-balancer strategy (alias).
- `PUT /api/v2/providers/load-balancing`: Update load-balancer strategy (alias).
- `GET /api/v2/providers/config/load-balancing`: Current load-balancer configuration with stats.
- `PUT /api/v2/providers/config/load-balancing`: Update load-balancer configuration.
- `GET /api/v2/providers/load-balancer/stats`: Load-balancer statistics.
- `POST /api/v2/providers/{id}/reconcile`: Trigger model sync for a provider.
- `GET /api/v2/providers/{id}/reconciliation-status`: Get reconciliation status for a provider.
- `POST /api/v2/providers/{id}/reconciliation-event`: Trigger a reconciliation event.
- `GET /api/v2/providers/containers/list`: List all provider containers.
- `GET /api/v2/providers/containers/status`: Get status of all provider containers (cached 10s).
- `GET /api/v2/providers/status-cards`: Canonical status payloads for all providers.
- `GET /api/v2/providers/{id}/status-card`: Status payload for a single provider.
- `GET /api/v2/providers/{id}/modal-stats`: Provider storage/model counts (cached 30s).
- `GET /api/v2/providers/{id}/sync-status`: V2-backed sync counts for a provider.
- `GET /api/v2/providers/{id}/models`: Provider models grouped by directory.
- `DELETE /api/v2/providers/{id}/models`: Delete a model file from a provider.
- `POST /api/v2/providers/models/custom`: Create a custom model entry and trigger downloads.
- `POST /api/v2/providers/{id}/setup`: Run provider setup (initialize directories).
- `GET /api/v2/providers/{id}/deploy-status`: Get persisted deploy state.
- `POST /api/v2/providers/{id}/deploy`: Deploy provider app (Modal or Beam).
- `POST /api/v2/providers/cleanup-orphaned-statuses`: Clean up orphaned provider status records.
- `POST /api/v2/providers/state/cleanup`: Maintenance cleanup for provider state.

### Provider Discovery (`/api/v2/providers`)

- `POST /api/v2/providers/discovery`: Self-discovery endpoint for provider containers to register themselves.

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

There is no `GET /api/files/proxy/{provider_id}/{path}`. This file documented one; no such route exists, and provider files are reached through `GET /api/v2/assets/{asset_id}/file` instead.



### Health

- `GET /api/live`: Liveness — the process is up. Checks nothing else, by design.
- `GET /api/ready`: Readiness — includes a database query (`SELECT 1`).

This was three endpoints: `/api/health` was a second name for the constant that
`/api/live` returns, with no callers outside a test, while the provider workers
exposed `/live` and the compose healthcheck used `/api/ready`. The provider
containers' `/live` and the backend's are now the same name for the same idea.

### Metrics

- `GET /metrics`: Prometheus metrics endpoint.

### WebSocket

- Endpoint: `ws://localhost:8002/socket.io` (Socket.IO transport).
- Clients subscribe to job/provider events and receive real-time updates (created, progress, completed, failed, cancelled).
