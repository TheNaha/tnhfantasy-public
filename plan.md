## Plan: Codebase Audit Remediation

Stabilize the codebase by first fixing contract and state-management drift, then reducing architectural duplication, then adding the tests and guardrails needed for multi-person or multi-agent maintenance. The recommended approach is to treat this as a staged modernization rather than a single refactor: Phase 1 addresses correctness and integration bugs, Phase 2 unifies the main divergent systems, Phase 3 hardens the codebase with tests, validation, and shared conventions.

**Steps**
1. Phase 1: establish a verified baseline and issue backlog from the current audit. Convert the findings below into tracked work items with severity, affected surface, and expected regression tests. This phase blocks implementation prioritization.
2. Phase 1: add contract and observability guardrails around realtime and provider interactions. Define canonical payload shapes for job events, provider error responses, and model status updates. Add backend logging/metrics for dropped EventBus messages, provider retries, and queue recovery outcomes. This can run in parallel with step 3.
3. Phase 1: fix backend correctness hotspots that can corrupt behavior under load. Refactor backend_v2/services/load_balancer.py away from class-level mutable state plus threading.RLock; split retry/failover logic out of backend_v2/api/main.py into a dedicated strategy/policy module; make backend_v2/services/job_queue.py perform graceful shutdown and explicit inflight reconciliation; verify backend_v2/infrastructure/database.py migrations after execution.
4. Phase 1: fix frontend realtime/server-state integration boundaries. Make frontend_v2/src/store/jobStore.js responsible only for websocket-driven job state; keep gallery and other server data in React Query; audit all invalidation paths in frontend_v2/src/pages/Dashboard.jsx and related hooks so websocket completions cannot leave gallery data stale. This depends on step 2’s event contract.
5. Phase 2: remove system duplication in model management. Choose V2 as the single canonical model system, deprecate the V1 model API/service/entity flow in backend_v2/core/entities.py and backend_v2/services/model_service.py, migrate remaining callers to backend_v2/core/entities_v2.py plus backend_v2/services/model_service_v2.py, and document a clear retirement path for /api/models versus /api/v2/models. This depends on step 1 and should be done before major new model features.
6. Phase 2: centralize shared domain mappings and error handling. Extract one model-directory/type mapping module used by backend parser logic, V2 services, and provider workers; add a FastAPI exception translation layer so routes stop mixing raw HTTPException handling with ComfyError subclasses; remove hardcoded backend/provider URLs by routing them through config/env. Steps 5 and 6 can proceed in parallel once the canonical model system decision is confirmed.
7. Phase 2: reduce maintainability friction in the frontend composition. Replace repeated websocket subscription patterns across stores with a shared sync abstraction or event layer; separate persisted preferences from ephemeral UI state; reduce large callback prop surfaces in frontend_v2/src/pages/Dashboard.jsx by introducing a scoped context or feature module boundary. This can run in parallel with step 6.
8. Phase 3: add missing automated coverage for the highest-risk flows. Add backend integration tests for job submission to provider response to image save to websocket event, provider failover, migration verification, EventBus overflow, and recovery-on-restart. Add frontend tests for websocket reconnection/deduplication, gallery invalidation on job completion, partial model-load failures, and long-lived subscription cleanup. This depends on steps 2 through 7 enough to avoid locking in broken behavior.
9. Phase 3: align documentation and contributor conventions. Update docs to reflect the canonical model path, config precedence, deployment variables, websocket/query boundaries, and testing commands or caveats on Windows. Add a short engineering guide covering service/repository boundaries, event contracts, naming, and where realtime side effects are allowed.
10. Phase 3: finish with performance validation and regression verification. Stress-test provider selection, websocket event delivery, queue recovery, model listing, and gallery refresh behavior under concurrent jobs; tune connection pools, queue sizes, and cache settings based on measured behavior rather than defaults.

