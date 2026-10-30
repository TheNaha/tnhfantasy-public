# Proposal

## Why

The Director (System 1 decision maker) uses a four-tier provider cascade — remote agent, in-process CPU LayaRunner, structured generative fallback on the util LLM, and deterministic heuristic — to decide next speaker, pacing, gates, and image triggers on every roleplay turn. Its contract is currently scattered across `services/decision_service.py`, `services/decision_schema.py`, `services/laya_runner.py`, and the frontend `directorEngine.js`. Nothing centralizes what each tier must guarantee, how routing decisions map to agents/variants, or how the frontend should reflect engine health. A capability-owned spec is needed so CI can detect drift between tiers (e.g. the Director says "illustrate" but the Illustrator never fires, or the engine stamp is misclassified in the panel).

## What Changes

- Create capability spec `specs/director-laya/spec.md` documenting the Director contract: four-tier cascade, 13-question rubric, fate & skill anti-godmoding check, routing to agent/variant, image trigger threshold, engine stamps, and frontend classification.
- No implementation changes; this spec and the change artifacts pin existing behavior.

## Capabilities

### New Capabilities

- `director-laya`: The System 1 Director decision contract — four-tier provider cascade, 13-question decision schema, fate check, agent/variant routing, trigger_image threshold, engine stamps, and frontend `directorEngine.js` classification.

### Modified Capabilities

- None.

## Impact

- `backend_v2/services/decision_service.py` — DecisionService, four-tier cascade.
- `backend_v2/services/decision_schema.py` — build_director_questions, heuristic_director_decision, resolve_fate_check.
- `backend_v2/services/laya_runner.py` — LayaRunner CPU execution.
- `frontend_v2/src/utils/directorEngine.js` — classifyDirectorEngine, engine levels.
- New backend test (optional follow-up): cascade tier drift detection.
