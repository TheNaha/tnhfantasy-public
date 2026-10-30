# Spec Delta

## Purpose

Defines the World Vault data layer contract so that SQLModel entity schemas, API payloads, migrations, and JSON workflow envelopes stay in sync across all three pillars.

## ADDED Requirements

### Requirement: Single source of truth for entity schemas

Each World Vault entity (Characters, Chats, Lorebooks, Stories, Personas, Jobs, Providers) SHALL be defined in exactly one place: `core/entities.py`. No API serializer or migration may redefine a field that already exists on the entity.

#### Scenario: Entity field not duplicated

- **WHEN** an entity has a field defined in `core/entities.py`
- **THEN** no migration DDL or API payload redefines that field with a different type

### Requirement: Migrations recorded and run once

Every schema change SHALL be appended as a `MigrationStep(version=..., apply_fn=...)` in `infrastructure/migrations/steps.py` and recorded in `schema_migrations`; steps run once at startup.

#### Scenario: Migration step applied once

- **WHEN** a new `MigrationStep` is added to `steps.py`
- **THEN** it runs once at startup and is recorded in `schema_migrations`, never re-run

### Requirement: Reference cleanup

When a Story or Chat is deleted, references to it in related entities SHALL be scrubbed so no dangling foreign keys remain.

#### Scenario: Story deletion scrubs references

- **WHEN** a Story is deleted
- **THEN** `reference_cleanup` removes its references from Chats and related entities without leaving orphaned IDs

### Requirement: API payload aliases match entity fields

API responses SHALL use `metadata_` aliased to `metadata` in payloads, matching the Python model convention.

#### Scenario: Metadata alias in payload

- **WHEN** an entity with `metadata_` is serialized to an API response
- **THEN** the payload exposes it as `metadata`, not `metadata_`

### Requirement: World Vault routes registered

Any new World Vault route SHALL be registered in `api/routes/world_vault/__init__.py` before it can be served.

#### Scenario: Route registration required

- **WHEN** a new World Vault endpoint is added
- **THEN** it is registered in `api/routes/world_vault/__init__.py` or it is not reachable
