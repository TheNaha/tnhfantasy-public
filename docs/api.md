# API Reference

TNHComfy exposes REST and WebSocket APIs for job lifecycle, model management, providers, and runtime state.

## Base URL
Typically `http://localhost:8002`.

## Authentication
TNHComfy is designed for trusted/self-hosted environments. If exposed publicly, enforce authentication at the reverse-proxy layer.

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
- `POST /api/providers/save-image`: Save an image from a provider.

### Models V2 (`/api/v2/models`)

- `GET /api/v2/models`: Grouped model listing.
- `GET /api/v2/models/all`: Flat model listing.
- `POST /api/v2/models`: Import a model/version selection.
- `PUT /api/v2/models/{model_id}/default-version`: Set model default version.
- `DELETE /api/v2/models/{model_id}`: Delete model and associated status rows.
- `GET /api/v2/models/all-storage-paths`: All expected storage paths from the database.
- `POST /api/v2/models/cleanup-orphans`: Remove models with no versions.
- `GET /api/v2/models/{model_id}/tags`: List tags for a model.
- `POST /api/v2/models/{model_id}/tags`: Add tags to a model.
- `DELETE /api/v2/models/{model_id}/tags/{tag_id}`: Remove a tag.
- `GET /api/v2/models/{model_id}/versions`: List versions for a model.
- `POST /api/v2/models/{model_id}/versions`: Create a version.
- `PUT /api/v2/models/versions/{version_id}`: Update a version.
- `DELETE /api/v2/models/versions/{version_id}`: Delete a version.
- `GET /api/v2/models/versions/{version_id}/files`: List files for a version.
- `POST /api/v2/models/versions/{version_id}/files`: Add a file to a version.
- `DELETE /api/v2/models/files/{file_id}`: Delete a model file.
- `GET /api/v2/models/{model_id}/preview`: Get model preview image.
- `POST /api/v2/models/provider-sync`: Sync models from a provider.

### External Models (`/api/v2/models/external`)

- `POST /api/v2/models/external/parse`: Parse a model URL from CivitAI or HuggingFace.
- `GET /api/v2/models/external/civitai`: Search CivitAI.
- `GET /api/v2/models/external/huggingface`: Search HuggingFace.

### Providers (`/api/providers`)

- `GET /api/providers`: List all configured providers.
- `POST /api/providers`: Register a new provider.
- `GET /api/providers/{id}`: Get provider details.
- `PUT /api/providers/{id}`: Update provider config/credentials.
- `PATCH /api/providers/{id}`: Update provider (alias for PUT).
- `DELETE /api/providers/{id}`: Remove provider.
- `POST /api/providers/wake`: Warm/ensure providers are ready.
- `GET /api/providers/load-balancing`: Current load-balancer strategy (alias).
- `PUT /api/providers/load-balancing`: Update load-balancer strategy (alias).
- `GET /api/providers/config/load-balancing`: Current load-balancer configuration with stats.
- `PUT /api/providers/config/load-balancing`: Update load-balancer configuration.
- `GET /api/providers/load-balancer/stats`: Load-balancer statistics.
- `POST /api/providers/{id}/reconcile`: Trigger model sync for a provider.
- `GET /api/providers/{id}/reconciliation-status`: Get reconciliation status for a provider.
- `POST /api/providers/{id}/reconciliation-event`: Trigger a reconciliation event.
- `GET /api/providers/containers/list`: List all provider containers.
- `GET /api/providers/containers/status`: Get status of all provider containers (cached 10s).
- `GET /api/providers/status-cards`: Canonical status payloads for all providers.
- `GET /api/providers/{id}/status-card`: Status payload for a single provider.
- `GET /api/providers/{id}/modal-stats`: Provider storage/model counts (cached 30s).
- `GET /api/providers/{id}/sync-status`: V2-backed sync counts for a provider.
- `GET /api/providers/{id}/models`: Provider models grouped by directory.
- `DELETE /api/providers/{id}/models`: Delete a model file from a provider.
- `POST /api/providers/models/custom`: Create a custom model entry and trigger downloads.
- `POST /api/providers/{id}/setup`: Run provider setup (initialize directories).
- `GET /api/providers/{id}/deploy-status`: Get persisted deploy state.
- `POST /api/providers/{id}/deploy`: Deploy provider app (Modal or Beam).
- `POST /api/providers/cleanup-orphaned-statuses`: Clean up orphaned provider status records.
- `POST /api/providers/state/cleanup`: Maintenance cleanup for provider state.

### Provider Discovery (`/api/v2/providers`)

- `POST /api/v2/providers/discovery`: Self-discovery endpoint for provider containers to register themselves.

### Characters (`/api/v2/characters`)

- `GET /api/v2/characters`: List all characters.
- `POST /api/v2/characters`: Create a character.
- `POST /api/v2/characters/import`: Import a SillyTavern PNG character card (V2/V3).
- `GET /api/v2/characters/{id}`: Get a character.
- `PUT /api/v2/characters/{id}`: Update a character.
- `DELETE /api/v2/characters/{id}`: Delete a character.
- `POST /api/v2/characters/{id}/avatar`: Upload character avatar.
- `GET /api/v2/characters/{id}/avatar`: Get character avatar.