**Relevant files**
- w:/containers/comfyui/backend_v2/api/main.py — extract provider retry/failover and image-processing orchestration concerns from the monolithic job-processing path
- w:/containers/comfyui/backend_v2/services/load_balancer.py — replace class-level in-memory balancing state and blocking lock strategy
- w:/containers/comfyui/backend_v2/services/job_queue.py — implement graceful shutdown, clearer recovery policy, and testable lifecycle hooks
- w:/containers/comfyui/backend_v2/core/events.py — define explicit queue overflow strategy, metrics, and subscriber semantics
- w:/containers/comfyui/backend_v2/infrastructure/database.py — verify migrations after manual ALTERs or prepare migration framework adoption
- w:/containers/comfyui/backend_v2/core/entities.py — retire V1 model concerns and keep only still-supported legacy entities if needed
- w:/containers/comfyui/backend_v2/core/entities_v2.py — canonical model schema and shared model-type mapping target
- w:/containers/comfyui/backend_v2/services/model_service.py — deprecate or remove once V1 model flow is retired
- w:/containers/comfyui/backend_v2/services/model_service_v2.py — consolidate all model orchestration here after migration
- w:/containers/comfyui/backend_v2/api/routes/models.py — deprecate V1 routes or redirect callers
- w:/containers/comfyui/backend_v2/api/routes/models_v2.py — canonical route surface for model operations
- w:/containers/comfyui/backend_v2/config.py — remove hardcoded deployment assumptions and unify config/env access
- w:/containers/comfyui/backend_v2/services/container_manager.py — stop hardcoding BACKEND_URL and related runtime values
- w:/containers/comfyui/frontend_v2/src/store/jobStore.js — narrow responsibilities and make websocket cleanup/order handling explicit
- w:/containers/comfyui/frontend_v2/src/api/websocket.js — centralize listener lifecycle and reconnection semantics
- w:/containers/comfyui/frontend_v2/src/pages/Dashboard.jsx — reduce prop drilling and align gallery refresh with server-state ownership
- w:/containers/comfyui/frontend_v2/src/hooks/useGallery.js — keep gallery as React Query server state with clear invalidation contract
- w:/containers/comfyui/frontend_v2/src/hooks/useModels.js — replace Promise.all failure amplification with partial-failure tolerant loading
- w:/containers/comfyui/frontend_v2/src/App.jsx — revisit query defaults and global websocket lifecycle responsibilities
- w:/containers/comfyui/provider_containers/provider_core/models.py — define strict shared provider response and error contracts
- w:/containers/comfyui/provider_containers/modal_worker/worker.py — conform worker responses to the shared contract
- w:/containers/comfyui/provider_containers/beam_worker/worker.py — conform worker responses to the shared contract
- w:/containers/comfyui/backend_v2/tests — add integration and concurrency coverage for backend behavior
- w:/containers/comfyui/frontend_v2/src/**/*.test.* — expand coverage for realtime integration and error paths
- w:/containers/comfyui/docs — update architecture, deployment, backend, and frontend docs to match the resulting system

**Verification**
1. Backend automated checks: run targeted pytest suites for load balancer, job queue, provider failover, model migration, event bus overflow, and end-to-end job processing with mocked provider streams.
2. Frontend automated checks: run Vitest suites for websocket lifecycle, Dashboard gallery invalidation, jobStore subscription cleanup, and partial failure handling in useModels. Account for the current Windows EPERM caveat noted in repo memory.
3. Manual integration check: submit single and batch jobs, simulate provider failure, confirm fallback behavior, verify websocket updates, verify gallery refresh, and confirm recovered jobs after backend restart.
4. Configuration validation: boot via docker-compose and via the workspace startup path, confirm no hardcoded localhost or container-name assumptions remain.
5. Documentation validation: confirm docs describe the same canonical model API, config precedence, and state-management boundaries implemented in code.

**Decisions**
- Include: correctness bugs, performance bottlenecks, integration gaps, missing tests, architectural duplication, and maintainability refactors.
- Exclude for now: broad UI redesign, database-engine replacement, and speculative optimization without measured hotspots.
- Recommended canonical direction: keep V2 model schema, domain exceptions, React Query for server state, Zustand for client-only state, and one shared provider error contract.
- Recommended sequencing: fix correctness and contracts before deleting legacy systems; do not attempt a large all-at-once refactor.

**Further Considerations**
1. V1 model retirement strategy: Option A deprecate then remove over two releases; Option B hard-cut after migration script verification. Recommendation: Option A unless there is no external dependency on V1 routes.
2. Load balancer state model: Option A async in-memory singleton with cleaner locking; Option B persistent/stateless DB-backed allocator. Recommendation: Option A first for lower risk, then revisit Option B if multi-instance backend is required.
3. Migration framework: Option A keep manual migrations but add verification and tests; Option B adopt Alembic. Recommendation: Option A immediately, Option B only if schema churn continues.

===== MORE CONTEXT ======

**Issue Compilation**
This is a high-confidence first-pass audit, not a claim that every defect in the repo has been exhausted. I verified the main findings directly in the source and used broader exploration to map the rest of the risk surface.

1. Backend concurrency and load-balancing state are fragile in load_balancer.py. The balancer keeps class-level mutable state in memory and protects it with a blocking threading lock inside an async backend. That is workable at low load, but it becomes harder to reason about under concurrency, makes testing stateful behavior more brittle, and does not scale cleanly toward multi-instance deployment.

2. The realtime event path can silently lose updates in events.py. The EventBus uses bounded queues and drops events with limited warning when subscribers fall behind. That creates a real risk of missed job progress or completion updates during bursts.

