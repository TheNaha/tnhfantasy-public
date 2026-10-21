"""`fallback_enabled` has to mean something.

It was a persisted column, an API field on GET and PUT, and a rendered row in
the load-balancer bar — and nothing read it. The balancer failed over
unconditionally, so a user who turned fallback off saw it persist, saw the
API report success, and watched the job move to another provider anyway.

The flag now decides: with it off, the first provider that fails ends the
job, with a diagnostic that says why, instead of silently trying the next
candidate.

The flag is read through the accessor that already existed for it —
`ProviderService.get_load_balancing_config` — so the settings API and the job
path cannot disagree about what the setting says. These tests write the
setting through the repository that accessor reads, so they fail if the job
path stops reading it or reads a different flag.
"""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from api.main import process_job
from core.entities import JobStatus, Provider
from infrastructure.repositories.provider_repo import LoadBalancingRepository
from services.job_service import JobService
from services.load_balancer import LoadBalancer
from services.provider_client import ProviderCallError


def _session_override(session: Session):
    @asynccontextmanager
    async def fake_get_session_context():
        yield session

    return fake_get_session_context


def _add_provider(session: Session, provider_id: str, priority: int):
    provider = Provider(
        id=provider_id,
        type="modal",
        enabled=True,
        priority=priority,
        credentials={"token_id": "ak-1", "token_secret": "as-1"},
        config={},
    )
    session.add(provider)
    session.commit()
    return provider


async def _get_job_from_fresh_session(session: Session, job_id: str, attempts: int = 250):
    job_service = JobService(session)
    for _ in range(attempts):
        session.expire_all()
        job = await job_service.get_job(job_id)
        if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return job
        await asyncio.sleep(0.05)

    session.expire_all()
    return await job_service.get_job(job_id)


def _set_fallback_enabled(session: Session, enabled: bool):
    LoadBalancingRepository(session).update(fallback_enabled=enabled)


@pytest.mark.asyncio
async def test_fallback_disabled_does_not_try_the_second_provider(
    session: Session, sample_workflow, monkeypatch
):
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1)
    _add_provider(session, "provider-2", 2)
    _set_fallback_enabled(session, False)

    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata={})

    tried = []

    async def fake_call_image_provider(**kwargs):
        tried.append(kwargs["provider_id"])
        raise ProviderCallError(
            "bad workflow", provider_id=kwargs["provider_id"], is_retryable=False
        )

    monkeypatch.setattr("api.main.get_session_context", _session_override(session))
    monkeypatch.setattr("services.provider_client.call_in_process_image_provider", fake_call_image_provider)
    monkeypatch.setattr("api.main.get_job_max_retries", lambda task_type="image": 0)

    await process_job(job.id)

    updated_job = await _get_job_from_fresh_session(session, job.id)
    assert updated_job.status == JobStatus.FAILED
    assert tried == ["provider-1"], "the job failed over with fallback disabled"
    assert "fallback" in (updated_job.error or "").lower()

    LoadBalancer.reset_state()


@pytest.mark.asyncio
async def test_fallback_enabled_still_tries_the_second_provider(
    session: Session, sample_workflow, monkeypatch
):
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1)
    _add_provider(session, "provider-2", 2)
    _set_fallback_enabled(session, True)

    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata={})

    tried = []

    async def fake_call_image_provider(**kwargs):
        tried.append(kwargs["provider_id"])
        if kwargs["provider_id"] == "provider-1":
            raise ProviderCallError(
                "bad workflow", provider_id="provider-1", is_retryable=False
            )
        return {"images": []}

    monkeypatch.setattr("api.main.get_session_context", _session_override(session))
    monkeypatch.setattr("services.provider_client.call_in_process_image_provider", fake_call_image_provider)
    monkeypatch.setattr("api.main.get_job_max_retries", lambda task_type="image": 0)

    await process_job(job.id)

    updated_job = await _get_job_from_fresh_session(session, job.id)
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.provider_id == "provider-2"
    assert tried == ["provider-1", "provider-2"]

    LoadBalancer.reset_state()


@pytest.mark.asyncio
async def test_the_flag_is_read_through_the_shared_accessor(
    session: Session, sample_workflow, monkeypatch
):
    """The job path reads `ProviderService.get_load_balancing_config` — the
    same accessor the settings API writes through. A different reader would
    let the two disagree again."""
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1)
    _add_provider(session, "provider-2", 2)

    seen = {}

    def fake_get_load_balancing_config(self):
        seen["called"] = True
        return SimpleNamespace(strategy="priority", fallback_enabled=False)

    monkeypatch.setattr(
        "services.job_runner.ProviderService.get_load_balancing_config",
        fake_get_load_balancing_config,
    )

    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata={})

    async def fake_call_image_provider(**kwargs):
        raise ProviderCallError("bad workflow", provider_id=kwargs["provider_id"], is_retryable=False)

    monkeypatch.setattr("api.main.get_session_context", _session_override(session))
    monkeypatch.setattr("services.provider_client.call_in_process_image_provider", fake_call_image_provider)
    monkeypatch.setattr("api.main.get_job_max_retries", lambda task_type="image": 0)

    await process_job(job.id)

    assert seen.get("called"), "the job path never asked for the load-balancing config"
    updated_job = await _get_job_from_fresh_session(session, job.id)
    assert updated_job.status == JobStatus.FAILED

    LoadBalancer.reset_state()
