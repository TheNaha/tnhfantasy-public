# Chat Workflow Improvement Plan

## Status: COMPLETE ✅

All four improvements have been implemented and verified.

---

## Task 1: Continuation Variant Support ✅

**Changed:** `backend_v2/services/job_processing.py`

The continuation flow now resolves the `continuation` builtin agent (and its active variant) instead of using a hardcoded prompt:

- Resolves `resolve_agent(session, "continuation", require_enabled=False)`
- Renders the continuation agent's variant-aware prompt template via `render_agent_template()`
- Falls back to the existing hardcoded continuation prompt if the agent is disabled
- Applies the continuation agent's sampler overrides on top of chat samplers
- Records `agent_slug` and `agent_variant_slug` in continuation job metadata
- Logs `agent_slug` and `variant_slug` in the `laya_continuation_triggered` log line

**Tests added:**
- `test_parse_director_result_resolves_custom_agent_variant` (variant resolution works for any agent slug)

---

## Task 2: LLM Management Introspection APIs ✅

**Changed:** `backend_v2/api/routes/world_vault/llm_config.py`

Added two new introspection endpoints:

1. `GET /llm/providers/health` — Aggregate health check across all LLM/hybrid providers. Runs checks in parallel via `asyncio.gather`. Returns per-provider `{provider_id, provider_type, enabled, healthy, models, latency_ms, error, worker_url}` plus `healthy_count` and `total_count` summaries.

2. `GET /llm/agents/with-variants` — Returns all agent profiles together with their variant lists, active variant slug, and resolved prompt template. Each entry includes full variant details (id, slug, name, description, template, samplers, is_active, selection_hint, tags).

Both routes are registered under both `/llm` and `/world-vault/llm` prefixes (matching the existing pattern).

**Tests added:**
- `test_providers_health_aggregate` — verifies health endpoint returns correct structure
- `test_agents_with_variants` — verifies agents endpoint returns profiles with variants

---

## Task 3: Multi-Variant Evaluation for All Agents ✅

**Changed:** `backend_v2/services/laya_questions.py`

Extended `resolve_stage_questions()` and `list_all_pipeline_questions()` to inject variant choice questions for **any** enabled agent that has prompt variants, not just `character` and `narrator`:

- For each agent (excluding `user`, `character`, `narrator`) with variants that have selection hints, injects a `{agent_slug}_variant` choice question
- Laya now evaluates variant fit for custom agents (e.g., `alchemist_variant`, `illustrator_variant`) during triage
- `parse_director_result()` already handles `{next_speaker}_variant` for any agent slug

**Tests added:**
- `test_variant_questions_injected_for_custom_agents` — verifies custom agent variants appear in triage questions
- `test_parse_director_result_resolves_custom_agent_variant` — verifies variant resolution for custom agents

---

## Task 4: Audit & Fix ✅

**Verification:**
- 90 chat workflow tests pass (multi_agent_workflow, agent_variants, agent_profiles, director_and_updater, orchestrator_service, roleplay_wiring_regressions, job_runner_orchestration)
- Ruff lint passes on all 4 modified files
- Pre-existing `test_app_boot_smoke.py` route-count failure confirmed unrelated to these changes (fails on unmodified code too)

---

## Files Modified

| File | Changes |
|------|---------|
| `services/job_processing.py` | Continuation flow uses continuation agent variant prompt |
| `services/laya_questions.py` | Variant questions injected for all agents with variants |
| `api/routes/world_vault/llm_config.py` | New `/llm/providers/health` and `/llm/agents/with-variants` endpoints |
| `tests/test_director_and_updater.py` | 4 new tests covering health, agents-with-variants, variant questions |

## No New Migrations Required

The `continuation` builtin agent already existed in migrations (line 5140-5150). No DB schema changes needed.

## Frontend Integration

The LLM Studio (`/llm-studio`) already exists with tabs for workflow, agents, gates, questions, traces, cluster, runtime, and simulator. New backend endpoints are available for frontend consumption:
- `/api/v2/llm/providers/health` — aggregate provider health
- `/api/v2/llm/agents/with-variants` — agents with variant details

Frontend hooks would need to be added to consume these endpoints for the dashboard view.
