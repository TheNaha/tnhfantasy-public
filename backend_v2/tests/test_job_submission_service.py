# Tests for services/job_submission_service.py (canonical job submission path)

from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, select

from core.entities import Job, Provider
from core.exceptions import JobError
from services.job_submission_service import JobSubmissionService


def _empty_workflow() -> dict:
    # No model-loader nodes → no required models (skips availability gating)
    return {"nodes": {"1": {"class_type": "EmptyLatentImage", "inputs": {}}}}


def _model_workflow() -> dict:
    return {"nodes": {"1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "dreamshaper.safetensors"}}}}


def _seed_enabled_provider(session: Session) -> str:
    provider = Provider(id="test-modal", type="modal", enabled=True)
    session.add(provider)
    session.commit()
    return provider.id


# ── validate_workflow / build_validation_response ───────────────────────────

def test_validate_workflow_no_models_with_enabled_provider(session):
    _seed_enabled_provider(session)
    svc = JobSubmissionService(session)
    required, availability = svc.validate_workflow(_empty_workflow())
    assert required == {}
    assert availability.valid
    assert "test-modal" in availability.eligible_providers


def test_validate_workflow_no_models_without_providers(session):
    svc = JobSubmissionService(session)
    _, availability = svc.validate_workflow(_empty_workflow())
    assert not availability.valid
    assert availability.eligible_providers == []


def test_validate_workflow_missing_models(session):
    _seed_enabled_provider(session)
    svc = JobSubmissionService(session)
    required, availability = svc.validate_workflow(_model_workflow())
    assert required == {"checkpoints": ["dreamshaper.safetensors"]}
    assert not availability.valid
    assert "checkpoints" in availability.missing_models["test-modal"]


def test_validate_workflow_preferred_provider_restricts_missing(session):
    svc = JobSubmissionService(session)
    _, availability = svc.validate_workflow(_model_workflow(), preferred_provider_id="other-provider")
    # Non-eligible preferred provider surfaces its own (empty) missing set
    assert availability.missing_models == {"other-provider": {}}


def test_build_validation_response_shape(session):
    _seed_enabled_provider(session)
    svc = JobSubmissionService(session)
    resp = svc.build_validation_response(_empty_workflow())
    assert set(resp) == {
        "valid", "eligible_providers", "missing_models",
        "global_missing", "can_trigger_download", "required_models",
    }
    assert resp["valid"] is True


# ── create_and_enqueue_job ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_and_enqueue_job_success(session, monkeypatch):
    _seed_enabled_provider(session)
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr("services.job_submission_service.queue_manager.enqueue", enqueue)

    svc = JobSubmissionService(session)
    job = await svc.create_and_enqueue_job(_empty_workflow(), {"prompt": "hi"})
    assert job.task_type == "image"
    assert job.metadata_ == {"prompt": "hi"}

    enqueue.assert_awaited_once_with(job.id, task_type="image")
    assert session.get(Job, job.id) is not None


@pytest.mark.asyncio
async def test_create_and_enqueue_job_llm_task_type(session, monkeypatch):
    _seed_enabled_provider(session)
    enqueue = AsyncMock(return_value=True)
    monkeypatch.setattr("services.job_submission_service.queue_manager.enqueue", enqueue)

    svc = JobSubmissionService(session)
    job = await svc.create_and_enqueue_job({}, task_type="llm")
    assert job.task_type == "llm"
    enqueue.assert_awaited_once_with(job.id, task_type="llm")


@pytest.mark.asyncio
async def test_create_and_enqueue_job_missing_models_raises(session):
    _seed_enabled_provider(session)
    svc = JobSubmissionService(session)
    with pytest.raises(Exception) as exc_info:
        await svc.create_and_enqueue_job(_model_workflow())
    assert "MissingModels" in type(exc_info.value).__name__


@pytest.mark.asyncio
async def test_create_and_enqueue_job_enqueue_failure_compensates(session, monkeypatch):
    _seed_enabled_provider(session)
    monkeypatch.setattr(
        "services.job_submission_service.queue_manager.enqueue",
        AsyncMock(side_effect=RuntimeError("boom")),
    )

    svc = JobSubmissionService(session)
    with pytest.raises(JobError):
        await svc.create_and_enqueue_job(_empty_workflow())

    # Compensating delete: no orphaned pending job survives
    assert session.exec(select(Job)).all() == []
