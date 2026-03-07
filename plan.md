## Plan: TNHComfy Audit And Refactor

This is a repo-wide audit and staged remediation plan for TNHComfy. The recommended approach is to fix correctness and integration risks first, then remove architectural hotspots and unify duplicate systems, then add the test and contributor guardrails needed for multi-person or multi-agent parallel work.

**Issue Compilation**
1. Critical: Load balancer uses class-level mutable state with threading.RLock inside async request paths in backend_v2/services/load_balancer.py. This is a concurrency and test isolation risk.
2. Critical: Frontend state ownership is blurred between Zustand jobStore and React Query gallery/job fetching, especially in frontend_v2/src/store/jobStore.js, frontend_v2/src/hooks/useGallery.js, and frontend_v2/src/pages/Dashboard.jsx.
3. Critical: Dashboard is a monolith with mixed data, UI, modal, filter, and selection logic in frontend_v2/src/pages/Dashboard.jsx, making safe parallel edits difficult.
4. Critical: The codebase still carries dual model systems, with V1 and V2 entities, services, repositories, and routes coexisting across backend_v2/core/entities.py, backend_v2/core/entities_v2.py, backend_v2/services/model_service.py, backend_v2/services/model_service_v2.py, backend_v2/api/routes/models.py, and backend_v2/api/routes/models_v2.py.
5. Critical: Dependency injection is not unified. Some routes bypass api/deps.py and import sessions or singletons directly from infrastructure, forcing awkward test overrides and weakening modularity.
6. High: Fire-and-forget async tasks are created without tracking, timeout policy, or exception handling in backend_v2/api/main.py and route modules, risking orphaned work and silent failures.
7. High: Request dedup infrastructure keeps module-level mutable dictionaries and cached results without robust locking or expiration in backend_v2/infrastructure/request_dedup.py.
8. High: Manual database migrations live inside backend_v2/infrastructure/database.py with no version table, rollback workflow, or strong verification after partial failures.
9. High: Event bus backpressure and subscriber lag handling are weak in backend_v2/core/events.py, creating risk of blocking or silent event loss under load.
10. High: Error handling is inconsistent across routes and providers. The backend mixes HTTPException and ComfyError patterns, while provider workers do not guarantee a single normalized error contract.
11. High: Provider integration remains brittle. Health checks are not consistently enforced before scheduling, and provider lifecycle startup and recovery are only partially integrated.
12. High: Backend job processing remains tightly coupled in backend_v2/api/main.py, mixing app startup, queue wiring, provider strategy, reconciliation, and background work orchestration.
13. High: Provider route surface is not cleanly separated. backend_v2/api/routes/providers.py mixes provider CRUD with image save and cache-related responsibilities.
14. High: Frontend websocket lifecycle logic is dense and side-effect heavy in frontend_v2/src/store/jobStore.js, with reconnect, polling fallback, page visibility, and notification behavior all bundled together.
15. High: Frontend has major missing page-level and integration tests, especially for Dashboard, generator pages, websocket-driven flows, and backend/frontend handoff.
16. Medium: Several large modules impede maintainability and parallel work, notably backend_v2/api/main.py, backend_v2/infrastructure/database.py, backend_v2/services/model_service_v2.py, backend_v2/api/routes/providers.py, backend_v2/api/routes/models_v2.py, frontend_v2/src/store/jobStore.js, and frontend_v2/src/pages/Dashboard.jsx.
17. Medium: Logging and observability are inconsistent, with print-based diagnostics still present in backend and provider code.
18. Medium: Config, deployment, and environment conventions are not fully unified across config.py, config.json, docker-compose.yml, backend startup, and provider worker settings.
19. Medium: Documentation and contributor workflow are insufficient for coordinated multi-engineer or multi-agent work. There is no strong contributor guide, architecture decision log, or ownership map.
20. Medium: Test coverage does not adequately protect critical backend lifecycle flows, provider failure paths, image processing, scheduler behavior, request dedup, or frontend page integration.

**Steps**
1. Phase 1: Stabilize foundations. Unify dependency injection around backend_v2/api/deps.py, replace class-level mutable coordination state in backend_v2/services/load_balancer.py, add tracked background task handling for backend_v2/api/main.py, and define one backend error translation path for ComfyError and HTTP responses. These changes should be treated as blockers for deeper refactors.
2. Phase 1 parallel work: Normalize provider contracts and startup checks across provider_containers/modal_worker, provider_containers/beam_worker, and backend_v2 provider orchestration. Standardize health checks, image-save paths, and error payload formats.
3. Phase 2: Reduce architecture hotspots. Extract job processing orchestration out of backend_v2/api/main.py into dedicated services such as job processor, provider strategy, and image pipeline modules. Split oversized route files, especially backend_v2/api/routes/models_v2.py and backend_v2/api/routes/providers.py, by responsibility.
4. Phase 2 depends on 1: Replace ad hoc migration logic in backend_v2/infrastructure/database.py with explicit versioned migration units and a migration registry. This does not require Alembic if the team wants to stay lightweight, but it does require deterministic version tracking and failure handling.
5. Phase 2 depends on 1: Refactor backend_v2/infrastructure/request_dedup.py to use safe locking and bounded or TTL-based caching semantics. Define clearly whether the feature is only for in-flight deduplication or also for result caching.
6. Phase 3: Unify the model domain. Decide on V2 as the single model path, migrate remaining V1 callers, deprecate backend_v2/api/routes/models.py and backend_v2/services/model_service.py, and remove mixed-status bridging logic from backend_v2/api/routes/models_v2.py once migration is complete.
7. Phase 3 parallel work: Establish cleaner route and service boundaries. Each route module should own one domain, and each service should expose a narrow public API. Remove cross-domain surprises such as provider routes owning image-save endpoints.
8. Phase 4: Rebuild frontend state boundaries. Keep websocket-driven active job progress in Zustand and move persistent server-owned job and gallery data to React Query. Update frontend_v2/src/store/jobStore.js, frontend_v2/src/hooks/useGallery.js, and related hooks so data ownership is explicit and cache invalidation rules are documented.
9. Phase 4 depends on 8: Split frontend_v2/src/pages/Dashboard.jsx into focused modules for container logic, filters, toolbar, grid or timeline rendering, and selection or details panels. This should reduce merge conflicts and make UI behavior testable.
10. Phase 4 parallel work: Simplify websocket lifecycle management by extracting connection orchestration from the store into a dedicated frontend websocket layer. Keep stores focused on state transitions, not browser event wiring.
11. Phase 5: Build a protective test matrix. Add backend integration tests for job lifecycle, provider failure and retry behavior, websocket event propagation, image processing, scheduler flows, load balancer correctness, and request dedup semantics. Add frontend page and integration tests for Dashboard, generator flows, provider management, and websocket reconnection behavior.
12. Phase 6: Make the repository collaboration-friendly. Add contributor documentation, architecture decision records, domain boundaries, and ownership conventions. Reduce shared mutable hotspot files, document allowed dependencies between domains, and define a standard module template for routes, services, stores, and hooks.

