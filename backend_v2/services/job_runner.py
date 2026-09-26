import asyncio
from datetime import datetime, timezone

from core.entities import JobStatus, Provider
from core.exceptions import NotFoundError
from core.workflow_parser import extract_models_from_workflow
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from services.job_processing import finalize_successful_job
from services.job_service import (
    FAILURE_UNEXPECTED,
    JobService,
)
from services.load_balancer import LoadBalancer
from services.load_balancer_factory import create_load_balancer
from services.provider_client import (
    JobCancelledError,
    JobTimeoutError,
    ProviderCallError,
)
from services.provider_runtime import resolve_provider_runtime
from services.provider_service import ProviderService

logger = get_logger("job_runner")


def track_attempt(job_service, job_id: str, *, provider_id: str | None, attempt: int):
    """Return a recorder for the outcome of a single provider attempt.

    Each call site closes its attempt with `await record("timeout"|"error"|...)`
    so `diagnostics.attempts` explains which providers were tried, in what
    order, and how long each took. Recording failures are swallowed — losing a
    diagnostic must never abort job execution.
    """
    started_at = datetime.now(timezone.utc)

    async def _record(outcome: str, error: str | None = None) -> None:
        duration = max((datetime.now(timezone.utc) - started_at).total_seconds(), 0.0)
        try:
            await job_service.record_attempt(
                job_id,
                provider_id=provider_id,
                attempt=attempt,
                outcome=outcome,
                error=error,
                duration_seconds=round(duration, 3),
            )
        except Exception as exc:  # pragma: no cover - record_attempt already guards
            logger.warning(
                "job_attempt_record_failed", job_id=job_id, provider=provider_id, error=str(exc)
            )

    return _record


async def mark_provider_exhausted(
    *,
    load_balancer: LoadBalancer,
    exhausted_providers: set[str],
    job_service,
    job_id: str,
    provider_id: str,
    message: str,
) -> None:
    """Release provider state and move the job back to pending before trying another provider."""
    await load_balancer.release_job(provider_id)
    exhausted_providers.add(provider_id)
    await job_service.update_job(
        job_id,
        status=JobStatus.PENDING,
        message=message,
    )


async def select_next_provider(
    *,
    load_balancer: LoadBalancer,
    job_service,
    job_id: str,
    exhausted_providers: set[str],
    preferred_provider_id: str | None,
    required_models: dict | None = None,
    task_type: str = "image",
) -> Provider | None:
    """Select the next provider or fail the job when no providers remain."""
    provider = await load_balancer.get_next_provider(
        preferred_provider_id=preferred_provider_id,
        required_models=required_models,
        exclude_provider_ids=exhausted_providers,
        task_type=task_type,
    )

    if provider:
        return provider

    if not exhausted_providers:
        logger.warning("no_providers", job_id=job_id)
        await job_service.update_job(
            job_id,
            status=JobStatus.FAILED,
            error="No available providers",
        )
    else:
        logger.warning("providers_exhausted", job_id=job_id, tried=list(exhausted_providers))
        await job_service.update_job(
            job_id,
            status=JobStatus.FAILED,
            error=f"All providers failed: {', '.join(exhausted_providers)}",
        )

    return None


async def maybe_retry_current_provider(
    *,
    job_service,
    job_id: str,
    provider_id: str,
    retry_count: int,
    max_retries: int,
    base_delay: float,
    max_delay: float,
    retry_message: str,
) -> tuple[bool, int]:
    """Apply retry backoff for the current provider if attempts remain."""
    next_retry_count = retry_count + 1
    if next_retry_count > max_retries:
        return False, next_retry_count

    delay = min(base_delay * (2 ** (next_retry_count - 1)), max_delay)
    logger.info(
        "job_retry",
        job_id=job_id,
        delay=delay,
        attempt=next_retry_count,
        provider=provider_id,
    )
    await job_service.update_job(
        job_id,
        status=JobStatus.RETRYING,
        message=retry_message.format(attempt=next_retry_count),
    )
    await asyncio.sleep(delay)
    return True, next_retry_count


async def _get_job_status(job_service, job_id: str):
    """Fetch latest job status or None when the job no longer exists."""
    try:
        job = await job_service.get_job(job_id)
        return job.status
    except NotFoundError:
        return None


