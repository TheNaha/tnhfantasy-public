# chat-pipeline Specification

## Purpose

Defines the behavior contract for the six-stage manifest-driven roleplay chat pipeline and its centralized numeric limits, so that no limit can drift between the manifest, the limits module, the entity default, and the executor without CI failing.

## Requirements

### Requirement: Pipeline stage ordering is manifest-driven

The six stages of the roleplay chat pipeline — triage, act, audit, update, illustrate, chain — and their run order come exclusively from `services/chat_pipeline.py`. No executor or runner may reorder, skip, or insert stages outside that manifest.

#### Scenario: Runner walks the graph declared in the manifest

- **WHEN** `pipeline_runner.run_from` executes a chat turn
- **THEN** it walks only the stages listed in `services/chat_pipeline.py`'s `next_stages` declarations, in that order

### Requirement: Pipeline numeric limits have a single source of truth

Every numeric limit the chat pipeline enforces (MAX_AUTONOMOUS_TURNS, IMAGE_TRIGGER_THRESHOLD, UPDATER_GATE_THRESHOLD, total-attempts-per-turn) is defined in exactly one module: `core/pipeline_limits.py`. No other module may redefine or duplicate these values.

#### Scenario: Manifest and limits module agree on MAX_AUTONOMOUS_TURNS

- **WHEN** `services/chat_pipeline.py` quotes `max_autonomous_turns: 4`
- **THEN** `core/pipeline_limits.MAX_AUTONOMOUS_TURNS` equals 4

#### Scenario: Limits module and entity default agree

- **WHEN** `core/pipeline_limits.MAX_AUTONOMOUS_TURNS` equals 4
- **THEN** the `Chat.max_autonomous_turns` column default equals 4

### Requirement: Stages and executors read limits from the source of truth

`pipeline_runner.py` and `pipeline_stages.py` must read every pipeline limit from `core.pipeline_limits` at runtime; they must not contain hardcoded numeric literals for MAX_AUTONOMOUS_TURNS, IMAGE_TRIGGER_THRESHOLD, UPDATER_GATE_THRESHOLD, or total-attempts-per-turn.

#### Scenario: Executor uses the limit, not a literal

- **WHEN** the chain stage checks `continuation_count` against the turn budget
- **THEN** it compares against `core.pipeline_limits.MAX_AUTONOMOUS_TURNS`, not a hardcoded number

### Requirement: Drift is machine-checkable in CI

A backend test exists that asserts the manifest, `core.pipeline_limits`, the `Chat.max_autonomous_turns` default, and the executor/stage code agree on each limit; any divergence fails CI.

#### Scenario: Contract drift test fails on mismatch

- **WHEN** any one of the four limit sources is changed without updating the others
- **THEN** the backend drift test fails
