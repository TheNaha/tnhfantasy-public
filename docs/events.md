# Real-time events — EventBus, EventType, and Socket.IO

The backend pushes real-time updates to the frontend over **Socket.IO** mounted
on `/socket.io` (one ASGI sub-app shared by all routes). Events originate on
the in-process `EventBus` (`backend_v2/core/events.py`), a singleton pub/sub
bus, and are broadcast into **topic rooms** derived from each event's type
prefix (`job`, `provider`, `model`, `reconciliation`, ...).

## EventType taxonomy

`backend_v2/core/events.py:126` `EventType(str, Enum)`. Every backend event
carries one of these; the frontend mirrors the same constants and the
cross-tree test `frontend_v2/src/test/eventContractInvariants.test.js` fails if
a backend member has no frontend counterpart (and vice versa).

### Job events

| EventType | Value | Meaning |
|---|---|---|
| `JOB_CREATED` | `job.created` | Job enqueued. |
| `JOB_UPDATED` | `job.updated` | Job fields changed (status, progress, metadata). |
| `JOB_PROGRESS` | `job.progress` | Incremental progress frame. |
| `JOB_COMPLETED` | `job.completed` | Terminal. Payload is the job's own representation; content-bearing (a paid generation's output). |
| `JOB_POST_PROCESSING` | `job.post_processing` | Post-processing (thumbnails/blurhash) underway. |
| `JOB_FAILED` | `job.failed` | Terminal. |
| `JOB_CANCELLED` | `job.cancelled` | Terminal. |

### Provider events

| EventType | Value | Meaning |
|---|---|---|
| `PROVIDER_STATUS` | `provider.status` | Provider health/connection state change. |
| `PROVIDER_STATS_UPDATE` | `provider.stats_update` | Modal stats, sync counts (replaces polling for modal-stats). |

### Model events

| EventType | Value | Meaning |
|---|---|---|
| `MODEL_STATUS_UPDATE` | `model.status_update` | Per-provider model status change (replaces polling for sync-status). |

### Reconciliation events

| EventType | Value | Meaning |
|---|---|---|
| `RECONCILIATION_STARTED` | `reconciliation.started` | Model/directory reconciliation tick began. |
| `RECONCILIATION_PROGRESS` | `reconciliation.progress` | Incremental reconciliation progress. |
| `RECONCILIATION_COMPLETED` | `reconciliation.completed` | Terminal. |
| `RECONCILIATION_FAILED` | `reconciliation.failed` | Terminal; emitted and handled nowhere until wired (see maintenance audit). |

### Model sync events

| EventType | Value | Meaning |
|---|---|---|
| `MODEL_SYNC_STARTED` | `model.sync_started` | A file download/reconcile began. |
| `MODEL_SYNC_PROGRESS` | `model.sync_progress` | Per-download progress; frontend reads `progress` (0-100), `model_name`, `directory`, `size_bytes`, `error_message`. Emitted by `in_process_reconciliation.download_single`. |
| `MODEL_SYNC_COMPLETED` | `model.sync_completed` | Terminal. |
| `MODEL_SYNC_FAILED` | `model.sync_failed` | Terminal. |

### Deliberately absent: `download.*`

There is **no** `download.*` family in `EventType`. The four members that used
to exist (`download.started`, `download.progress`, `download.completed`,
`download.failed`) plus an `emit_download_event` helper had zero production
producers and zero frontend subscribers — a contract implemented by neither
side, which read as "push progress already works". Model-download status is
served by **polling** the model-status endpoints, not pushed. Re-adding a
member requires a producer and a frontend counterpart or
`eventContractInvariants` fails.

## EventBus mechanics

`EventBus` (`backend_v2/core/events.py:212`) is a global singleton
(`event_bus` at line 527).

- **Topics** are derived from the event type prefix: `job.created` → topic
  `job`. `subscribe(topic)` / `subscribe_multiple(topics)` return async
  generators yielding `Event` objects (`{type, data, timestamp,
  sequence_number}`).
- **Replay buffer**: last 100 events kept for debugging (`get_replay_buffer`,
  `clear_replay_buffer`).