async def signal_provider_cancellation(*, runtime, provider_id: str, job_id: str) -> bool:
    """Best-effort cancellation request to the active provider runtime."""
    try:
        if runtime.mode in ("container_http", "discovery") and runtime.worker_url:
            http_client = get_http_client()
            response = await http_client.post(
                f"{runtime.worker_url}/cancel-job",
                json={"job_id": job_id},
                timeout=5.0,
            )
            if getattr(response, "status_code", None) == 200:
                logger.info("provider_cancel_signaled", job_id=job_id, provider=provider_id, mode=runtime.mode)
                return True

            logger.warning(
                "provider_cancel_unacknowledged",
                job_id=job_id,
                provider=provider_id,
                mode=runtime.mode,
                status=getattr(response, "status_code", None),
            )
            return False

        if runtime.mode == "external_worker":
            from infrastructure.worker_registry import request_worker_job_cancel

            cancelled = await request_worker_job_cancel(provider_id, job_id)
            if cancelled:
                logger.info("provider_cancel_signaled", job_id=job_id, provider=provider_id, mode=runtime.mode)
                return True
            else:
                logger.warning("provider_cancel_not_connected", job_id=job_id, provider=provider_id, mode=runtime.mode)
            return cancelled
    except Exception as exc:
        logger.warning(
            "provider_cancel_signal_failed",
            job_id=job_id,
            provider=provider_id,
            mode=getattr(runtime, "mode", "unknown"),
            error=str(exc),
        )
    return False


async def _handle_provider_failure(
    runtime,
    provider_id: str,
    job_id: str,
    job_service,
    load_balancer,
    error_type: str
) -> bool:
    """
    Handles provider cancellation signal and checks job status.
    Returns True if the job is terminal (should stop processing), False otherwise.
    """
    cancel_signal_delivered = await signal_provider_cancellation(
        runtime=runtime,
        provider_id=provider_id,
        job_id=job_id,
    )
    if not cancel_signal_delivered:
        logger.warning("provider_cancel_not_confirmed", job_id=job_id, provider=provider_id)
        
    await load_balancer.report_failure(provider_id)
    return False