3. Job execution, retry, failover, provider parsing, and image post-processing are too concentrated in main.py. The file is carrying orchestration concerns that should be split into explicit policy and workflow modules. This is a maintainability problem first, but it also increases the chance of subtle retry and fallback bugs.

4. Graceful shutdown and recovery need tightening in job_queue.py. The current stop path cancels workers directly, leaving recovery to startup-time reconciliation. That is survivable, but it is not a robust lifecycle model for an async queue.

5. The codebase still has two model systems in parallel: the legacy flat model path in entities.py and model_service.py, and the normalized V2 path in entities_v2.py and model_service_v2.py. This is the biggest architectural drift in the backend. It increases duplication, complicates migrations, and makes ownership unclear.

6. Configuration and deployment assumptions are not fully unified. There are hardcoded origins and defaults in config.py, a hardcoded backend container URL in container_manager.py, and frontend backend defaults in config.js. That creates avoidable environment drift between local, Docker, and alternative deployments.

7. Exception handling is inconsistent across the route layer. The app has domain exceptions, but many routes still translate errors ad hoc with raw HTTPException handling, as seen in generation.py and broadly across routes. That makes API behavior less uniform and harder to test.

8. Frontend server-state ownership is blurred. Jobs are fetched and stored globally in Zustand from App.jsx and jobStore.js, while gallery data also fetches jobs through React Query in useGallery.js. Even though Dashboard.jsx already invalidates gallery queries on completion, the same domain data still spans two state systems, which raises merge and ordering complexity.

9. Model loading in the frontend is brittle in useModels.js. It uses one large Promise.all for multiple model directories, so a single failing endpoint can take down the entire load path instead of degrading per category.

10. Test coverage is uneven around the highest-risk integration flows. I did not find an obvious dedicated backend end-to-end job flow test covering submit job → provider response → save image → emit event → frontend-visible update, and the frontend test set is heavier on units/components than on realtime integration flows. The current frontend test inventory confirms coverage exists, but not much around Dashboard-level or websocket/query interaction.

11. The maintainability boundary between side effects and state is still loose in the frontend. Websocket lifecycle logic, store mutation, global app bootstrapping, and user notifications are spread across websocket.js, jobStore.js, App.jsx, and useJobNotifications.jsx. Multiple people can work in that area, but they will step on each other more easily than they should.

12. Documentation is at risk of drifting behind the implementation because the architecture has moved while both old and new systems still exist. The main hotspots are the model subsystem, deployment/config behavior, and frontend state ownership.

**Plan**
I saved the detailed execution plan in session memory at /memories/session/plan.md. The scannable version is:

1. Stabilize contracts first.
Define canonical payloads for provider errors, job events, and model status events, then add logging and metrics around dropped events, retries, and recovery outcomes.

2. Fix backend correctness hotspots before broad refactors.
Refactor load_balancer.py, split orchestration out of main.py, harden shutdown/recovery in job_queue.py, and verify manual migrations in database.py.

3. Unify model management around V2.
Keep entities_v2.py and model_service_v2.py as the canonical path, then deprecate and retire the V1 model flow in entities.py, model_service.py, and models.py.

4. Standardize backend error and config handling.
Add one exception translation layer, remove scattered HTTPException patterns where domain errors should be used, and route backend/provider URLs through config instead of hardcoded values in config.py, container_manager.py, and config.js.

5. Clean up frontend ownership boundaries.
Keep React Query as the owner of server data like gallery/model/provider fetches, keep Zustand for client-only and websocket-derived session state, and reduce the amount of cross-system merge logic in jobStore.js, useGallery.js, and Dashboard.jsx.

6. Refactor for multi-person and multi-agent maintainability.
Extract shared domain mappings, reduce large orchestration files, replace repeated websocket subscription patterns with a common abstraction, and define clearer service/repository/module boundaries.

7. Add the missing high-risk tests last, against the cleaned design.
Prioritize backend integration tests for provider failover, event delivery, migration verification, and queue recovery, then frontend tests for websocket lifecycle, Dashboard refresh behavior, and partial model-load failure handling.

8. Finish with docs and deployment alignment.
Update architecture, frontend, backend, and deployment docs so they match the canonical systems and the supported runtime configuration paths.

**Refactor Direction**
For maintainability, the strongest direction is:

- One model system: V2 only.
- One backend error model: domain exceptions translated centrally.
- One source of truth for domain mappings: model directories/types shared across backend and workers.
- One clear frontend split: React Query for server data, Zustand for client/session state only.
- Smaller orchestration units: retry policy, provider selection, image post-processing, and websocket sync separated into testable modules.

I did not implement changes in this pass because this session is in planning mode. Natural next steps are:

1. Approve this plan and hand off to implementation.
2. Ask me to convert these findings into a prioritized issue backlog with milestones and task breakdowns.
3. Ask for a narrower second-pass audit focused only on backend, frontend, tests, or provider containers.