**Relevant files**
- c:/workspace/TNHComfy/backend_v2/api/deps.py — target single source of truth for request-scoped dependency injection.
- c:/workspace/TNHComfy/backend_v2/api/main.py — currently overloaded with startup, orchestration, and background task concerns.
- c:/workspace/TNHComfy/backend_v2/services/load_balancer.py — class-level state and async-safety hotspot.
- c:/workspace/TNHComfy/backend_v2/infrastructure/request_dedup.py — dedup semantics, concurrency safety, and cache lifetime need redesign.
- c:/workspace/TNHComfy/backend_v2/infrastructure/database.py — manual migration and startup DB handling hotspot.
- c:/workspace/TNHComfy/backend_v2/core/events.py — event bus backpressure, queueing, and observability behavior.
- c:/workspace/TNHComfy/backend_v2/api/routes/models.py — legacy V1 model API to deprecate.
- c:/workspace/TNHComfy/backend_v2/api/routes/models_v2.py — oversized V2 route module and mixed transitional logic.
- c:/workspace/TNHComfy/backend_v2/services/model_service.py — legacy V1 service to retire.
- c:/workspace/TNHComfy/backend_v2/services/model_service_v2.py — oversized service to split by responsibility.
- c:/workspace/TNHComfy/backend_v2/api/routes/providers.py — provider CRUD mixed with unrelated responsibilities.
- c:/workspace/TNHComfy/frontend_v2/src/store/jobStore.js — websocket lifecycle and state-ownership hotspot.
- c:/workspace/TNHComfy/frontend_v2/src/hooks/useGallery.js — React Query boundary with overlap against Zustand.
- c:/workspace/TNHComfy/frontend_v2/src/pages/Dashboard.jsx — major UI hotspot blocking parallel frontend work.
- c:/workspace/TNHComfy/provider_containers/provider_core/models.py — worker/backend contract should be treated as the canonical interface definition.
- c:/workspace/TNHComfy/docker-compose.yml — deployment assumptions and security or portability cleanup.

**Verification**
1. Backend verification: run backend_v2 pytest suites plus new integration tests covering job creation, queue execution, provider failure, image saving, websocket propagation, and shutdown behavior.
2. Frontend verification: run frontend_v2 vitest suites plus new page-level and integration tests for Dashboard, generation flows, provider management, and websocket reconnect behavior.
3. Architecture verification: confirm that only one model system remains active, that routes resolve sessions only through api/deps.py, and that major domains can be modified independently with low merge conflict risk.
4. Operational verification: exercise both Modal and Beam flows, simulate provider health failures, verify normalized error responses, and confirm that background tasks are tracked and logged.
5. Collaboration verification: add or update contributor docs and confirm a new engineer or agent can identify domain boundaries, test entry points, and ownership rules without reading giant files first.

**Decisions**
- Included scope: audit findings, architectural risks, test gaps, integration gaps, and a staged remediation plus refactor plan.
- Excluded scope: implementation details for every individual bug fix. Those should be handled in follow-on execution passes per phase.
- Recommended strategic direction: treat this as a phased stabilization and modularization program, not a single massive rewrite. Rewrite risk is higher than incremental extraction and unification.
- Model-domain recommendation: standardize on V2 and plan explicit deprecation of V1.
- Collaboration recommendation: finish the dependency injection, load balancer, and hotspot-file cleanup before attempting broad parallel contributor work.

**Further Considerations**
1. Migration strategy choice: Option A is strict incremental refactor in place, which is safer. Option B is parallel replacement modules with cutover flags, which is faster for teams but increases temporary duplication.
2. Ownership strategy: Option A is domain ownership by backend, frontend, and provider teams. Option B is cross-cutting squads by job flow, model flow, and platform. For this repository, domain ownership is the lower-risk starting point.
3. Migration tooling choice: Option A is a lightweight in-repo versioned migration runner. Option B is adopting Alembic. If the team wants lower process overhead, start with the lightweight runner and revisit Alembic only if schema churn increases.