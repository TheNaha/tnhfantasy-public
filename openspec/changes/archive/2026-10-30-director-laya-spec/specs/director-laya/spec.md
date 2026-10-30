# Spec Delta

## Purpose

Defines the behavior contract for the System 1 Director: its four-tier provider cascade, the 13-question decision rubric, fate and skill checks, agent/variant routing, image trigger threshold, engine stamps, and frontend engine classification.

## ADDED Requirements

### Requirement: Four-tier provider cascade

The Director SHALL evaluate decisions across exactly four tiers in order: remote agent (`/v1/decisions`), in-process CPU LayaRunner, structured generative fallback on the util LLM, and deterministic heuristic fallback. The Director never fails or blocks a roleplay turn.

#### Scenario: Remote agent primary

- **WHEN** a remote agent is configured and reachable with a `/v1/decisions` endpoint
- **THEN** the Director uses it as tier 1 and stamps `engine_used` with the provider id

#### Scenario: Fallback to LayaRunner

- **WHEN** the remote agent is unavailable or not configured
- **THEN** the Director falls back to the in-process CPU LayaRunner (or generative/util fallback when Laya is not installed)

#### Scenario: Heuristic never blocks

- **WHEN** all higher tiers are unavailable
- **THEN** the Director still returns a deterministic heuristic decision so the turn proceeds

### Requirement: 13-question decision rubric

Each Director decision SHALL answer all 13 typed questions: next_speaker, continue_chain, pacing_directive, scene_tension, pacing_speed, emotional_tone, trigger_image, and 5 Statekeeper gates.

#### Scenario: All 13 questions answered

- **WHEN** the Director evaluates a turn
- **THEN** the result contains keys for next_speaker, continue_chain, pacing_directive, scene_tension, pacing_speed, emotional_tone, trigger_image, gate_character_mood, gate_scene_tone, gate_relationship_dynamic, gate_character_outfit, gate_current_activity, gate_physical_condition

#### Scenario: Speaker options adapt to scene

- **WHEN** a secondary character is present in the scene
- **THEN** `next_speaker` options include `secondary_character`; otherwise it does not

### Requirement: Fate and skill anti-godmoding check

Triage SHALL execute a Fate & Skill anti-godmoding check before routing, and Laya-picked matched skills SHALL gate into the fate check.

#### Scenario: Fate check runs at triage

- **WHEN** a roleplay turn is being routed
- **THEN** the fate check evaluates character skills against the action before deciding next speaker

### Requirement: Agent and variant routing

The Director SHALL route to an agent (Character, Narrator, or Custom Agent) and resolve an AgentPromptVariant via `variant:<slug>` when one is active for that agent.

#### Scenario: Variant resolution

- **WHEN** an AgentPromptVariant is active for the routed agent
- **THEN** the variant's prompt and samplers override the defaults for that generation

### Requirement: Image trigger threshold

The Director SHALL set `trigger_image` as a probability 0.0–1.0; illustration fires when it crosses the configured threshold (0.65).

#### Scenario: Image trigger at threshold

- **WHEN** `trigger_image` is at or above IMAGE_TRIGGER_THRESHOLD
- **THEN** the Illustrator stage formulates a ComfyUI visual prompt for the scene

### Requirement: Engine stamps and frontend classification

Every Director decision SHALL carry `engine_used` with a provider id after a colon (e.g. `remote_agent:modal`). The frontend SHALL classify stamps into `live`, `reduced`, `heuristic`, or `off` levels and color panels accordingly.

#### Scenario: Frontend colors engine health

- **WHEN** a decision carries `engine_used: remote_agent:modal`
- **THEN** the decision panel shows a `live` level chip (emerald tone)

#### Scenario: Fallback shows reduced level

- **WHEN** a decision comes from the deterministic heuristic tier
- **THEN** the decision panel shows a `heuristic` level chip (amber tone)
