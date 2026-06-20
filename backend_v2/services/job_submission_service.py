from typing import Any, Dict, Optional, Tuple

from sqlmodel import Session

from core.exceptions import JobError, MissingModelsError
from core.workflow_parser import extract_models_from_workflow
from infrastructure.logging import get_logger
from services.job_queue import job_queue
from services.job_service import JobService
from services.model_availability_service import AvailabilityResult, ModelAvailabilityService

logger = get_logger("job_submission")


class JobSubmissionService:
    """Canonical job submission path shared by all active job-creation routes."""

    def __init__(self, session: Session):
        self.session = session
        self.job_service = JobService(session)
        self.availability_service = ModelAvailabilityService(session)

    def validate_workflow(
        self,
        workflow: Dict[str, Any],
        *,
        preferred_provider_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], AvailabilityResult]:
        required_models = extract_models_from_workflow(workflow)
        availability = self.availability_service.check_availability(required_models)

        if preferred_provider_id and preferred_provider_id not in availability.eligible_providers:
            availability.missing_models = {
                preferred_provider_id: availability.missing_models.get(preferred_provider_id, {})
            }

        return required_models, availability

    def build_validation_response(
        self,
        workflow: Dict[str, Any],
        *,
        preferred_provider_id: Optional[str] = None,
    ) -> Dict[str, Any]:
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
        workflow: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        *,
        preferred_provider_id: Optional[str] = None,
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

        job = await self.job_service.create_job(workflow, metadata)
        try:
            await job_queue.enqueue(job.id)
        except Exception as exc:
            logger.error("job_enqueue_failed", job_id=job.id, error=str(exc))

            # Compensating action: best-effort delete so callers don't leave
            # orphaned pending jobs that never execute.
            try:
                self.job_service.repo.delete(job.id)
            except Exception as cleanup_exc:
                logger.error("job_enqueue_cleanup_failed", job_id=job.id, error=str(cleanup_exc))

            raise JobError(job_id=job.id, message="Failed to enqueue job. Please retry.") from exc

        logger.info("job_enqueued", job_id=job.id)
        return job
