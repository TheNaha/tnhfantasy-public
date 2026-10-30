# Design

## Context

The provider system already exists across `deployables/` (cloud worker source), `backend_v2/services/engines/` (in-process engine clients), `remote_agent/provider_core.py` (forked worker runtime), and `backend_v2/services/load_balancer.py` (selection + health gating). Two contract tests already pin deployable↔engine parity and provider_core fork parity. There is no single spec stating the provider contract or what `enabled: false` means. See `proposal.md` - Why for motivation.

## Goals / Non-Goals

**Goals:**

- A capability spec for `provider-system` centralizing the provider contract so engine/deployable drift and health-misclassification are detectable.
- Requirements precise enough to anchor future machine-checkable tests (deployable mapping, fork parity, healthy-only dispatch).

**Non-Goals:**

- Changing engine code, deployable configuration, or load balancer logic.
- Unifying `provider_worker_core` with `remote_agent/provider_core` (explicitly forbidden).
- Adding new providers or deployables.

## Decisions

### Decision: Keep the provider_worker_core / remote_agent/provider_core fork

**Approach:** Spec that the two trees remain separate with a pinned parity contract; never unify them.

**Rationale:** The project already enforces this via `test_provider_core_parity.py` and explicitly states "do NOT unify." The spec documents the existing rule.

**Alternatives considered:**
- Unifying the two trees into one shared module: explicitly rejected by project convention.

### Decision: `enabled: false` means paused intentionally, never broken

**Approach:** Spec that `enabled: false` is a user pause (cost, billing, maintenance) and must not be treated as broken or trigger "needs attention."

**Rationale:** Project convention states this explicitly; treating it as broken would cause false alarms and unwanted deletions.

**Alternatives considered:**
- Treating `enabled: false` as a degraded-but-working state: rejected, because it would still trigger attention signals the project wants to avoid.

### Decision: Load balancer dispatch gates on `status == "healthy"`

**Approach:** Spec that only providers with `status == "healthy"` are eligible for dispatch, and class-level state does not accumulate untracked async tasks.

**Rationale:** `load_balancer.py` gates on healthy status and `LoadBalancer` keeps class-level state; making this explicit prevents dispatch to degraded providers.

**Alternatives considered:**
- Dispatching to degraded providers with a warning: rejected, because it risks silent job failures.

## Risks / Trade-offs

- [Risk] Deployable-engine mapping could drift as new engines are added without updating `deployables/README.md`. [Mitigation] The spec requires each engine to map to a deployable; a future contract test can verify.
- [Risk] `enabled: false` could be confused with unhealthy status by operators. [Mitigation] The spec draws a hard distinction.

## Migration Plan

None — additive spec only, no data migration, no behavior change, no rollback needed.

## Open Questions

None.
