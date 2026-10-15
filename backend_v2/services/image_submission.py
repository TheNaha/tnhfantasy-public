"""Image job submission helper.

Wraps the common pattern:
  checkpoint resolution -> workflow build -> validate -> create job -> enqueue

All call sites should use this instead of manually calling
`build_image_job_workflow` + `JobService.create_job` + `queue_manager.enqueue`.
"""
from __future__ import annotations

from typing import Any

from core.workflow_builder import build_image_job_workflow
from services.job_submission_service import JobSubmissionService
from services.model_availability_service import ModelAvailabilityService


async def submit_image_job(
    session,
    *,
    prompt: str,
    negative_prompt: str | None = None,
    checkpoint: str | None = None,
    lora: str | None = None,
    filename_prefix: str | None = None,
    source: str | None = None,
    workspace: str = "main",
    chat_id: str | None = None,
    character_id: str | None = None,
    story_id: str | None = None,
    chapter_id: str | None = None,
    parent_job_id: str | None = None,
    branch_id: str | None = None,
    task_type: str = "image",
    extra_metadata: dict[str, Any] | None = None,
    preferred_provider_id: str | None = None,
) -> Any:
    """Build, validate, create and enqueue an image job.

    Returns the created Job.
    """
    # Resolve checkpoint: preferred → config default → hardcoded fallback.
    # Unlike resolve_checkpoint(), we preserve the *preferred* name in the
    # metadata even when it's not installed — the JobSubmissionService
    # validation layer will catch the missing model and produce the right
    # error message.  If the preferred isn't installed but *some* checkpoint
    # is, we use that to avoid a false MISSING_MODELS error.
    availability = ModelAvailabilityService(session)
    from config import resolve_default_checkpoint

    fallback_name = checkpoint or resolve_default_checkpoint()
    resolved_checkpoint = availability.get_available_checkpoint(fallback_name) or fallback_name

    workflow, metadata = build_image_job_workflow(
        prompt=prompt,
        negative=negative_prompt or "",
        checkpoint=resolved_checkpoint,
        lora=lora,
        filename_prefix=filename_prefix,
        source=source,
        workspace=workspace,
        chat_id=chat_id,
        character_id=character_id,
        story_id=story_id,
        chapter_id=chapter_id,
        parent_job_id=parent_job_id,
        branch_id=branch_id,
        extra_metadata=extra_metadata,
    )

    submission = JobSubmissionService(session)
    return await submission.create_and_enqueue_job(
        workflow,
        metadata=metadata,
        task_type=task_type,
        preferred_provider_id=preferred_provider_id,
    )
