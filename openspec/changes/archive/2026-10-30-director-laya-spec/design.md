# Design

## Context

The Director is already implemented across `services/decision_service.py` (cascade), `services/decision_schema.py` (13-question rubric), `services/laya_runner.py` (CPU execution), and `frontend_v2/src/utils/directorEngine.js` (engine-level classification). There is no single spec that states what each tier guarantees or how the frontend classifies engine stamps. See `proposal.md` - Why for motivation.

## Goals / Non-Goals

**Goals:**

- A capability spec for `director-laya` that centralizes the Director contract so drift between tiers is detectable.
- Requirements precise enough to anchor a future machine-checkable test (cascade tier drift, engine stamp classification).

**Non-Goals:**

- Adding new tiers, changing cascade order, or altering decision values.
- Implementing a cascade-drift test in this change (the spec can anchor one later).
- Frontend changes beyond documenting the existing `directorEngine.js` contract.

## Decisions

### Decision: Spec the existing cascade as-is, do not restructure

**Approach:** Document the four tiers (remote agent → LayaRunner → generative/util → heuristic) exactly as they exist; add no new tier and no reordering.

**Rationale:** The cascade works end-to-end and the heuristic never blocks turns. Restructuring would be an implementation change, not a spec clarification.

**Alternatives considered:**
- Introducing a "shadow mode" tier that runs a secondary decision in parallel for comparison: out of scope for a spec-only change.

### Decision: Frontend engine classification is part of the spec

**Approach:** The `directorEngine.js` `live`/`reduced`/`heuristic`/`off` levels are included as a requirement because engine health visibility is user-facing behavior, not implementation detail.

**Rationale:** The panel currently colors all stamps the same green whether live or fallback, which misleads users about director health. Specifying honest classification is a contract clarification.

**Alternatives considered:**
- Leaving classification entirely out of scope: rejected, because the spec's purpose is to make drift detectable, and frontend misclassification is a form of drift.

## Risks / Trade-offs

- [Risk] The spec describes behavior that a future CI test would need to enforce, but no test exists yet. [Mitigation] The spec itself is the anchor; a test can be added later under a new change.
- [Risk] Remote agent tier behavior depends on network/worker availability that varies by deployment. [Mitigation] Spec states the tier "never blocks" via fallback, which holds across deployments.

## Migration Plan

None — additive spec only, no data migration, no behavior change, no rollback needed.

## Open Questions

None.
