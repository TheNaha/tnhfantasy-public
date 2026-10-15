from datetime import datetime, timedelta, timezone

from api.deps import get_session_sync
from infrastructure.logging import get_logger
from services.job_service import JobService

logger = get_logger("startup_helpers")


def configure_worker_pool() -> None:
    """Set worker counts per category from the enabled providers.

    One worker per enabled provider in that category, floored at one so a
    category with no provider still has a pool to log and to recover into.

    The old rule was `worker_type != "llm" counts as image`, which is why a
    `tts` provider silently grew image capacity and its own category stayed
    permanently sized at the floor of one — no matter how many TTS workers you
    enabled.
    """
    try:
        from core.entities import (
            CATEGORY_IMAGE,
            CATEGORY_LLM,
            CATEGORY_TTS,
            VALID_CATEGORIES,
        )
        from infrastructure.repositories import ProviderRepository
        from services.job_queue import queue_manager

        session = get_session_sync()
        try:
            provider_repo = ProviderRepository(session)
            enabled_providers = provider_repo.get_enabled()

            counts = {category: 0 for category in sorted(VALID_CATEGORIES)}
            for provider in enabled_providers:
                # `category` is the `worker_type` column read through its proper
                # name. Hybrid providers provide both image and LLM capability.
                category = getattr(provider, "worker_type", "") or CATEGORY_IMAGE
                if category == "hybrid":
                    counts[CATEGORY_IMAGE] += 1
                    counts[CATEGORY_LLM] += 1
                elif category in counts:
                    counts[category] += 1
                else:
                    counts[CATEGORY_IMAGE] += 1

            sizing = {category: max(1, count) for category, count in counts.items()}

            # LLM is sized by the WORK, not by the provider count.
            #
            # It used to be one worker per enabled LLM provider, which was right
            # when one provider meant one model meant one request at a time. It
            # is not right now: `rp` and `util` can share one set of weights, so
            # a deployment with one provider still has two kinds of work
            # contending for one coroutine — chat replies, agentic follow-ups,
            # narrator jobs, suggest jobs, memory extractions and story
            # continuations all in a single lane. A memory extraction blocked
            # the next reply.
            #
            # Per-provider sizing became a proxy for concurrency, and the
            # provider count stopped being a proxy for the number of things a
            # provider is asked to do at once. `llm.max_workers` is the real
            # answer; it defaults to 2 (reply + one background job), which is
            # what a single user generates.
            from config import get_config

            configured_llm = (get_config() or {}).get("llm", {}).get("max_workers", 2)
            try:
                sizing[CATEGORY_LLM] = max(1, int(configured_llm))
            except (TypeError, ValueError):
                sizing[CATEGORY_LLM] = 2

            counts.setdefault(CATEGORY_IMAGE, sizing.get(CATEGORY_IMAGE, 1))
            counts.setdefault(CATEGORY_LLM, sizing.get(CATEGORY_LLM, 1))
            counts.setdefault(CATEGORY_TTS, sizing.get(CATEGORY_TTS, 1))
            queue_manager.resize(**sizing)
            logger.info("worker_pool_configured", providers_per_category=counts, **sizing)
        finally:
            session.close()
    except Exception as exc:
        logger.warning("worker_pool_error", error=str(exc))



async def recover_pending_jobs() -> None:
    """Recover pending and in-flight jobs after startup, routed by task_type."""
    try:
        from services.job_queue import queue_manager

        recovery_session = get_session_sync()
        try:
            recovery_job_service = JobService(recovery_session)
            await queue_manager.recover_pending_jobs(recovery_job_service)
        finally:
            recovery_session.close()
    except Exception as exc:
        logger.warning("job_recovery_failed", error=str(exc))



def cleanup_provider_state_artifacts(
    stale_downloading_after_minutes: int = 120,
    *,
    skip_orphan_cleanup: bool = False,
) -> None:
    """Reset stale downloading entries and optionally clean orphaned provider statuses.
    
    Does NOT purge provider records — let the discovery heartbeat system
    (POST /api/v2/providers/discovery) upsert live provider records.
    Providers from old backups are harmless; they get overwritten when
    the live container sends its first discovery heartbeat.
    
    Args:
        stale_downloading_after_minutes: Reset downloading statuses older than this.
        skip_orphan_cleanup: If True, skip deleting orphaned provider statuses.
            Use this on initial startup to avoid a race where providers haven't
            re-registered yet and their statuses would be wrongly deleted.
    """
    try:
        from infrastructure.repositories import ProviderRepository
        from infrastructure.repositories.model_repo_v2 import ModelRepositoryV2

        session = get_session_sync()
        try:
            provider_repo = ProviderRepository(session)
            all_providers = provider_repo.get_all()
            active_provider_ids = [p.id for p in all_providers]

            model_repo = ModelRepositoryV2(session)
            orphaned_result = {"deleted_count": 0, "orphaned_providers": []}
            if not skip_orphan_cleanup:
                orphaned_result = model_repo.cleanup_orphaned_provider_statuses(active_provider_ids)
            stale_before = datetime.now(timezone.utc) - timedelta(minutes=stale_downloading_after_minutes)
            stale_resets = model_repo.reset_stale_downloading_statuses(
                stale_before=stale_before,
                provider_names=active_provider_ids,
            )

            logger.info(
                "provider_state_cleanup_complete",
                active_providers=len(active_provider_ids),
                orphaned_statuses_deleted=orphaned_result.get("deleted_count", 0),
                stale_downloading_reset=stale_resets,
            )
        finally:
            session.close()
    except Exception as exc:
        logger.warning("provider_state_cleanup_failed", error=str(exc))


def reset_interrupted_reconciliations() -> None:
    """Reset any provider reconciliation states left in-progress across backend restarts."""
    try:
        from infrastructure.repositories import ProviderRepository
        from services.provider_service import ProviderService

        session = get_session_sync()
        try:
            repo = ProviderRepository(session)
            service = ProviderService(session)
            reset_count = 0
            for p in repo.get_all():
                recon = (p.config or {}).get("reconciliation_state", {})
                if recon.get("status") in ("reconciling", "queued"):
                    service.upsert_reconciliation_state(
                        p.id,
                        {
                            "status": "idle",
                            "phase": "idle",
                            "message": "Reconciliation interrupted by backend restart; click Reconcile or Quick Sync to resume.",
                        },
                    )
                    reset_count += 1
            if reset_count:
                session.commit()
                logger.info("reconciliations_interrupted_reset", count=reset_count)
        finally:
            session.close()
    except Exception as exc:
        logger.warning("reset_interrupted_reconciliations_failed", error=str(exc))
