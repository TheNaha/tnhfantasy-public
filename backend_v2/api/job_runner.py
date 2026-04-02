import asyncio
from typing import Optional

from api.job_orchestration import (
    create_load_balancer,
    mark_provider_exhausted,
    maybe_retry_current_provider,
    select_next_provider,
)
from api.job_processing import finalize_successful_job
from api.provider_client import JobCancelledError, JobTimeoutError, ProviderCallError
from api.provider_runtime import resolve_provider_runtime
from core.workflow_parser import extract_models_from_workflow
from core.entities import JobStatus
from core.exceptions import NotFoundError
from infrastructure.http_client import get_http_client
from infrastructure.logging import get_logger
from services.job_service import JobService
from services.provider_service import ProviderService

logger = get_logger("job_runner")


async def _get_job_status(job_service, job_id: str):
    """Fetch latest job status or None when the job no longer exists."""
    try:
        job = await job_service.get_job(job_id)
        return job.status
    except NotFoundError:
        return None


async def _signal_provider_cancellation(*, runtime, provider_id: str, job_id: str) -> bool:
    """Best-effort cancellation request to the active provider runtime."""
    try:
        if runtime.mode == "container_http" and runtime.worker_url:
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
            from api.routes.worker_ws import request_worker_job_cancel

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


async def execute_job(
    job_id: str,
    preferred_provider_id: Optional[str] = None,
    *,
    session_factory,
    call_provider_fn,
    process_image_background_fn,
    get_timeout_fn,
    get_max_retries_fn,
    get_retry_base_delay_fn,
    get_retry_max_delay_fn,
):
    """Execute a queued job against providers with retry and fallback handling."""
    session = next(session_factory())
    try:
        job_service = JobService(session)
        provider_service = ProviderService(session)
        load_balancer = create_load_balancer(session, provider_service)

        try:
            job = await job_service.get_job(job_id)
        except NotFoundError:
            logger.warning("job_not_found", job_id=job_id)
            return

        if job.status != JobStatus.PENDING:
            logger.debug("job_not_pending", job_id=job_id, status=job.status)
            return

        timeout = get_timeout_fn()
        max_retries = get_max_retries_fn()
        base_delay = get_retry_base_delay_fn()
        max_delay = get_retry_max_delay_fn()

        exhausted_providers = set()
        current_provider = None
        retry_count = 0
        required_models = extract_models_from_workflow(job.workflow) if isinstance(job.workflow, dict) else {}

        while True:
            if current_provider is None or current_provider.id in exhausted_providers:
                current_provider = await select_next_provider(
                    load_balancer=load_balancer,
                    job_service=job_service,
                    job_id=job_id,
                    exhausted_providers=exhausted_providers,
                    preferred_provider_id=preferred_provider_id,
                    required_models=required_models,
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

            latest_status = await _get_job_status(job_service, job_id)
            if latest_status in {JobStatus.CANCELLED, JobStatus.COMPLETED, JobStatus.FAILED}:
                logger.info(
                    "job_terminal_before_attempt",
                    job_id=job_id,
                    provider=current_provider.id,
                    status=latest_status.value,
                )
                load_balancer.release_job(current_provider.id)
                return

            await job_service.update_job(
                job_id,
                status=JobStatus.RUNNING,
                provider_id=current_provider.id,
                message=f"Starting on {current_provider.id}...",
            )

            runtime = resolve_provider_runtime(current_provider)
            if not runtime.connected:
                logger.warning("provider_runtime_unavailable", job_id=job_id, provider=current_provider.id, mode=runtime.mode)
                load_balancer.report_failure(current_provider.id)
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
                if runtime.mode == "container_http":
                    final_result = await asyncio.wait_for(
                        call_provider_fn(
                            worker_url=runtime.worker_url,
                            workflow=job.workflow,
                            job_id=job_id,
                            job_service=job_service,
                            total_nodes=total_nodes,
                            timeout=timeout,
                            use_snapshot=use_snapshot,
                            provider_id=current_provider.id,
                        ),
                        timeout=timeout,
                    )
                elif runtime.mode == "external_worker":
                    from api.routes.worker_ws import dispatch_job_to_worker

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
                    load_balancer.release_job(current_provider.id)
                    return

                if final_result.get("__handled_by_external_worker"):
                    load_balancer.report_success(current_provider.id)
                    load_balancer.release_job(current_provider.id)
                else:
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
                latest_status = await _get_job_status(job_service, job_id)
                if latest_status != JobStatus.CANCELLED:
                    await job_service.update_job(
                        job_id,
                        status=JobStatus.CANCELLED,
                        message=str(error),
                        provider_id=current_provider.id,
                    )
                load_balancer.release_job(current_provider.id)
                return

            except JobTimeoutError:
                logger.warning("job_timeout", job_id=job_id, provider=current_provider.id)
                cancel_signal_delivered = await _signal_provider_cancellation(
                    runtime=runtime,
                    provider_id=current_provider.id,
                    job_id=job_id,
                )
                if not cancel_signal_delivered:
                    logger.warning("provider_cancel_not_confirmed", job_id=job_id, provider=current_provider.id)
                latest_status = await _get_job_status(job_service, job_id)
                if latest_status == JobStatus.CANCELLED:
                    logger.info("job_cancelled_after_timeout", job_id=job_id, provider=current_provider.id)
                    load_balancer.release_job(current_provider.id)
                    return
                load_balancer.report_failure(current_provider.id)
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
                cancel_signal_delivered = await _signal_provider_cancellation(
                    runtime=runtime,
                    provider_id=current_provider.id,
                    job_id=job_id,
                )
                if not cancel_signal_delivered:
                    logger.warning("provider_cancel_not_confirmed", job_id=job_id, provider=current_provider.id)
                refreshed_job = await job_service.get_job(job_id)
                if refreshed_job.status in {JobStatus.CANCELLED, JobStatus.FAILED, JobStatus.COMPLETED}:
                    load_balancer.release_job(current_provider.id)
                    return
                load_balancer.report_failure(current_provider.id)
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
                cancel_signal_delivered = await _signal_provider_cancellation(
                    runtime=runtime,
                    provider_id=current_provider.id,
                    job_id=job_id,
                )
                if not cancel_signal_delivered:
                    logger.warning("provider_cancel_not_confirmed", job_id=job_id, provider=current_provider.id)
                latest_status = await _get_job_status(job_service, job_id)
                if latest_status == JobStatus.CANCELLED:
                    logger.info("job_cancelled_after_timeout_exceeded", job_id=job_id, provider=current_provider.id)
                    load_balancer.release_job(current_provider.id)
                    return
                load_balancer.report_failure(current_provider.id)
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
            job_service = JobService(session)
            latest_status = await _get_job_status(job_service, job_id)
            if latest_status in {JobStatus.CANCELLED, JobStatus.COMPLETED, JobStatus.FAILED}:
                return
            await job_service.update_job(
                job_id,
                status=JobStatus.FAILED,
                error=str(error),
            )
        except Exception as update_error:
            logger.error("job_update_failed", job_id=job_id, error=str(update_error))
    finally:
        session.close()
