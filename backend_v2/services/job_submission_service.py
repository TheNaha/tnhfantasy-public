from typing import Any

from sqlmodel import Session

from core.exceptions import JobError, MissingModelsError
from core.workflow_builder import build_image_workflow
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

        if preferred_provider_id and preferred_provider_id not in availability.eligible_providers:
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
        metadata = metadata or {}
        required_models, availability = self.validate_workflow(
            workflow,
            preferred_provider_id=preferred_provider_id,
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

    async def build_image_job(
        self,
        prompt: str,
        *,
        negative_prompt: str | None = None,
        checkpoint: str | None = None,
        filename_prefix: str = "ComfyUI",
        workspace: str = "main",
        character_id: str | None = None,
        story_id: str | None = None,
        source: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
        preferred_provider_id: str | None = None,
    ) -> Any:
        """Build an image workflow, validate models, create and enqueue the job.

        Returns the created Job.
        """
        from core.workflow_builder import DEFAULT_NEGATIVE_PROMPT, build_image_job_workflow

        workflow, metadata = build_image_job_workflow(
            prompt=prompt,
            negative=negative_prompt or DEFAULT_NEGATIVE_PROMPT,
            checkpoint=checkpoint or "sd_xl_base_1.0.safetensors",
            filename_prefix=filename_prefix,
            source=source,
            workspace=workspace,
            character_id=character_id,
            story_id=story_id,
            extra_metadata=extra_metadata,
        )

        return await self.create_and_enqueue_job(
            workflow,
            metadata=metadata,
            task_type="image",
            preferred_provider_id=preferred_provider_id,
        )
