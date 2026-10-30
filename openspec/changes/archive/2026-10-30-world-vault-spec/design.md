# Design

## Context

The World Vault data layer already exists: entities in `core/entities.py`, migrations in `infrastructure/migrations/steps.py`, repositories in `infrastructure/repositories.py`, routes under `api/routes/world_vault/`, reference cleanup in `services/reference_cleanup.py`, and events via `core/events.py`. There is no single spec stating that each entity has exactly one source of truth or how migrations relate to entity definitions. See `proposal.md` - Why for motivation.

## Goals / Non-Goals

**Goals:**

- A capability spec for `world-vault` centralizing the data layer contract so schema drift between entities, API payloads, migrations, and workflow envelopes is detectable.
- Requirements precise enough to anchor a future machine-checkable test (entity field duplication detection, migration step uniqueness).

**Non-Goals:**

- Changing any entity schema, migration, or API payload shape.
- Implementing a schema-drift test in this change.
- Cross-service data consistency beyond the World Vault.

## Decisions

### Decision: Entity schema is the single source of truth

**Approach:** Spec that `core/entities.py` owns each field definition; migrations and API serializers derive from it, not the reverse.

**Rationale:** Python imports enforce this today (`core/entities.py` imports from `pipeline_limits`; entities define defaults). Making it explicit prevents a migration from redefining a field with a conflicting type.

**Alternatives considered:**
- Making migrations the source of truth: rejected, because entities are imported at runtime by services and tests; migrations run only at startup.

### Decision: No implementation changes in this change

**Approach:** The spec documents existing behavior only.

**Rationale:** This change is a contract clarification, not a refactor. Any entity or migration change would be a separate change with its own spec delta.

## Risks / Trade-offs

- [Risk] The spec describes relationships (e.g. Story.persona_id has producers; AgentProfile too) that a future test would need to enforce, but no test exists yet. [Mitigation] The spec anchors those relationships; a test can be added later.
- [Risk] Migration DDL is hand-written (no Alembic), so a missed step leaves the DB out of sync. [Mitigation] Spec requires each step run once and be recorded in `schema_migrations`.

## Migration Plan

None — additive spec only, no data migration, no behavior change, no rollback needed.

## Open Questions

None.
