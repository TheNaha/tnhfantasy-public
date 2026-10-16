# World Graph Relations + Label Cohesion Plan

Goal: Make the World Graph a real, editable relationship graph (stored edges, not just derived FK joins), keep Activity as a read-only projection (out of scope to make it a write entity), and reconcile redundant UI labels ("Play" = Chat, "Worlds" = World).

## Decisions (locked)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Add `WorldEdge` table for explicit, named relationships between any two vault entities. `GraphLayout` stays as the node position store (already has `entity_type`/`entity_id`/x/y + unique index). Nodes are the entities themselves — no separate `WorldNode` table. | `GraphLayout` already serves as the node registry. Edges are the missing piece: derived edges can't represent non-FK relationships (e.g. "character A is enemy of character B") or carry labels/weights. |
| D2 | `WorldEdge` is global (no `world_id`), matching the current `get_relationships` contract which returns all vault relationships unfiltered by world. | The derived-graph endpoint is not world-scoped; adding `world_id` would change the contract and break the frontend. |
| D3 | `WorldEdge` complements derived edges, does not replace them. The `GET /relationships` endpoint returns stored edges + derived edges (derived for backward compat with FK-based relationships not yet stored). | Avoids a breaking change; existing vaults keep working without backfilling stored edges for every FK. |
| D4 | Activity stays a **read-only projection** (messages, chapters, memories, images via `useTimeline`). No `Activity` write entity. Out of scope for this plan. | Activity.jsx already works as a feed. Making it a write entity is a much larger surface area (activity rows on every mutation) and was not requested as a new feature. |
| D5 | Label reconciliation: rename the "Roleplay a character" shortcut to "Chat" in `RoleplayWorkspace.jsx`. "Worlds" stays as "Worlds". | "Play" and "Chat" are the same table (`Chat`, `chat_type="chat"`). "Worlds" is `World`. Removing the redundant label reduces conceptual overlap. |

## Affected boundaries

Backend (`backend_v2/`):
- `core/entities.py` — new `WorldEdge` SQLModel table
- `infrastructure/migrations/steps.py` — migration step creating `world_edges` table (+ unique constraint)
- `api/routes/world_vault/graph_edges.py` — new CRUD routes (GET list, POST create, DELETE by id)
- `api/routes/world_vault/world_hub.py` — `get_relationships` includes stored edges alongside derived edges
- `services/reference_cleanup.py` — `scrub_entity_references` drops `WorldEdge` rows referencing a deleted entity (both source and target)
- `api/main.py` — register `graph_edges` router

Frontend (`frontend_v2/src/`):
- `hooks/useWorldVaultSearch.js` — `useGraphEdges`, `useCreateGraphEdge`, `useDeleteGraphEdge` hooks
- `pages/RelationshipGraph.jsx` — render stored edges + derived edges; add "link two nodes" UI; edge delete affordance
- `pages/RoleplayWorkspace.jsx` — rename "Roleplay a character" shortcut → "Chat"

Worker pipeline (`services/engines/`, `services/llm_router.py`, `services/world_integration_service.py`): **no changes** — worker routing is entity-agnostic and unaffected by graph edges.

## Data flow

```
User clicks "Link" on two nodes in RelationshipGraph
  → useCreateGraphEdge.mutate({ source_entity_type, source_entity_id,
      target_entity_type, target_entity_id, relation_type, label })
    → POST /api/v2/world-vault/graph-edges
      → WorldEdge row inserted (validated: both entities exist, no duplicate)
      → RelationshipGraph refetches edges → renders new edge line

User deletes an edge (or deletes an entity)
  → DELETE /api/v2/world-vault/graph-edges/{id}
    → WorldEdge row removed
    → (on entity delete) scrub_entity_references removes edges where
      source_entity_id or target_entity_id == deleted id

GET /api/v2/world-vault/relationships
  → stored WorldEdge rows + derived FK-based edges → merged node/edge list
    → RelationshipGraph renders nodes (from GraphLayout positions) + edges
```

## Failure modes & risks

- **Orphan edges**: deleting an entity must remove edges referencing it. Handled by adding `WorldEdge` scrub branches to `scrub_entity_references` for all 7 member kinds + `world`.
- **Duplicate edges**: unique constraint on `(source_entity_type, source_entity_id, target_entity_type, target_entity_id, relation_type)` prevents exact duplicates at the DB level; route returns 409/422 on conflict.
- **Edge to non-existent entity**: route validates both endpoint IDs exist before insert (404 otherwise).
- **Derived vs stored edge duplication**: same relationship may appear twice (once stored, once derived). Frontend dedups by `(source, target, relation_type)` key when merging.
- **Large edge sets**: cap `GET /graph-edges` list with `limit`/`offset` (same pattern as `get_relationships`: `ge=1, le=1000`).

## Rollout / migration path

1. Add migration step in `infrastructure/migrations/steps.py`: `CREATE TABLE world_edges (...)` + unique index. Version string follows existing convention (next after current max).
2. Add `WorldEdge` entity to `core/entities.py` (relationships optional — no back_populates needed; edges are standalone).
3. Create `api/routes/world_vault/graph_edges.py` with Pydantic request/response models, GET/POST/DELETE routes. Register in `api/main.py`.
4. Update `get_relationships` in `world_hub.py` to append stored edges to the derived edge list.
5. Add `WorldEdge` scrub branches to `scrub_entity_references` for character, lorebook, voice, scenario, persona, world, location, chat, story (drop edges where either endpoint == deleted id).
6. Frontend: add `useGraphEdges`/`useCreateGraphEdge`/`useDeleteGraphEdge` hooks in `useWorldVaultSearch.js`.
7. Frontend: update `RelationshipGraph.jsx` to merge stored + derived edges, dedup, render edge lines, add link/delete UI.
8. Frontend: rename "Roleplay a character" → "Chat" shortcut in `RoleplayWorkspace.jsx`.
9. Run backend tests + frontend tests + lint + typecheck.

## Validation plan

- Backend: `cd backend_v2 && pytest` — existing roleplay/world tests green; new tests for `WorldEdge` CRUD, dedup in `get_relationships`, scrub-on-delete.
- Frontend: `cd frontend_v2 && npm test` + `npm run lint`.
- Lint/typecheck: `cd backend_v2 && ruff check .`; `cd frontend_v2 && npm run lint`.
- Scenario: creating an edge between two nodes shows it in the graph; deleting an entity removes its edges; derived + stored edges don't duplicate in the render.

## Open questions (deferred, not blocking)

- Whether `WorldEdge` should be world-scoped (`world_id` column) — deferred; current contract is global.
- Whether `Activity` should ever become a write entity — deferred; kept read-only per D4.

## Implementation note

This plan is implementation-ready but I cannot mutate files. Switch to an implementation-capable agent (code agent) and point it at this plan file: `.kilo/plans/1792210000003-world-graph-relations-plan.md`.
