## 2026-06-19T12:30:58Z
Your role is Worker M3 for the ComfyUI Wrapper Audit, Consolidation, and Repair project.
Your working directory is /home/thenaha/containers/stacks/comfyui/.agents/worker_m3.
Your task is to implement the Provider Integration & Health Normalization (Milestone 3) as outlined.
Specifically:
1. In /home/thenaha/containers/stacks/comfyui/provider_containers/provider_core/logging.py:
   - Create a new module that exposes a `get_logger(name: str)` helper returning a configured `logging.Logger` logging to stdout.
2. In the provider codebase (under /home/thenaha/containers/stacks/comfyui/provider_containers/), find and replace standard `print(...)` statements (except those outputting raw streams/logs intentionally) with structured logger calls using the newly created `get_logger`. Pay special attention to background loops, model setup/downloads, and reconciliation scripts.
3. In /home/thenaha/containers/stacks/comfyui/provider_containers/provider_core/router.py:
   - In `attach_provider_routes()`, register global exception handlers on the FastAPI app instance for:
     - `starlette.exceptions.HTTPException` (mapping it to the ErrorResponse schema, extracting message details, and setting `retryable=exc.status_code >= 500`)
     - `fastapi.exceptions.RequestValidationError` (mapping it to the ErrorResponse schema)
     - `Exception` (mapping unhandled exceptions to ErrorResponse schema as retryable status=500 errors)
4. In /home/thenaha/containers/stacks/comfyui/backend_v2/services/load_balancer.py:
   - Add `provider_health_cache: Dict[str, Tuple[bool, float]] = field(default_factory=dict)` to `LoadBalancerRuntimeState`.
   - Implement `_check_provider_health(self, provider)` which probes the container's status or health endpoint, caching the result for 5 seconds.
   - Update `get_next_provider()` to:
     - Differentiate between warm (healthy/running) and cold (stopped/unhealthy) candidate providers.
     - If warm providers exist, select and route the job only among warm providers.
     - If only cold providers exist, trigger container startup via `ProviderLifecycleService.start_container(provider.id)`, and wait/poll (up to 30 seconds) until it responds to `/health` successfully before returning it.
5. In /home/thenaha/containers/stacks/comfyui/backend_v2/api/provider_client.py:
   - In `call_provider()` when raising `ProviderCallError` on non-200 responses: try to parse the JSON error payload and extract the `retryable` boolean field to determine if the job can be retried.
6. Run the backend tests to verify load balancer health checks, error handler mappings, and provider worker changes.
7. Document all changes and test results in /home/thenaha/containers/stacks/comfyui/.agents/worker_m3/handoff.md.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

When complete, notify parent conversation d4553e37-d267-4d5b-ba70-743258ac2a78 by calling send_message with recipient parent.
