from types import SimpleNamespace

import pytest

from services.job_orchestration import maybe_retry_current_provider, select_next_provider
from core.entities import JobStatus


class StubJobService:
    def __init__(self):
        self.calls = []

    async def update_job(self, job_id, **kwargs):
        self.calls.append((job_id, kwargs))


class StubLoadBalancer:
    async def release_job(self, p): pass
    async def report_success(self, p): pass
    async def report_failure(self, p): pass
    async def get_stats(self): return {}

    def __init__(self, provider=None):
        self.provider = provider
        self.calls = []

    async def get_next_provider(self, preferred_provider_id=None, required_models=None, exclude_provider_ids=None):
        self.calls.append((preferred_provider_id, required_models, exclude_provider_ids))
        return self.provider


@pytest.mark.asyncio
async def test_select_next_provider_marks_job_failed_when_none_available():
    job_service = StubJobService()
    load_balancer = StubLoadBalancer(provider=None)

    provider = await select_next_provider(
        load_balancer=load_balancer,
        job_service=job_service,
        job_id="job-1",
        exhausted_providers=set(),
        preferred_provider_id=None,
    )

    assert provider is None
    assert job_service.calls == [
        (
            "job-1",
            {"status": JobStatus.FAILED, "error": "No available providers"},
        )
    ]


@pytest.mark.asyncio
async def test_maybe_retry_current_provider_updates_job_and_returns_true(monkeypatch):
    job_service = StubJobService()
    sleep_calls = []

    async def fake_sleep(delay):
        sleep_calls.append(delay)

    monkeypatch.setattr("services.job_orchestration.asyncio.sleep", fake_sleep)

    should_retry, next_retry_count = await maybe_retry_current_provider(
        job_service=job_service,
        job_id="job-2",
        provider_id="provider-1",
        retry_count=0,
        max_retries=2,
        base_delay=1,
        max_delay=10,
        retry_message="Retrying after error (attempt {attempt})...",
    )

    assert should_retry is True
    assert next_retry_count == 1
    assert sleep_calls == [1]
    assert job_service.calls == [
        (
            "job-2",
            {
                "status": JobStatus.PENDING,
                "message": "Retrying after error (attempt 1)...",
            },
        )
    ]


@pytest.mark.asyncio
async def test_select_next_provider_returns_provider_when_available():
    provider = SimpleNamespace(id="provider-1")
    job_service = StubJobService()
    load_balancer = StubLoadBalancer(provider=provider)
    exhausted = {"provider-2"}

    result = await select_next_provider(
        load_balancer=load_balancer,
        job_service=job_service,
        job_id="job-3",
        exhausted_providers=exhausted,
        preferred_provider_id="provider-1",
    )

    assert result is provider
    assert job_service.calls == []
    assert load_balancer.calls == [("provider-1", None, exhausted)]
