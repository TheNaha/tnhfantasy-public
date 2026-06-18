import asyncio
from typing import Optional, Set, Tuple

from core.entities import JobStatus, Provider
from infrastructure.logging import get_logger
from services.load_balancer import LoadBalancer
from services.load_balancer_factory import create_load_balancer as create_balancer

logger = get_logger("job_orchestration")


def create_load_balancer(session, provider_service) -> LoadBalancer:
    """Create a load balancer using the currently configured strategy."""
    lb_config = provider_service.get_load_balancing_config()
    strategy = lb_config.strategy if lb_config else None
    return create_balancer(session, strategy=strategy)


async def mark_provider_exhausted(
    *,
    load_balancer: LoadBalancer,
    exhausted_providers: Set[str],
    job_service,
    job_id: str,
    provider_id: str,
    message: str,
) -> None:
    """Release provider state and move the job back to pending before trying another provider."""
    load_balancer.release_job(provider_id)
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
    exhausted_providers: Set[str],
    preferred_provider_id: Optional[str],
    required_models: Optional[dict] = None,
) -> Optional[Provider]:
    """Select the next provider or fail the job when no providers remain."""
    provider = await asyncio.to_thread(
        load_balancer.get_next_provider,
        preferred_provider_id=preferred_provider_id,
        required_models=required_models,
        exclude_provider_ids=exhausted_providers,
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
) -> Tuple[bool, int]:
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
        status=JobStatus.PENDING,
        message=retry_message.format(attempt=next_retry_count + 1),
    )
    await asyncio.sleep(delay)
    return True, next_retry_count