### Chats (`/api/v2/chats`)

- `GET /api/v2/chats`: List all chats.
- `POST /api/v2/chats`: Create a chat session.
- `GET /api/v2/chats/{id}`: Get a chat.
- `PATCH /api/v2/chats/{id}`: Update a chat.
- `DELETE /api/v2/chats/{id}`: Delete a chat (cascades messages).
- `GET /api/v2/chats/{id}/messages`: List messages for a chat.
- `POST /api/v2/chats/{id}/messages`: Send a message (triggers LLM reply if role=user).
- `DELETE /api/v2/chats/{id}/messages/{msg_id}`: Delete a message.
- `POST /api/v2/chats/{id}/scene`: Generate a scene image from chat context.

### Lorebooks (`/api/v2/lorebooks`)

- `GET /api/v2/lorebooks`: List all lorebooks.
- `POST /api/v2/lorebooks`: Create a lorebook.
- `GET /api/v2/lorebooks/{id}`: Get a lorebook.
- `PUT /api/v2/lorebooks/{id}`: Update a lorebook.
- `DELETE /api/v2/lorebooks/{id}`: Delete a lorebook (cascades entries).
- `GET /api/v2/lorebooks/{id}/search?q=`: Semantic search lorebook entries.
- `GET /api/v2/lorebooks/{id}/entries`: List entries.
- `POST /api/v2/lorebooks/{id}/entries`: Create an entry (auto-embeds).
- `PUT /api/v2/lorebooks/{id}/entries/{eid}`: Update an entry.
- `DELETE /api/v2/lorebooks/{id}/entries/{eid}`: Delete an entry.

### Scenarios (`/api/v2/scenarios`)

- `GET /api/v2/scenarios`: List all scenarios.
- `POST /api/v2/scenarios`: Create a scenario.
- `GET /api/v2/scenarios/{id}`: Get a scenario.
- `PUT /api/v2/scenarios/{id}`: Update a scenario.
- `DELETE /api/v2/scenarios/{id}`: Delete a scenario.

### Stories (`/api/v2/stories`)

- `GET /api/v2/stories`: List all stories.
- `POST /api/v2/stories`: Create a story.
- `GET /api/v2/stories/{id}`: Get a story.
- `PUT /api/v2/stories/{id}`: Update a story.
- `DELETE /api/v2/stories/{id}`: Delete a story (cascades chapters).
- `GET /api/v2/stories/{id}/chapters`: List chapters.
- `POST /api/v2/stories/{id}/chapters`: Create a chapter.
- `GET /api/v2/stories/{id}/chapters/{cid}`: Get a chapter.
- `PUT /api/v2/stories/{id}/chapters/{cid}`: Update a chapter.
- `DELETE /api/v2/stories/{id}/chapters/{cid}`: Delete a chapter.
- `POST /api/v2/stories/{id}/chapters/{cid}/continue`: AI continues the story.
- `POST /api/v2/stories/{id}/chapters/{cid}/beats`: Add a story beat.
- `POST /api/v2/stories/{id}/chapters/{cid}/illustrate`: Generate chapter illustration.

### LLM Config (`/api/v2/llm`)

- `GET /api/v2/llm/default-provider`: Get the default LLM provider.
- `PUT /api/v2/llm/default-provider`: Set the default LLM provider.
- `GET /api/v2/llm/available-models`: List available LLM models.

### Collections (`/api/collections`)

- `GET /api/collections`: List all collections.
- `POST /api/collections`: Create a new collection.
- `GET /api/collections/{collection_id}`: Get collection details.
- `PUT /api/collections/{collection_id}`: Update a collection.
- `DELETE /api/collections/{collection_id}`: Delete a collection.
- `POST /api/collections/{collection_id}/images`: Add images to a collection.
- `DELETE /api/collections/{collection_id}/images`: Remove images from a collection.
- `POST /api/collections/import`: Import collections.
- `GET /api/collections/export`: Export collections.

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
- `GET /api/view/{path}`: Serve an output image by relative path.
- `GET /api/thumbnail/{size}/{filename}`: Serve a thumbnail by size and filename.
- `POST /api/upload`: Upload an image file.
- `POST /api/upload/input`: Upload an input file.
- `POST /api/upload/mask`: Upload a mask file.
- `POST /api/batch/delete`: Batch delete files.
- `GET /api/files/proxy/{provider_id}/{path}`: Proxy file access from a provider.
- `POST /api/files/metadata/batch`: Get metadata for multiple files in batch.



### Health

- `GET /api/health`: Health check endpoint.

### Metrics

- `GET /metrics`: Prometheus metrics endpoint.

### WebSocket

- Endpoint: `ws://localhost:8002/socket.io` (Socket.IO transport).
- Clients subscribe to job/provider events and receive real-time updates (created, progress, completed, failed, cancelled).