async def execute_job(
    job_id: str,
    preferred_provider_id: str | None = None,
    *,
    session_context_manager,
    call_image_provider_fn,
    call_llm_provider_fn,
    process_image_background_fn,
    get_timeout_fn,
    get_max_retries_fn,
    get_retry_base_delay_fn,
    get_retry_max_delay_fn,
    get_stagger_delay_fn=None,
):
    """Execute a queued job against providers with retry and fallback handling."""
    # Bound before the try so the failure handler can always release/annotate,
    # even when the failure happened before a provider was ever selected.
    exhausted_providers: set[str] = set()
    current_provider: Provider | None = None
    load_balancer = None
    async with session_context_manager() as session:
        try:
            job_service = JobService(session)

            try:
                job = await job_service.get_job(job_id)
            except NotFoundError:
                logger.warning("job_not_found", job_id=job_id)
                return

            load_balancer = create_load_balancer(session, task_type=job.task_type)

            if job.status != JobStatus.PENDING:
                logger.debug("job_not_pending", job_id=job_id, status=job.status)
                return

            if preferred_provider_id is None:
                preferred_provider_id = (job.metadata_ or {}).get("preferred_provider_id")

            task_type = job.task_type
            timeout = get_timeout_fn(task_type)
            max_retries = get_max_retries_fn(task_type)
            base_delay = get_retry_base_delay_fn(task_type)
            max_delay = get_retry_max_delay_fn(task_type)
            stagger_delay = get_stagger_delay_fn() if get_stagger_delay_fn else 0.0

            retry_count = 0
            required_models = extract_models_from_workflow(job.workflow) if isinstance(job.workflow, dict) else {}

            while True:
                if current_provider is None or current_provider.id in exhausted_providers:
                    if exhausted_providers and stagger_delay > 0:
                        logger.info(
                            "failover_stagger",
                            job_id=job_id,
                            task_type=task_type,
                            delay=stagger_delay,
                            tried=list(exhausted_providers),
                        )
                        await asyncio.sleep(stagger_delay)

                    current_provider = await select_next_provider(
                        load_balancer=load_balancer,
                        job_service=job_service,
                        job_id=job_id,
                        exhausted_providers=exhausted_providers,
                        preferred_provider_id=preferred_provider_id,
                        required_models=required_models,
                        task_type=task_type,
                    )

                    if not current_provider:
                        return
                    retry_count = 0

                attempt = retry_count + 1
                logger.info(
                    "job_processing",
                    job_id=job_id,
                    provider=current_provider.id,
                    attempt=attempt,
                    max_attempts=max_retries + 1,
                )

                # Always re-read: a provider failover resets retry_count to 0, so
                # gating this on `retry_count > 0` left `latest_status` as a
                # stale in-memory value and a job cancelled mid-flight on
                # provider A was still dispatched to provider B.
                job = await job_service.get_job(job_id)
                if job is None:
                    return
                latest_status = job.status
                if latest_status in {JobStatus.CANCELLED, JobStatus.COMPLETED, JobStatus.FAILED}:
                    logger.info(
                        "job_terminal_before_attempt",
                        job_id=job_id,
                        provider=current_provider.id,
                        status=latest_status.value,
                    )
                    await load_balancer.release_job(current_provider.id)
                    return

                await job_service.update_job(
                    job_id,
                    status=JobStatus.SENT_TO_PROVIDER,
                    provider_id=current_provider.id,
                    message=f"Starting on {current_provider.id}...",
                )

                record_attempt = track_attempt(
                    job_service,
                    job_id,
                    provider_id=current_provider.id,
                    attempt=attempt,
                )

                runtime = resolve_provider_runtime(current_provider)
                if not runtime.connected:
                    logger.warning("provider_runtime_unavailable", job_id=job_id, provider=current_provider.id, mode=runtime.mode)
                    await load_balancer.report_failure(current_provider.id)
                    await record_attempt("unavailable", f"Provider runtime {runtime.mode} unavailable")
                    await mark_provider_exhausted(
                        load_balancer=load_balancer,
                        exhausted_providers=exhausted_providers,
                        job_service=job_service,
                        job_id=job_id,
                        provider_id=current_provider.id,
                        message=f"Provider {current_provider.id} is unavailable, trying fallback...",
                    )
                    current_provider = None
                    continue

                total_nodes = len(job.workflow) if isinstance(job.workflow, dict) else 0
                provider_config = current_provider.config or {}
                use_snapshot = provider_config.get("enable_memory_snapshot", False)

                try:
                    if runtime.mode in ("container_http", "discovery"):
                        # Route to the correct provider function based on task type.
                        # call_*_provider_fn already enforces stream/client timeout semantics.
                        # Avoid double-wrapping with asyncio.wait_for to keep timeout ownership clear.
                        if task_type == "llm":
                            final_result = await call_llm_provider_fn(
                                worker_url=runtime.worker_url,
                                workflow=job.workflow,
                                job_id=job_id,
                                job_service=job_service,
                                timeout=timeout,
                                provider_id=current_provider.id,
                                provider_type=current_provider.type,
                            )
                        else:
                            final_result = await call_image_provider_fn(
                                worker_url=runtime.worker_url,
                                workflow=job.workflow,
                                job_id=job_id,
                                job_service=job_service,
                                total_nodes=total_nodes,
                                timeout=timeout,
                                use_snapshot=use_snapshot,
                                provider_id=current_provider.id,
                            )
                    elif runtime.mode == "external_worker":
                        from infrastructure.worker_registry import dispatch_job_to_worker

                        final_result = await dispatch_job_to_worker(
                            current_provider.id,
                            {
                                "id": job.id,
                                "workflow": job.workflow,
                                "metadata": job.metadata_ or {},
                            },
                            timeout=timeout,
                        )
                    else:
                        raise ProviderCallError(
                            f"Provider runtime for {current_provider.id} is unavailable",
                            provider_id=current_provider.id,
                            is_retryable=True,
                        )

                    latest_status = await _get_job_status(job_service, job_id)
                    if latest_status in {JobStatus.CANCELLED, JobStatus.FAILED, JobStatus.COMPLETED}:
                        logger.info(
                            "job_terminal_after_provider_response",
                            job_id=job_id,
                            provider=current_provider.id,
                            status=latest_status.value,
                        )
                        await load_balancer.release_job(current_provider.id)
                        return

                    if final_result.get("__handled_by_external_worker"):
                        await record_attempt("completed")
                        await load_balancer.report_success(current_provider.id)
                        await load_balancer.release_job(current_provider.id)
                    else:
                        await record_attempt("completed")
                        await finalize_successful_job(
                            job=job,
                            job_id=job_id,
                            job_service=job_service,
                            load_balancer=load_balancer,
                            provider_id=current_provider.id,
                            final_result=final_result,
                            process_image_background_fn=process_image_background_fn,
                        )
                    return

                except JobCancelledError as error:
                    logger.info("job_cancelled_by_provider", job_id=job_id, provider=current_provider.id, message=str(error))
                    await record_attempt("cancelled", str(error))
                    latest_status = await _get_job_status(job_service, job_id)
                    if latest_status != JobStatus.CANCELLED:
                        await job_service.update_job(
                            job_id,
                            status=JobStatus.CANCELLED,
                            message=str(error),
                            provider_id=current_provider.id,
                        )
                    await load_balancer.release_job(current_provider.id)
                    return

                except JobTimeoutError as error:
                    logger.warning("job_timeout", job_id=job_id, provider=current_provider.id)
                    await record_attempt("timeout", str(error) or "Provider timed out")
                    await _handle_provider_failure(runtime, current_provider.id, job_id, job_service, load_balancer, "timeout")
                    should_retry, retry_count = await maybe_retry_current_provider(
                        job_service=job_service,
                        job_id=job_id,
                        provider_id=current_provider.id,
                        retry_count=retry_count,
                        max_retries=max_retries,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        retry_message="Retrying after timeout (attempt {attempt})...",
                    )

                    if should_retry:
                        continue

                    logger.warning("provider_max_retries", job_id=job_id, provider=current_provider.id, retries=retry_count)
                    await mark_provider_exhausted(
                        load_balancer=load_balancer,
                        exhausted_providers=exhausted_providers,
                        job_service=job_service,
                        job_id=job_id,
                        provider_id=current_provider.id,
                        message=f"Provider {current_provider.id} exhausted retries, trying fallback...",
                    )
                    current_provider = None
                    continue

                except ProviderCallError as error:
                    logger.warning(
                        "provider_error",
                        job_id=job_id,
                        provider=current_provider.id,
                        provider_error_id=error.provider_id,
                        error=str(error),
                    )
                    await record_attempt(
                        "retryable_error" if error.is_retryable else "error", str(error)
                    )
                    await _handle_provider_failure(runtime, current_provider.id, job_id, job_service, load_balancer, "provider_error")
                    should_retry = False
                    if error.is_retryable:
                        should_retry, retry_count = await maybe_retry_current_provider(
                            job_service=job_service,
                            job_id=job_id,
                            provider_id=current_provider.id,
                            retry_count=retry_count,
                            max_retries=max_retries,
                            base_delay=base_delay,
                            max_delay=max_delay,
                            retry_message="Retrying after error (attempt {attempt})...",
                        )

                    if should_retry:
                        continue

                    failed_provider_id = current_provider.id
                    await mark_provider_exhausted(
                        load_balancer=load_balancer,
                        exhausted_providers=exhausted_providers,
                        job_service=job_service,
                        job_id=job_id,
                        provider_id=failed_provider_id,
                        message=f"Switching providers after error on {failed_provider_id}...",
                    )
                    current_provider = None

                    if not error.is_retryable:
                        logger.warning(
                            "provider_non_retryable",
                            job_id=job_id,
                            provider=failed_provider_id,
                            error=str(error),
                        )

                    continue

                except asyncio.TimeoutError:
                    logger.error("job_timeout_exceeded", job_id=job_id, timeout=timeout)
                    await record_attempt("timeout", f"Timed out after {timeout}s")
                    await _handle_provider_failure(runtime, current_provider.id, job_id, job_service, load_balancer, "timeout_exceeded")
                    await mark_provider_exhausted(
                        load_balancer=load_balancer,
                        exhausted_providers=exhausted_providers,
                        job_service=job_service,
                        job_id=job_id,
                        provider_id=current_provider.id,
                        message=f"Provider {current_provider.id} timed out, trying fallback...",
                    )
                    current_provider = None
                continue

        except Exception as error:
            logger.error("job_processing_error", job_id=job_id, error=str(error), exc_info=True)

            try:
                if current_provider is not None and load_balancer is not None:
                    await load_balancer.release_job(current_provider.id)
                job_service = JobService(session)
                latest_status = await _get_job_status(job_service, job_id)
                if latest_status in {JobStatus.CANCELLED, JobStatus.COMPLETED, JobStatus.FAILED}:
                    return
                await job_service.mark_failed(
                    job_id,
                    error=str(error),
                    error_type=FAILURE_UNEXPECTED,
                )
            except Exception as update_error:
                logger.error("job_update_failed", job_id=job_id, error=str(update_error))
