# Proposal

## Why

AgentPromptVariant (migration 103) lets prompts and samplers be overridden per agent via a globally unique slug resolved through `variant:<slug>`, wired into job_processing, chats, and simulate. But the variant contract — slug uniqueness, activation rules, variant overlay semantics (replaces narrator/custom prompts, lands on char card), and resolution precedence — has no single behavior contract. A capability-owned spec is needed so variant drift between migration, resolution, and application surfaces before it changes agent behavior silently.

## What Changes

- Create capability spec `specs/agent-variants/spec.md` documenting the AgentPromptVariant contract: slug uniqueness, per-agent activation, `variant:<slug>` resolution, overlay semantics, and wiring into job_processing, chats, and simulate.
- No implementation changes; this spec pins existing behavior.

## Capabilities

### New Capabilities

- `agent-variants`: The AgentPromptVariant contract — slug uniqueness, per-agent active flag, `variant:<slug>` resolution, prompt+sampler overlay semantics, and wiring into job processing, chats, and simulation.

### Modified Capabilities

- None.

## Impact

- `backend_v2/services/agent_variants.py` — variant resolution and activation.
- `backend_v2/infrastructure/migrations/steps.py` — migration 103 (AgentPromptVariant).
- `backend_v2/services/job_processing.py` — variant overlay on char card.
- `backend_v2/api/routes/world_vault/chats.py` — variant in chat paths.
- `backend_v2/services/agent_simulation.py` — variant in simulate.
