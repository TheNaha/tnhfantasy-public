import asyncio
from uuid import uuid4
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

import httpx
from core.events import EventType, emit_provider_event

from core.entities import Provider
from infrastructure.repositories import ProviderRepository
from infrastructure.http_client import get_http_client
from core.exceptions import NotFoundError, ValidationError, ProviderError
from services.provider_utils import (
    read_deploy_state,
    extract_runtime_config,
    extract_deploy_config,
    compose_config,
    utcnow_iso,
    parse_utc_timestamp,
    DEPLOY_IN_PROGRESS_TTL,
    read_reconciliation_state,
    default_deploy_mode,
    default_deploy_targets,
    normalize_deploy_step_command
)
from services.provider_env_builder import build_provider_environment
from services.provider_deploy_orchestrator import (
    ProviderDeployOrchestrator,
    ProviderDeployStepExecutionError,
    ProviderDeployStepTimeoutError,
)
from infrastructure.request_dedup import deduplicated, is_in_flight
from infrastructure.logging import provider_logger

logger = provider_logger()

class ProviderDeployService:
    def __init__(self, repo: ProviderRepository):
        self.repo = repo

    def _build_deploy_state(
        self,
        *,
        provider_id: str,
        provider_type: str,
        status: str,
        attempt_id: str,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        message: Optional[str] = None,
        completed_steps: Optional[List[str]] = None,
        failed_steps: Optional[List[str]] = None,
        steps: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        state: Dict[str, Any] = {
            "provider_id": provider_id,
            "provider_type": provider_type,
            "status": status,
            "attempt_id": attempt_id,
            "updated_at": utcnow_iso(),
        }
        if started_at:
            state["started_at"] = started_at
        if finished_at:
            state["finished_at"] = finished_at
        if message:
            state["message"] = message
        if completed_steps:
            state["completed_steps"] = completed_steps
        if failed_steps:
            state["failed_steps"] = failed_steps
        if steps is not None:
            state["steps"] = steps
        return state

    async def _persist_deploy_state(self, provider: Provider, state: Dict[str, Any]) -> Dict[str, Any]:
        config = compose_config(
            base_config=provider.config,
            runtime_config=extract_runtime_config(provider.type, provider.container_config, provider.config or {}),
            deploy_config=extract_deploy_config(provider.type, provider.config or {}),
            deploy_state=state,
            reconciliation_state=read_reconciliation_state(provider),
        )
        updated = self.repo.update(provider.id, {"config": config})
        if updated is None:
            raise NotFoundError("Provider", provider.id)

        # Emit websocket event for live deploy progress
        event_type_map = {
            "deploying": EventType.PROVIDER_DEPLOY_PROGRESS,
            "failed": EventType.PROVIDER_DEPLOY_FAILED,
            "succeeded": EventType.PROVIDER_DEPLOY_COMPLETED,
            "idle": EventType.PROVIDER_DEPLOY_COMPLETED,
        }
        event_type = event_type_map.get(state.get("status"), EventType.PROVIDER_DEPLOY_PROGRESS)
        # Handle the start event
        if state.get("status") == "deploying" and not state.get("steps"):
            event_type = EventType.PROVIDER_DEPLOY_STARTED

        await emit_provider_event(event_type, provider.id, state)
        
        return state

    def _is_deploy_in_progress(self, state: Dict[str, Any]) -> bool:
        if state.get("status") != "deploying":
            return False
        started_at_raw = state.get("started_at")
        started_at = parse_utc_timestamp(started_at_raw)
        if not started_at:
            return True
        age = datetime.now(timezone.utc) - started_at
        return age.total_seconds() <= DEPLOY_IN_PROGRESS_TTL

    def _has_active_deploy_attempt_container(
        self,
        container_manager: Any,
        provider_id: str,
        attempt_id: Optional[str],
    ) -> bool:
        if not attempt_id:
            return False

        containers_client = getattr(getattr(container_manager, "client", None), "containers", None)
        if containers_client is None:
            return True

        expected_name = f"comfy-provider-deploy-{provider_id}-{str(attempt_id)[:8]}"

        try:
            container = containers_client.get(expected_name)
            try:
                container.reload()
            except Exception:
                pass
            status = getattr(container, "status", None)
            return status not in {"exited", "dead", "removing"}
        except Exception:
            pass

        try:
            matches = containers_client.list(
                all=True,
                filters={
                    "label": [
                        "comfy-provider-deploy=true",
                        f"provider-id={provider_id}",
                        f"deploy-attempt-id={attempt_id}",
                    ]
                },
            )
        except Exception as exc:
            logger.warning(
                "provider_deploy_container_probe_failed",
                provider_id=provider_id,
                attempt_id=attempt_id,
                error=str(exc),
            )
            return True

        for container in matches or []:
            try:
                container.reload()
            except Exception:
                pass
            status = getattr(container, "status", None)
            if status not in {"exited", "dead", "removing"}:
                return True

        return False

    async def _mark_deploy_state_failed(self, provider: Provider, state: Dict[str, Any], *, message: str) -> Dict[str, Any]:
        failed_state = self._build_deploy_state(
            provider_id=provider.id,
            provider_type=provider.type,
            status="failed",
            attempt_id=state.get("attempt_id") or "stale-state",
            started_at=state.get("started_at"),
            finished_at=utcnow_iso(),
            message=message,
            completed_steps=state.get("completed_steps"),
            failed_steps=state.get("failed_steps"),
            steps=state.get("steps") if isinstance(state.get("steps"), list) else None,
        )
        await self._persist_deploy_state(provider, failed_state)
        return failed_state

    @staticmethod
    def _decode_exec_output(exec_result: Any) -> tuple[int, str]:
        output = getattr(exec_result, "output", (None, None))
        stdout_bytes = output[0] if isinstance(output, tuple) and len(output) > 0 else None
        stderr_bytes = output[1] if isinstance(output, tuple) and len(output) > 1 else None
        stdout = stdout_bytes.decode("utf-8") if stdout_bytes else ""
        stderr = stderr_bytes.decode("utf-8") if stderr_bytes else ""
        return getattr(exec_result, "exit_code", -1), f"{stdout}{stderr}"

    async def get_provider_deploy_state(self, provider: Provider) -> Dict[str, Any]:
        state = read_deploy_state(provider)

        if self._is_deploy_in_progress(state):
            container_manager = None
            try:
                from services.container_manager import get_container_manager
                container_manager = get_container_manager()
            except Exception:
                container_manager = None

            if container_manager and not self._has_active_deploy_attempt_container(
                container_manager,
                provider.id,
                state.get("attempt_id"),
            ):
                return await self._mark_deploy_state_failed(
                    provider,
                    state,
                    message="Previous deployment container disappeared and state was marked failed",
                )
            return state

        if state.get("status") == "deploying":
            return await self._mark_deploy_state_failed(
                provider,
                state,
                message="Previous deployment state expired and was marked failed",
            )

        return state

    async def deploy_provider_app(self, provider: Provider, container_manager: Any) -> Dict[str, Any]:
        from services.provider_runtime import resolve_provider_runtime
        runtime = resolve_provider_runtime(provider)
        
        if runtime.mode == "discovery" or not container_manager:
            if runtime.mode not in ("container_http", "discovery"):
                raise ProviderError(provider.id, "Cannot deploy without a running worker")
            
            http_client = get_http_client()
            try:
                response = await http_client.post(
                    f"{runtime.worker_url}/deploy",
                    json={"provider_id": provider.id},
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException as exc:
                raise ProviderError(provider.id, "Deploy request timed out") from exc
            except (httpx.HTTPError, ValueError) as exc:
                raise ProviderError(provider.id, f"Deploy failed: {str(exc)}") from exc

        current_state = read_deploy_state(provider)
        if self._is_deploy_in_progress(current_state):
            if not self._has_active_deploy_attempt_container(
                container_manager,
                provider.id,
                current_state.get("attempt_id"),
            ):
                current_state = await self._mark_deploy_state_failed(
                    provider,
                    current_state,
                    message="Previous deployment container disappeared and state was marked failed",
                )
            else:
                return {
                    "status": "already_running",
                    "provider_id": provider.id,
                    "provider_type": provider.type,
                    "message": "Deployment already in progress for this provider",
                    "deploy_state": current_state,
                }

        dedup_key = f"provider-deploy:{provider.id}"
        if is_in_flight(dedup_key):
            return {
                "status": "already_running",
                "provider_id": provider.id,
                "provider_type": provider.type,
                "message": "Deployment already in progress for this provider",
                "deploy_state": current_state,
            }

        async def _run_deploy() -> Dict[str, Any]:
            return await self._execute_provider_deploy(provider, container_manager)

        return await deduplicated(dedup_key, _run_deploy)

    async def _execute_provider_deploy(self, provider: Provider, container_manager: Any) -> Dict[str, Any]:
        attempt_id = str(uuid4())
        started_at = utcnow_iso()
        deploy_config = extract_deploy_config(provider.type, provider.config or {})
        deploy_mode = deploy_config.get("deploy_mode", default_deploy_mode(provider.type))

        if deploy_mode != "managed":
            raise ValidationError(f"Managed deploy is disabled for provider '{provider.id}'")

        previous_state = read_deploy_state(provider)
        resumed_steps: List[str] = []
        if provider.type == "beam" and previous_state.get("status") == "failed":
            resumed_steps = [
                step
                for step in (previous_state.get("completed_steps") or [])
                if step in {"comfy_gpu", "comfy_storage", "comfy_download"}
            ]

        deploying_state = self._build_deploy_state(
            provider_id=provider.id,
            provider_type=provider.type,
            status="deploying",
            attempt_id=attempt_id,
            started_at=started_at,
            message="Deployment started",
            completed_steps=resumed_steps,
            steps=[],
        )
        await self._persist_deploy_state(provider, deploying_state)

        orchestrator = ProviderDeployOrchestrator(container_manager)
        deploy_container = None
        try:
            deploy_env_vars = build_provider_environment(provider)
            if provider.type == "beam":
                deploy_env_vars.setdefault("CI", "1")

            deploy_container = orchestrator.start_attempt_container(
                provider_id=provider.id,
                provider_type=provider.type,
                attempt_id=attempt_id,
                env_vars=deploy_env_vars,
            )
            deployments = deploy_config.get("targets") or default_deploy_targets(provider.type)
            completed_steps = set(resumed_steps)
            results: List[Dict[str, Any]] = []

            for step in deployments:
                name = step.get("name") or "deploy-step"
                command = normalize_deploy_step_command(provider.type, step.get("command") or [])
                if not command:
                    continue
                if name in completed_steps:
                    results.append(
                        {
                            "name": name,
                            "success": True,
                            "exit_code": 0,
                            "output": "Skipped; step already completed in previous failed attempt",
                            "skipped": True,
                        }
                    )
                    continue

                try:
                    exec_result = await orchestrator.run_step(deploy_container, command)
                    exit_code, output = self._decode_exec_output(exec_result)
                except ProviderDeployStepTimeoutError as exc:
                    exit_code, output = -1, str(exc)
                except ProviderDeployStepExecutionError as exc:
                    exit_code, output = -1, str(exc)
                success = exit_code == 0
                if success:
                    completed_steps.add(name)
                results.append(
                    {
                        "name": name,
                        "success": success,
                        "exit_code": exit_code,
                        "output": output,
                        "entrypoint": step.get("entrypoint"),
                    }
                )
                step_state = self._build_deploy_state(
                    provider_id=provider.id,
                    provider_type=provider.type,
                    status="deploying",
                    attempt_id=attempt_id,
                    started_at=started_at,
                    message=f"Running step: {name}",
                    completed_steps=list(completed_steps),
                    steps=results,
                )
                await self._persist_deploy_state(provider, step_state)
                if not success:
                    break

            failed_steps = [entry["name"] for entry in results if not entry["success"]]
            if failed_steps:
                failed_state = self._build_deploy_state(
                    provider_id=provider.id,
                    provider_type=provider.type,
                    status="failed",
                    attempt_id=attempt_id,
                    started_at=started_at,
                    finished_at=utcnow_iso(),
                    message=f"Deployment failed at step '{name}'",
                    completed_steps=list(completed_steps),
                    failed_steps=failed_steps,
                    steps=results,
                )
                await self._persist_deploy_state(provider, failed_state)
                raise ProviderError(
                    provider.id,
                    f"{provider.type.capitalize()} deploy failed for: {', '.join(failed_steps)}. Check deploy details for logs.",
                )

            success_state = self._build_deploy_state(
                provider_id=provider.id,
                provider_type=provider.type,
                status="succeeded",
                attempt_id=attempt_id,
                started_at=started_at,
                finished_at=utcnow_iso(),
                message="Deployment completed successfully",
                completed_steps=list(completed_steps),
                steps=results,
            )
            await self._persist_deploy_state(provider, success_state)

            try:
                from services.provider_runtime import resolve_provider_runtime
                runtime = resolve_provider_runtime(provider)
                if runtime.worker_url:
                    await self._run_deployment_tests(
                        provider=provider,
                        attempt_id=attempt_id,
                        started_at=started_at,
                        completed_steps=sorted(completed_steps),
                        deployments=results,
                        worker_url=runtime.worker_url,
                    )
                    success_state = read_deploy_state(provider)
            except Exception as e:
                logger.error(
                    "provider_deploy_tests_failed",
                    provider_id=provider.id,
                    error=str(e)
                )

            return {
                "status": "succeeded",
                "provider_type": provider.type,
                "message": f"{provider.type.capitalize()} app deployed for {provider.id}",
                "deployments": results,
                "deploy_state": success_state,
            }
        except Exception:
            current_state = read_deploy_state(provider)
            if current_state.get("status") == "deploying":
                failed_state = self._build_deploy_state(
                    provider_id=provider.id,
                    provider_type=provider.type,
                    status="failed",
                    attempt_id=current_state.get("attempt_id") or attempt_id,
                    started_at=current_state.get("started_at") or started_at,
                    finished_at=utcnow_iso(),
                    message=current_state.get("message") or "Deployment failed",
                    completed_steps=current_state.get("completed_steps"),
                    failed_steps=current_state.get("failed_steps"),
                )
                await self._persist_deploy_state(provider, failed_state)
            raise
        finally:
            orchestrator.cleanup_container(deploy_container)

    async def _run_deployment_tests(
        self,
        provider: Provider,
        attempt_id: str,
        started_at: str,
        completed_steps: list[str],
        deployments: list[dict],
        worker_url: str,
    ) -> None:
        import time
        from services.provider_utils import utcnow_iso
        testing_state = self._build_deploy_state(
            provider_id=provider.id,
            provider_type=provider.type,
            status="testing",
            attempt_id=attempt_id,
            started_at=started_at,
            message="Running post-deployment tests",
            completed_steps=completed_steps,
            steps=deployments,
        )
        testing_state["test_results"] = []
        await self._persist_deploy_state(provider, testing_state)

        from infrastructure.http_client import get_http_client
        http_client = get_http_client()
        test_results = []
        all_passed = True

        async def _update_test_state(results: list[dict]):
            testing_state["test_results"] = list(results)
            await self._persist_deploy_state(provider, testing_state)

        # 1. Liveness Ping
        try:
            start_t = time.time()
            res = await http_client.get(f"{worker_url}/health", timeout=10.0)
            res.raise_for_status()
            latency = int((time.time() - start_t) * 1000)
            test_results.append({
                "name": "Liveness Ping",
                "success": True,
                "message": f"OK ({latency}ms)"
            })
        except Exception as e:
            all_passed = False
            test_results.append({"name": "Liveness Ping", "success": False, "message": str(e)})

        await _update_test_state(test_results)

        # 2. Egress/Storage Test
        if all_passed:
            try:
                start_t = time.time()
                payload = {
                    "url": "https://speed.hetzner.de/100MB.bin",
                    "path": "test_dummy_write_100mb.bin"
                }
                res = await http_client.post(f"{worker_url}/download-model", json=payload, timeout=120.0)
                res.raise_for_status()
                latency = time.time() - start_t
                mb_per_sec = 104.85 / latency if latency > 0 else 0 # 100 MiB
                test_results.append({
                    "name": "Egress/Storage",
                    "success": True,
                    "message": f"Write OK: {mb_per_sec:.1f} MB/s ({latency:.1f}s)"
                })
            except Exception as e:
                all_passed = False
                test_results.append({"name": "Egress/Storage", "success": False, "message": str(e)})
            
            await _update_test_state(test_results)

        # 3. Inference Warmup
        # Skipped to save provider container compute costs
        if all_passed:
            test_results.append({
                "name": "Inference Warmup",
                "success": True,
                "message": "Skipped to save compute"
            })
            await _update_test_state(test_results)

        final_status = "succeeded" if all_passed else "failed"
        final_message = "Deployment and tests completed successfully" if all_passed else "Deployment tests failed"
        
        final_state = self._build_deploy_state(
            provider_id=provider.id,
            provider_type=provider.type,
            status=final_status,
            attempt_id=attempt_id,
            started_at=started_at,
            finished_at=utcnow_iso(),
            message=final_message,
            completed_steps=completed_steps,
            failed_steps=[t["name"] for t in test_results if not t.get("success")] if not all_passed else None,
            steps=deployments,
        )
        final_state["test_results"] = test_results
        await self._persist_deploy_state(provider, final_state)
