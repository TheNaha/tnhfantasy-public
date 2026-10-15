import asyncio
from typing import Any

from sqlmodel import Session

from core.exceptions import JobError, MissingModelsError
from core.workflow_parser import extract_models_from_workflow
from infrastructure.logging import get_logger
from services.job_queue import queue_manager
from services.job_service import JobService
from services.model_availability_service import (
    AvailabilityResult,
    ModelAvailabilityService,
)

logger = get_logger("job_submission")


class JobSubmissionService:
    """Canonical job submission path shared by all active job-creation routes."""

    def __init__(self, session: Session):
        self.session = session
        self.job_service = JobService(session)
        self.availability_service = ModelAvailabilityService(session)

    def validate_workflow(
        self,
        workflow: dict[str, Any],
        *,
        preferred_provider_id: str | None = None,
    ) -> tuple[dict[str, Any], AvailabilityResult]:
        required_models = extract_models_from_workflow(workflow)
        availability = self.availability_service.check_availability(required_models)

        if preferred_provider_id:
            if preferred_provider_id in availability.eligible_providers:
                availability.eligible_providers = [preferred_provider_id]
            else:
                availability.eligible_providers = []
                availability.valid = False
                availability.missing_models = {
                    preferred_provider_id: availability.missing_models.get(preferred_provider_id, {})
                }

        return required_models, availability

    def build_validation_response(
        self,
        workflow: dict[str, Any],
        *,
        preferred_provider_id: str | None = None,
    ) -> dict[str, Any]:
        required_models, result = self.validate_workflow(
            workflow,
            preferred_provider_id=preferred_provider_id,
        )
        return {
            "valid": result.valid,
            "eligible_providers": result.eligible_providers,
            "missing_models": result.missing_models,
            "global_missing": result.global_missing,
            "can_trigger_download": result.can_trigger_download,
            "required_models": required_models,
        }

    async def create_and_enqueue_job(
        self,
        workflow: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        *,
        preferred_provider_id: str | None = None,
        task_type: str = "image",
    ):
        def _resolve_and_validate():
            """The database prologue: resolve the provider, then validate the
            workflow against what is actually installed.

            BLOCKING — three or four queries. This is the caller-visible cost of
            `submit_image_job` and it was running inline on the event loop, once
            per generate/illustrate/narrate request, while the request that asked
            for it waited. The only genuinely async part of this method is the
            `await` on `create_job` and `enqueue` below, so the prologue is the
            part that can move.

            Returning rather than mutating keeps the `metadata` rebinding visible:
            `preferred_provider_id` is reassigned here and used after the
            `await`, so it has to come back out of the worker thread.
            """
            resolved_metadata = dict(metadata or {})
            resolved_provider_id = preferred_provider_id
            if task_type == "llm" and not resolved_provider_id:
                from services.llm_config import resolve_default_provider

                try:
                    resolved = resolve_default_provider(self.session)
                except Exception:
                    resolved = None
                if resolved:
                    resolved_provider_id = resolved[0]
                    resolved_metadata.setdefault("llm_model", resolved[1])
            if resolved_provider_id:
                resolved_metadata = {
                    **resolved_metadata,
                    "preferred_provider_id": resolved_provider_id,
                }
            required, avail = self.validate_workflow(
                workflow,
                preferred_provider_id=resolved_provider_id,
            )
            return resolved_metadata, resolved_provider_id, required, avail

        metadata, preferred_provider_id, required_models, availability = (
            await asyncio.to_thread(_resolve_and_validate)
        )

        if required_models and not availability.valid:
            logger.warning("job_creation_missing_models", global_missing=availability.global_missing)
            raise MissingModelsError(
                required_models=required_models,
                global_missing=availability.global_missing,
                missing_by_provider=availability.missing_models,
                can_trigger_download=availability.can_trigger_download,
            )

        job = await self.job_service.create_job(workflow, metadata, task_type=task_type)
        try:
            await queue_manager.enqueue(job.id, task_type=task_type)
        except Exception as exc:
            logger.error("job_enqueue_failed", job_id=job.id, error=str(exc))

            try:
                self.job_service.repo.delete(job.id)
            except Exception as cleanup_exc:
                logger.error("job_enqueue_cleanup_failed", job_id=job.id, error=str(cleanup_exc))

            raise JobError(job_id=job.id, message="Failed to enqueue job. Please retry.") from exc

        logger.info("job_enqueued", job_id=job.id)
        return job


async def submit_job(
    session: Session,
    workflow: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    *,
    task_type: str,
    preferred_provider_id: str | None = None,
):
    """The one place any job enters the pipeline.

    `JobSubmissionService` was, by its own docstring, the canonical submission
    path "shared by all active job-creation routes" — but only the image routes
    used it. Every LLM and TTS route hand-rolled
    `JobService.create_job(task_type=...)` followed by
    `queue_manager.enqueue(job.id, task_type=...)`, each with its own idea of
    the metadata rebinding, the LLM default-provider resolution, and the
    enqueue-failure rollback. 21 call sites, one contract.

    This is that contract. An LLM or TTS workflow carries no ComfyUI model
    loaders, so `validate_workflow` extracts nothing and behaves as a no-op —
    which is why the same function is safe for all three task types.
    """
    submission = JobSubmissionService(session)
    return await submission.create_and_enqueue_job(
        workflow,
        metadata=metadata,
        task_type=task_type,
        preferred_provider_id=preferred_provider_id,
    )


async def submit_llm_job(
    session: Session,
    workflow: dict[str, Any],
    metadata: dict[str, Any] | None = None,
):
    """Submit an LLM job. See `submit_job` for why this is not hand-rolled."""
    return await submit_job(session, workflow, metadata, task_type="llm")


async def submit_tts_job(
    session: Session,
    workflow: dict[str, Any],
    metadata: dict[str, Any] | None = None,
):
    """Submit a TTS job. See `submit_job` for why this is not hand-rolled."""
    return await submit_job(session, workflow, metadata, task_type="tts")
