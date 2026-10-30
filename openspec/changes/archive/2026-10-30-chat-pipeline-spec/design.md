# Design

## Context

The chat pipeline's limits were centralized into `backend_v2/core/pipeline_limits.py` to eliminate four copies of "4 turns" that had to be changed by hand together. `services/chat_pipeline.py` is the authoritative manifest declaring stage order and quoting limits; `core/pipeline_limits.py` is the leaf module the code imports. However, nothing machine-checks that they stay in sync. When a limit is edited in one place but not another, roleplay turns can break with schema/JSON mismatches that are hard to trace. See `proposal.md` - Why for motivation.

## Goals / Non-Goals

**Goals:**

- A backend test that fails CI when any limit source diverges from the others.
- The test covers `MAX_AUTONOMOUS_TURNS`, `IMAGE_TRIGGER_THRESHOLD`, `UPDATER_GATE_THRESHOLD`, and total-attempts-per-turn.
- Sources compared: manifest (`services/chat_pipeline.py`), limits module (`core/pipeline_limits.py`), `Chat.max_autonomous_turns` column default (`core/entities.py`), and executor/stage code (`pipeline_runner.py`, `pipeline_stages.py`).

**Non-Goals:**

- Changing any pipeline behavior, limit value, or stage ordering.
- Enforcing limits at runtime (the code already reads from `pipeline_limits`; this test only pins consistency).
- Extending the pattern to other capabilities in this change.

## Decisions

### Decision: Compare values by import and AST inspection rather than string matching

**Approach:** Import `core.pipeline_limits` and `core.entities` directly to read numeric values. Parse `services/chat_pipeline.py` with the `ast` module to extract quoted limit numbers from the manifest docstring/comments. Inspect `pipeline_runner.py` and `pipeline_stages.py` for hardcoded numeric literals matching the known limits.

**Rationale:** Importing is the most robust way to compare the limits module and entity default; they're Python values, not strings. AST parsing the manifest avoids brittle regex on prose while still catching a changed quoted number.

**Alternatives considered:**
- String/regex matching on all four files: fragile to whitespace and comment changes; rejected.
- A single canonical JSON/YAML limits file that everything reads from: would require implementation changes across the pipeline; out of scope for this change (non-goal).
- Duplicating limits into a test fixture: recreates the drift problem; rejected.

### Decision: The test asserts agreement, it does not choose the canonical value

No source is declared "the winner" if they disagree — the test simply fails and reports which sources differ. A human decides which value is correct and updates all sources.

**Rationale:** Picking a canonical source would itself be a behavior decision; this test guards consistency, not correctness of a particular number.

## Risks / Trade-offs

- [Risk] A legitimate limit change requires updating the test's expected values alongside the four sources, or the test fails. [Mitigation] The test is small and obvious; any PR touching a pipeline limit will naturally touch the test.
- [Risk] AST parsing of the manifest could miss a quoted limit if it's expressed in an unusual form. [Mitigation] Keep the manifest's limit declarations in a consistent, simple form the AST check can recognize; if the manifest format changes, update the parser.
- [Trade-off] The test imports backend modules, so it requires the backend test environment (SQLite fixtures, conftest). [Mitigation] This is already true of the existing backend test suite.

## Migration Plan

No data migration, no schema change, no behavior change. The spec and test are additive. Deploy by merging; no rollback needed beyond reverting the change.

## Open Questions

None. All design decisions are resolved; nothing deferred here would change the specs, approach, or task breakdown.
