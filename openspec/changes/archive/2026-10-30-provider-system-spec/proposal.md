# Proposal

## Why

The provider system lets the backend run inference against Modal, Beam, direct_url, and remote_agent workers, but its contract lives in three trees that can drift: `deployables/` (the only source for cloud workers), `backend_v2/services/engines/` (in-process engine clients), and `remote_agent/provider_core.py` (the forked worker runtime). The two contract tests (`test_deployable_contract.py`, `test_provider_core_parity.py`) already pin some of this, but nothing centralizes what each engine must expose, how health is determined, or what the load balancer gates on. A capability-owned spec is needed so provider drift is caught before jobs fail silently.

## What Changes

- Create capability spec `specs/provider-system/spec.md` documenting the provider contract: engine interfaces, deployable mapping, health checks, load balancer gating, and the fork between `provider_worker_core` and `remote_agent/provider_core`.
- No implementation changes; this spec pins existing behavior.

## Capabilities

### New Capabilities

- `provider-system`: The provider contract — Modal/Beam/remote_agent engines, deployable mapping, health checks, load balancer gating, and the `provider_worker_core` ↔ `remote_agent/provider_core` fork.

### Modified Capabilities

- None.

## Impact

- `backend_v2/services/engines/` — in-process engine clients (modal_llm, beam_llm, remote_agent, etc.)
- `deployables/` — cloud worker source (Modal/Beam apps + Beam deployments)
- `remote_agent/provider_core.py` — forked worker runtime
- `backend_v2/services/load_balancer.py` — provider selection and health gating
- `backend_v2/tests/test_deployable_contract.py` — existing contract test
- `backend_v2/tests/test_provider_core_parity.py` — existing parity test
