# Proposal

## Why

The roleplay chat pipeline's limits live in more than one place: the manifest in `services/chat_pipeline.py`, the leaf module `core/pipeline_limits.py`, the `Chat.max_autonomous_turns` column default in `core/entities.py`, and hardcoded literals in the executor. They were once four separate copies of "4 turns" that had to be changed by hand together. Centralizing into `pipeline_limits.py` fixed the duplication, but nothing enforces that they stay in sync. As the project ships features quickly, a limit edited in one place but not another will silently drift and cause schema/JSON mismatches that break roleplay turns end-to-end. We need a centralized, capability-owned spec for the chat pipeline that states each limit's single source of truth, plus a machine-checkable test that fails CI when they diverge.

## What Changes

- Create capability spec `specs/chat-pipeline/spec.md` documenting the chat pipeline contract: six stages, the single-source-of-truth limits module, and the requirement that no stage or executor hardcodes a limit the manifest does not quote.
- Add a machine-checkable backend test that asserts the manifest, `core.pipeline_limits`, the `Chat.max_autonomous_turns` default, and the executor/stage code agree on each limit (MAX_AUTONOMOUS_TURNS, IMAGE_TRIGGER_THRESHOLD, UPDATER_GATE_THRESHOLD, total-attempts-per-turn).
- No implementation changes to pipeline behavior; this spec and test pin existing behavior.

## Capabilities

### New Capabilities

- `chat-pipeline`: The six-stage manifest-driven roleplay chat pipeline (triage → act → audit → update → illustrate → chain), its centralized limits in `core/pipeline_limits.py`, and the rule that every limit has exactly one source of truth enforced by a CI test.

### Modified Capabilities

- None.

## Impact

- `backend_v2/services/chat_pipeline.py` — the authoritative manifest; source of stage ordering and stage metadata.
- `backend_v2/core/pipeline_limits.py` — the leaf limits module; single source of truth for pipeline numbers.
- `backend_v2/core/entities.py` — `Chat.max_autonomous_turns` column default; must match `MAX_AUTONOMOUS_TURNS`.
- `backend_v2/services/pipeline_runner.py` / `pipeline_stages.py` — executors; must read limits from `pipeline_limits`, not hardcoded literals.
- New backend test under `backend_v2/tests/` for contract drift detection.
