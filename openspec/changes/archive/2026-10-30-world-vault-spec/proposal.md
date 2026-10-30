# Proposal

## Why

The World Vault is the shared data layer behind all three pillars (image generation, roleplay chat, story sandbox), but its data model — Characters, Chats, Lorebooks, Stories, Personas, Jobs, Providers — has no single behavior contract. Schema drift between SQLModel definitions, API request/response payloads, migration DDL in `infrastructure/migrations/steps.py`, and JSON workflow envelopes silently breaks turns and exports. A capability-owned spec is needed so CI can detect mismatches before they reach production.

## What Changes

- Create capability spec `specs/world-vault/spec.md` documenting the World Vault data model contract: entity schemas, API payloads, migrations, reference cleanup rules, and persona/character/chat relationships.
- No implementation changes; this spec pins existing behavior.

## Capabilities

### New Capabilities

- `world-vault`: The World Vault data layer contract — entity schemas (Characters, Chats, Lorebooks, Stories, Personas, Jobs, Providers), API payloads, migrations, reference cleanup, and cross-entity relationships.

### Modified Capabilities

- None.

## Impact

- `backend_v2/core/entities.py` — SQLModel entity definitions.
- `backend_v2/infrastructure/migrations/steps.py` — migration DDL steps.
- `backend_v2/infrastructure/repositories.py` — repository layer.
- `backend_v2/services/reference_cleanup.py` — Story+Chat reference scrubbing.
- `backend_v2/api/routes/world_vault/` — World Vault routes (registered in `__init__.py`).
- `backend_v2/core/events.py` — emit_job_event event surface.
