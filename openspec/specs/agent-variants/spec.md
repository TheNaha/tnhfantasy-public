# agent-variants Specification

## Purpose

Defines the AgentPromptVariant contract so prompt and sampler overrides per agent are applied consistently across job processing, chats, and simulation.

## Requirements

### Requirement: Slug uniqueness

Each AgentPromptVariant SHALL have a globally unique slug; no two variants may share a slug regardless of agent.

#### Scenario: Slugs are globally unique

- **WHEN** two AgentPromptVariants are created
- **THEN** their slugs differ even if they belong to different agents

### Requirement: Per-agent activation

A variant SHALL be active per agent through an `is_active` flag; only active variants are resolved for that agent.

#### Scenario: Only active variants resolve

- **WHEN** an agent has multiple variants, one active and one inactive
- **THEN** `resolve_agent()` with `variant:<slug>` returns the active variant only

### Requirement: Variant resolution

The system SHALL accept `variant:<slug>` to resolve a variant, overriding the agent's default prompt and samplers.

#### Scenario: Variant overrides prompt and samplers

- **WHEN** `resolve_agent()` receives `variant:<slug>` for an active variant
- **THEN** the variant's prompt and samplers override the agent defaults

### Requirement: Overlay semantics on char card

A variant overlay SHALL replace narrator/custom prompts and land on the char card; it does not merge with the base prompt.

#### Scenario: Variant replaces base prompt

- **WHEN** an active variant is applied to a character card
- **THEN** the variant's prompt replaces the narrator/custom prompt on the card

### Requirement: Wiring into job processing, chats, and simulate

Variants SHALL be wired into `job_processing.py`, chat paths, and `agent_simulation.py` so all three agent paths apply the same variant resolution.

#### Scenario: Variant applied consistently across paths

- **WHEN** a variant is active for an agent
- **THEN** job processing, chats, and simulation all resolve and apply the same variant
