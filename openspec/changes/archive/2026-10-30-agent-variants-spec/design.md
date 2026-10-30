# Design

## Context

AgentPromptVariant already exists via migration 103 (globally unique slug, per-agent `is_active`, `variant:<slug>` resolution), wired into `job_processing.py`, chat paths, and `agent_simulation.py`. There is no single spec stating slug uniqueness, activation, or overlay semantics. See `proposal.md` - Why for motivation.

## Goals / Non-Goals

**Goals:**

- A capability spec for `agent-variants` centralizing the variant contract so drift between migration, resolution, and application is detectable.
- Requirements precise enough to anchor future machine-checkable tests (slug uniqueness, variant resolution precedence, overlay semantics).

**Non-Goals:**

- Changing variant resolution code or migration 103.
- Adding new variant fields or activation modes.
- Changing how variants affect sampling parameters beyond what migration 103 already defines.

## Decisions

### Decision: Variant overrides, does not merge

**Approach:** Spec that an active variant's prompt and samplers replace the agent defaults on the char card; they do not merge with the base prompt.

**Rationale:** Project memory confirms variants "REPLACE narrator/custom prompts" and land on the char card. Making this explicit prevents a future merge-based implementation from silently changing behavior.

**Alternatives considered:**
- Deep-merging variant with base prompt: rejected, because project memory states replace semantics.

### Decision: Wiring into all three agent paths

**Approach:** Spec that `job_processing.py`, chat paths, and `agent_simulation.py` all resolve and apply the same variant via `variant:<slug>`.

**Rationale:** Project memory confirms variants are wired into all three; spec makes this a requirement so a future change doesn't wire only one path.

**Alternatives considered:**
- Wiring variants into only job processing: rejected, because chats and simulate would then diverge.

## Risks / Trade-offs

- [Risk] Slug uniqueness across agents could be violated if two variants for different agents use the same slug. [Mitigation] Spec requires global uniqueness; migration 103 already enforces it.
- [Risk] An inactive variant could still be referenced by `variant:<slug>` if resolution doesn't check `is_active`. [Mitigation] Spec requires activation check; resolution code already does this.

## Migration Plan

None — additive spec only, no data migration, no behavior change, no rollback needed.

## Open Questions

None.
