import base64
import io
import json
import os
from types import SimpleNamespace

from PIL import Image

import pytest
from sqlmodel import Session

from api.main import process_job
from api.provider_client import ProviderCallError
from core.entities import JobStatus, Provider
from services.job_service import JobService
from services.load_balancer import LoadBalancer


def _session_override(session: Session):
    def fake_get_session():
        yield session

    return fake_get_session


def _add_provider(session: Session, provider_id: str, priority: int, container_config):
    provider = Provider(
        id=provider_id,
        type="modal",
        enabled=True,
        priority=priority,
        credentials={},
        config={},
        container_config=container_config,
    )
    session.add(provider)
    session.commit()
    return provider


@pytest.mark.asyncio
async def test_process_job_falls_back_when_provider_missing_container_config(session: Session, sample_workflow, monkeypatch):
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1, None)
    _add_provider(session, "provider-2", 2, {"port": 8000})

    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata={})

    async def fake_call_provider(**kwargs):
        assert kwargs["worker_url"] == "http://comfy-provider-provider-2:8000"
        return {"images": []}

    monkeypatch.setattr("api.main.get_session", _session_override(session))
    monkeypatch.setattr("api.main._call_provider", fake_call_provider)
    monkeypatch.setattr("api.job_runner.ProviderService.get_load_balancing_config", lambda self: SimpleNamespace(strategy="priority"))

    await process_job(job.id)

    updated_job = await job_service.get_job(job.id)
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.provider_id == "provider-2"

    stats = LoadBalancer(session, strategy="priority").get_stats()
    provider_stats = {item["id"]: item for item in stats["provider_stats"]}
    assert provider_stats["provider-1"]["jobs_assigned"] == 0
    assert provider_stats["provider-1"]["failures"] == 1
    assert provider_stats["provider-2"]["jobs_assigned"] == 0

    LoadBalancer.reset_state()


@pytest.mark.asyncio
async def test_process_job_falls_back_after_non_retryable_provider_error(session: Session, sample_workflow, monkeypatch):
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1, {"port": 8000})
    _add_provider(session, "provider-2", 2, {"port": 8000})

    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata={})

    async def fake_call_provider(**kwargs):
        worker_url = kwargs["worker_url"]
        if worker_url == "http://comfy-provider-provider-1:8000":
            raise ProviderCallError("bad workflow", provider_id="provider-1", is_retryable=False)
        return {"images": []}

    monkeypatch.setattr("api.main.get_session", _session_override(session))
    monkeypatch.setattr("api.main._call_provider", fake_call_provider)
    monkeypatch.setattr("api.job_runner.ProviderService.get_load_balancing_config", lambda self: SimpleNamespace(strategy="priority"))
    monkeypatch.setattr("api.main.get_job_max_retries", lambda: 0)

    await process_job(job.id)

    updated_job = await job_service.get_job(job.id)
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.provider_id == "provider-2"

    stats = LoadBalancer(session, strategy="priority").get_stats()
    provider_stats = {item["id"]: item for item in stats["provider_stats"]}
    assert provider_stats["provider-1"]["jobs_assigned"] == 0
    assert provider_stats["provider-1"]["failures"] == 1
    assert provider_stats["provider-2"]["jobs_assigned"] == 0

    LoadBalancer.reset_state()


@pytest.mark.asyncio
async def test_process_job_writes_sidecar_metadata_when_embedded_save_fails(session: Session, sample_workflow, monkeypatch, tmp_path):
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1, {"port": 8000})

    metadata = {"prompt": "hello", "seed": 42}
    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata=metadata)

    image = Image.new("RGB", (8, 8), color=(255, 0, 0))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")

    async def fake_call_provider(**kwargs):
        return {
            "images": [
                {
                    "filename": "result.png",
                    "data": encoded,
                    "_base64_encoded": True,
                }
            ]
        }

    async def fake_process_image_background(image_path, job_id):
        return None

    monkeypatch.setattr("api.main.get_session", _session_override(session))
    monkeypatch.setattr("api.main._call_provider", fake_call_provider)
    monkeypatch.setattr("api.job_runner.ProviderService.get_load_balancing_config", lambda self: SimpleNamespace(strategy="priority"))
    monkeypatch.setattr("api.main._process_image_background", fake_process_image_background)
    monkeypatch.setattr("api.job_processing.os.path.relpath", lambda target, base: ".")
    monkeypatch.setattr("infrastructure.image_processor.get_output_path", lambda base_dir: str(tmp_path))
    monkeypatch.setattr(
        "infrastructure.image_processor.save_image_with_metadata",
        lambda image_obj, path, metadata_dict: (_ for _ in ()).throw(RuntimeError("pnginfo failed")),
    )

    await process_job(job.id)

    output_path = tmp_path / "result.png"
    sidecar_path = tmp_path / "result.png.json"
    assert output_path.exists()
    assert sidecar_path.exists()

    stored_metadata = json.loads(sidecar_path.read_text(encoding="utf-8"))
    assert stored_metadata["job_id"] == job.id
    assert stored_metadata["provider"] == "provider-1"
    assert stored_metadata["prompt"] == "hello"
    assert stored_metadata["seed"] == 42

    updated_job = await job_service.get_job(job.id)
    assert updated_job.status == JobStatus.COMPLETED

    LoadBalancer.reset_state()