- **Non-blocking publish**: slow subscribers do not block publishers; a full
  queue drops the event unless it is terminal.
- **Terminal-event preservation** (`TERMINAL_EVENT_TYPES`: `job.completed`,
  `job.failed`, `job.cancelled`, `reconciliation.completed`,
  `reconciliation.failed`, `model.sync_completed`, `model.sync_failed`): on a
  full queue the bus evicts the oldest queued event to make room, retrying up
  to `max(3, maxsize+1)` times. An evicted `JOB_COMPLETED` is logged at
  `error` (content-bearing — a paid generation whose output trace is lost);
  `CONTENT_BEARING_EVENT_TYPES = {JOB_COMPLETED}`.
- **Drop accounting**: `get_stats()` returns subscriber counts, replay-buffer
  size, per-topic drop counts, and the last drop record.

## Emitting events

Convenience publishers (`core/events.py`):

- `emit_job_event(event_type, job_data)` — publishes `{job: job_data}` on the
  `job` topic and, on Postgres only, NOTIFYs the cross-process channel so
  sibling workers re-broadcast to their local Socket.IO clients.
- `emit_provider_event(event_type, provider_id, data)` — `{provider_id, ...}`.
- `emit_provider_stats(provider_id, stats)` — `provider.stats_update`.
- `emit_model_status_update(provider_id, file_id, status, extra)` —
  `model.status_update`.
- `emit_model_sync_event(event_type, provider_id, file_id, **fields)` — one of
  the `model.sync_*` family.

Routes and services emit through these helpers, never by sending Socket.IO
messages directly. `emit_job_event` is the job-lifecycle entry point; the LLM
path historically built payloads by hand (no `task_type`, hand-written status
strings, replaced metadata) and was moved through `update_job` so `status`
says what the job IS and the LLM sub-state travels as `phase`.

## Cross-process broadcast (multiple workers)

When `COMFY_UVICORN_WORKERS` / `WEB_CONCURRENCY` > 1, each process has its own
`EventBus` and `WebSocketManager`. Events emitted on one process must reach
clients on another, so the publisher NOTIFYs the Postgres channel:

| Constant | Value |
|---|---|
| `CROSS_PROCESS_EVENT_CHANNEL` | `tnhfantasy_job_events` |

The NOTIFY payload is deliberately small (`{"event": "<type>", "job": {"id": ...}}`)
because Postgres NOTIFY payloads are capped at 8 KB. Sibling processes that
need more detail re-read the job row from the DB. Notify failures are logged at
`debug` and never break the local event path. This only matters on Postgres;
SQLite ignores it silently.

Boot-time side effects (migrations, scheduler, asset migration, job recovery)
run N times under multiple workers but are advisory-locked and idempotent; job
dispatch is safe under `FOR UPDATE SKIP LOCKED` (the claim query requires
`jobs.enqueued_at`, so workers claim disjoint rows).

## Waiting for a terminal job state

`wait_for_job_completion(job_id, timeout=120.0, ...)` subscribes to the `job`
topic and listens for the terminal events matching `job_id`, falling back to
DB polling (run in `asyncio.to_thread`, never on the event loop) for
race-condition safety. The poll interval backs off from 2s to 15s because the
event almost always arrives first. Used by the orchestrator (LLM job worker)
with a 330s timeout.

## Frontend contract

The frontend joins Socket.IO topic rooms and updates Zustand job state in
realtime. A payload without `task_type` is dropped by the frontend's global
realtime handler (a partial payload merged into the cached job drops
`task_type` and `provider_id` and can move the status backwards), so every
job event now carries the job's own representation — including the post-processing
announcement (`_process_image_background`), which used to send a hand-built
`{id, message, images_processed}` payload that no subscriber could act on.

## Logging

Dropped events are logged: `event_dropped` at `warning` (first drop and every
50th), `content_bearing_event_dropped` at `error` (a paid generation's output
thrown away; the job id names the reply to re-drive),
`cross_process_notify_failed` at `debug`. Swallowed exceptions elsewhere in
the codebase should emit at least `logger.debug(..., exc_info=True)` rather
than `pass`.
