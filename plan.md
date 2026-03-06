**Issue Compilation**

1. Provider error contracts are inconsistent across workers, which means backend error handling is incomplete. The backend inference parser in main.py raises from a message field, while Beam emits error payloads using an error field in worker.py and Modal emits message in worker.py. This can suppress useful failure details for one provider type.

2. The load balancer keeps shared mutable state at class level and guards it with a thread lock in load_balancer.py, even though job execution is async. That is a real concurrency risk around provider selection, job counts, and round-robin state.

3. The backend event bus silently drops events when subscriber queues fill. In events.py, queue overflow is swallowed with no logging or metrics. Under load, that can cause missing progress or completion updates in the UI.

4. Job retry and fallback logic is spread through the core processing loop in main.py. The logic is workable, but it is high-risk because provider failure accounting, retryability, requeue state, and fallback exhaustion are all coupled in one place and are only lightly protected by tests.

5. Image save fallback can degrade metadata integrity. In main.py, the code tries to embed metadata and then falls back to raw binary write if embedding fails. That keeps the image but can silently lose the metadata needed for later traceability.

6. The shared provider contract is incomplete. models.py defines requests, but not a strict shared response model for inference, errors, or model-management endpoints. That is why Modal and Beam have drifted.

7. There is at least one concrete directory-contract mismatch already in the provider layer. The canonical directory list uses models/upscale_models in models.py, while Modal stats use models/upscale/models in worker.py. That will produce inconsistent model visibility and stats.

8. Frontend API usage is not unified. The project has a centralized client in client.js, but large surfaces still use direct fetch, especially ProviderManagement.jsx. That duplicates error handling, config, and request behavior.

9. Provider state ownership on the frontend is split across local component state and the store. ProviderManagement.jsx keeps providers, load-balancer data, and container status in local state, while providerStore.js also owns provider websocket state. That is a source-of-truth problem.

10. The frontend state model does not consistently follow the documented boundary in STATE_MANAGEMENT.md. The architecture says React Query is for server data and Zustand is for client state, but several components mix transport, cache, and local state responsibilities.

11. Websocket listener lifecycle needs cleanup in websocket.js. The file already tries to avoid duplicates on reconnect, which is good, but the overall listener and subscription model is global, stateful, and easy to misuse from multiple pages and stores.

12. Test coverage is not aligned with the highest-risk paths. I found no backend test files targeting streaming parser behavior or retry behavior by name, and the critical integration surfaces are concentrated in tests rather than explicitly covering provider-stream parsing, fallback behavior, and worker contract drift. Frontend tests exist, but they do not yet cover the most fragile provider-management and websocket integration flows in src.

**Plan**

## Plan: TNHComfy Reliability Sweep

Full sweep, staged for safety. Fix runtime correctness first in the provider-job pipeline, then unify duplicated frontend/backend systems, then close the remaining architectural debt and test gaps.

**Steps**
1. Phase 1: Standardize provider response contracts and harden backend parsing. Update shared response models, make Modal and Beam emit the same shapes, and make main.py parse them defensively.
2. Phase 1: Stabilize backend job execution state. Refactor main.py and load_balancer.py so retries, fallback, success, and release semantics are deterministic under async load.
3. Phase 1: Make event delivery observable and safer in events.py. Increase resilience around queue overflow and add instrumentation or warnings.
4. Phase 1 parallel: Add backend integration tests for NDJSON parsing, retry/fallback, provider error payloads, and event emission in tests.
5. Phase 2: Fix backend operational correctness issues. Address metadata-save fallback behavior in main.py, health/status accuracy in container_manager.py, migration verification in database.py, and output-path consistency.
6. Phase 3: Unify frontend transport and state ownership. Move raw fetch calls onto the central client, extract ProviderManagement API calls, and converge provider state around providerStore.js plus React Query where appropriate.
7. Phase 3: Break up ProviderManagement.jsx into smaller modules after state ownership is decided, not before.
8. Phase 3 parallel: Add frontend tests for provider actions, websocket listener lifecycle, and cache invalidation behavior in src.
9. Phase 4: Tackle longer-horizon cleanup such as V1 versus V2 duplication once the runtime path is stable. This includes service consolidation and unifying system ownership boundaries.
10. Phase 5: Run full regression verification, then update documentation where contracts or architecture changed.

**Relevant files**
- main.py
- load_balancer.py
- events.py
- container_manager.py
- database.py
- models.py
- worker.py
- worker.py
- STATE_MANAGEMENT.md
- client.js
- websocket.js
- ProviderManagement.jsx
- providerStore.js
- tests
- src

**Verification**
1. Add backend tests for malformed and partial NDJSON, retryable and non-retryable provider failures, fallback exhaustion, and event emission.
2. Add provider tests proving Modal and Beam return the same success and error shapes.
3. Add frontend tests for provider management flows and websocket listener cleanup.
4. Run the backend and frontend test suites after each phase, not just at the end.
5. Manually verify job submission, progress updates, worker error surfacing, fallback behavior, gallery refresh, and provider status updates.

The full staged plan is saved in session memory as plan.md. Because you asked for a full sweep and broad cleanup, my recommendation is to execute this in phases rather than one giant patch.

Natural next steps:
1. Approve this plan and I’ll start with Phase 1 only.
2. Ask me to expand any specific finding into a deeper technical breakdown before implementation.
3. Ask me to reprioritize the phases if you want frontend or architecture cleanup first.