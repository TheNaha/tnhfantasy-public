import asyncio
import base64
import io
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlmodel import Session

from api.main import process_job
from core.entities import JobStatus, Provider
from services.job_processing import _classify_llm_job_type
from services.job_service import JobService
from services.load_balancer import LoadBalancer
from services.provider_client import JobTimeoutError, ProviderCallError


def _session_override(session: Session):
    def fake_get_session():
        yield session
    return fake_get_session

def _async_session_override(session: Session):
    @asynccontextmanager
    async def fake_get_session_context():
        yield session
    return fake_get_session_context


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


async def _wait_for_provider_stats(session: Session, provider_id: str, expected_assigned: int, attempts=50):
    for _ in range(attempts):
        stats = await LoadBalancer(session, strategy="priority").get_stats()
        provider_stats = {item["id"]: item for item in stats["provider_stats"]}
        if provider_stats[provider_id]["jobs_assigned"] == expected_assigned:
            return provider_stats
        await asyncio.sleep(0.05)
    
    stats = await LoadBalancer(session, strategy="priority").get_stats()
    return {item["id"]: item for item in stats["provider_stats"]}


@pytest.fixture(autouse=True)
def _stub_container_runtime(monkeypatch):
    async def fake_resolve_provider_runtime(provider):
        container_config = getattr(provider, "container_config", None) or {}
        if not container_config:
            return SimpleNamespace(
                provider_id=provider.id,
                mode="unavailable",
                connected=False,
                worker_url=None,
                status="unavailable",
                healthy=False,
            )

        return SimpleNamespace(
            provider_id=provider.id,
            mode="container_http",
            connected=True,
            worker_url=f"http://tnhcomfy-{provider.id}:8000",
            status="running",
            healthy=True,
        )

    # job_runner awaits the non-blocking resolver so the blocking Docker-socket
    # read it performs stays off the event loop.
    monkeypatch.setattr("services.job_runner.resolve_provider_runtime_async", fake_resolve_provider_runtime)


@pytest.mark.asyncio
async def test_process_job_falls_back_when_provider_missing_container_config(session: Session, sample_workflow, monkeypatch):
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1, None)
    _add_provider(session, "provider-2", 2, {"port": 8000})

    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata={})

    async def fake_call_image_provider(**kwargs):
        assert kwargs["worker_url"] == "http://tnhcomfy-provider-2:8000"
        return {"images": []}

    async def fake_resolve_provider_runtime(provider):
        if provider.id == "provider-1":
            return SimpleNamespace(
                provider_id=provider.id,
                mode="unavailable",
                connected=False,
                worker_url=None,
            )
        return SimpleNamespace(
            provider_id=provider.id,
            mode="container_http",
            connected=True,
            worker_url="http://tnhcomfy-provider-2:8000",
        )

    monkeypatch.setattr("api.main.get_session_context", _async_session_override(session))
    monkeypatch.setattr("api.main._call_image_provider", fake_call_image_provider)
    monkeypatch.setattr("services.job_runner.resolve_provider_runtime_async", fake_resolve_provider_runtime)
    monkeypatch.setattr("services.job_runner.ProviderService.get_load_balancing_config", lambda self: SimpleNamespace(strategy="priority"))

    await process_job(job.id)

    updated_job = await _get_job_from_fresh_session(session, job.id)
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.provider_id == "provider-2"

    provider_stats = await _wait_for_provider_stats(session, "provider-2", expected_assigned=0)
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

    async def fake_call_image_provider(**kwargs):
        worker_url = kwargs["worker_url"]
        if worker_url == "http://tnhcomfy-provider-1:8000":
            raise ProviderCallError("bad workflow", provider_id="provider-1", is_retryable=False)
        return {"images": []}

    monkeypatch.setattr("api.main.get_session_context", _async_session_override(session))
    monkeypatch.setattr("api.main._call_image_provider", fake_call_image_provider)
    monkeypatch.setattr("services.job_runner.ProviderService.get_load_balancing_config", lambda self: SimpleNamespace(strategy="priority"))
    monkeypatch.setattr("api.main.get_job_max_retries", lambda task_type="image": 0)

    await process_job(job.id)

    updated_job = await _get_job_from_fresh_session(session, job.id)
    assert updated_job.status == JobStatus.COMPLETED
    assert updated_job.provider_id == "provider-2"

    provider_stats = await _wait_for_provider_stats(session, "provider-2", expected_assigned=0)
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

    async def fake_call_image_provider(**kwargs):
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

    monkeypatch.setattr("api.main.get_session_context", _async_session_override(session))
    monkeypatch.setattr("api.main._call_image_provider", fake_call_image_provider)
    monkeypatch.setattr("services.job_runner.ProviderService.get_load_balancing_config", lambda self: SimpleNamespace(strategy="priority"))
    monkeypatch.setattr("api.main._process_image_background", fake_process_image_background)
    monkeypatch.setattr("services.job_processing.os.path.relpath", lambda target, base: ".")
    monkeypatch.setattr("infrastructure.image_processor.get_output_path", lambda base_dir, subdir=None, workspace="main", **kwargs: str(tmp_path))
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
    assert stored_metadata["job_created_at"] == job.created_at.isoformat()
    assert stored_metadata["job_timeline_anchor"] == job.created_at.isoformat()
    assert stored_metadata["prompt"] == "hello"
    assert stored_metadata["seed"] == 42

    updated_job = await _get_job_from_fresh_session(session, job.id)
    assert updated_job.status == JobStatus.COMPLETED

    LoadBalancer.reset_state()


@pytest.mark.asyncio
async def test_process_job_respects_cancelled_status_before_finalize(session: Session, sample_workflow, monkeypatch):
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1, {"port": 8000})

    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata={})
    job_id = job.id

    async def fake_call_image_provider(**kwargs):
        await kwargs["job_service"].update_job(
            kwargs["job_id"],
            status=JobStatus.CANCELLED,
            message="Cancelled during processing",
        )
        return {"images": []}

    monkeypatch.setattr("api.main.get_session_context", _async_session_override(session))
    monkeypatch.setattr("api.main._call_image_provider", fake_call_image_provider)
    monkeypatch.setattr("services.job_runner.ProviderService.get_load_balancing_config", lambda self: SimpleNamespace(strategy="priority"))

    await process_job(job_id)

    updated_job = await _get_job_from_fresh_session(session, job_id)
    assert updated_job.status == JobStatus.CANCELLED
    assert updated_job.completed_at is not None

    LoadBalancer.reset_state()


@pytest.mark.asyncio
async def test_process_job_timeout_signals_provider_cancel(session: Session, sample_workflow, monkeypatch):
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1, {"port": 8000})

    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata={})

    async def fake_call_image_provider(**kwargs):
        raise JobTimeoutError("timed out")

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=SimpleNamespace(status_code=200))

    monkeypatch.setattr("api.main.get_session_context", _async_session_override(session))
    monkeypatch.setattr("api.main._call_image_provider", fake_call_image_provider)
    monkeypatch.setattr("api.main.get_job_max_retries", lambda task_type="image": 0)
    monkeypatch.setattr("services.job_runner.get_http_client", lambda: mock_http_client)
    monkeypatch.setattr("services.job_runner.ProviderService.get_load_balancing_config", lambda self: SimpleNamespace(strategy="priority"))

    await process_job(job.id)

    assert mock_http_client.post.await_count >= 1
    cancel_call = mock_http_client.post.await_args_list[0]
    assert cancel_call.args[0].endswith("/cancel-job")
    assert cancel_call.kwargs["json"]["job_id"] == job.id

    updated_job = await _get_job_from_fresh_session(session, job.id)
    assert updated_job.status == JobStatus.FAILED

    LoadBalancer.reset_state()


@pytest.mark.asyncio
async def test_process_job_persists_base64_image_to_workspace_partition(session: Session, sample_workflow, monkeypatch, tmp_path):
    """Base64 worker artifacts must be written to disk in the workspace-partitioned
    directory (job.metadata_.workspace), not flat 'main' — chat/story images
    would otherwise land in default_user/main."""
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1, {"port": 8000})

    metadata = {"prompt": "hello", "seed": 42, "workspace": "chat"}
    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata=metadata)

    image = Image.new("RGB", (8, 8), color=(0, 255, 0))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")

    async def fake_call_image_provider(**kwargs):
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

    monkeypatch.setattr("api.main.get_session_context", _async_session_override(session))
    monkeypatch.setattr("api.main._call_image_provider", fake_call_image_provider)
    monkeypatch.setattr("services.job_runner.ProviderService.get_load_balancing_config", lambda self: SimpleNamespace(strategy="priority"))
    monkeypatch.setattr("api.main._process_image_background", fake_process_image_background)
    monkeypatch.setattr("services.job_processing.os.path.relpath", lambda target, base: str(tmp_path))
    monkeypatch.setattr(
        "infrastructure.image_processor.get_output_path",
        lambda base_dir, subdir=None, workspace="main", **kwargs: (lambda p: (p.mkdir(parents=True, exist_ok=True), str(p))[1])(
            tmp_path / (workspace or "main")
        ),
    )

    await process_job(job.id)

    output_path = tmp_path / "chat" / "result.png"
    assert output_path.exists(), f"image must be written under the workspace partition: {output_path}"

    updated_job = await _get_job_from_fresh_session(session, job.id)
    assert updated_job.status == JobStatus.COMPLETED

    LoadBalancer.reset_state()


@pytest.mark.asyncio
async def test_process_job_timeout_signals_external_worker_cancel(session: Session, sample_workflow, monkeypatch):
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1, {"port": 8000})

    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata={})

    async def fake_dispatch_job_to_worker(provider_id, job_data, timeout):
        del provider_id, job_data, timeout
        raise JobTimeoutError("timed out")

    request_cancel = AsyncMock(return_value=True)

    monkeypatch.setattr("api.main.get_session_context", _async_session_override(session))
    monkeypatch.setattr("api.main.get_job_max_retries", lambda task_type="image": 0)
    monkeypatch.setattr("infrastructure.worker_registry.dispatch_job_to_worker", fake_dispatch_job_to_worker)
    monkeypatch.setattr("infrastructure.worker_registry.request_worker_job_cancel", request_cancel)
    async def fake_resolve_provider_runtime_external(provider):
        del provider
        return SimpleNamespace(mode="external_worker", connected=True, worker_url=None)

    monkeypatch.setattr(
        "services.job_runner.resolve_provider_runtime_async",
        fake_resolve_provider_runtime_external,
    )
    monkeypatch.setattr("services.job_runner.ProviderService.get_load_balancing_config", lambda self: SimpleNamespace(strategy="priority"))

    await process_job(job.id)

    request_cancel.assert_awaited_once_with("provider-1", job.id)
    updated_job = await _get_job_from_fresh_session(session, job.id)
    assert updated_job.status == JobStatus.FAILED

    LoadBalancer.reset_state()


@pytest.mark.asyncio
async def test_process_job_fails_after_all_providers_exhausted(session: Session, sample_workflow, monkeypatch):
    LoadBalancer.reset_state()
    _add_provider(session, "provider-1", 1, {"port": 8000})
    _add_provider(session, "provider-2", 2, {"port": 8000})

    job_service = JobService(session)
    job = await job_service.create_job(workflow=sample_workflow, metadata={})
    call_attempts = []

    async def fake_call_image_provider(**kwargs):
        provider_id = kwargs["provider_id"]
        call_attempts.append(provider_id)
        raise ProviderCallError(f"{provider_id} hard failure", provider_id=provider_id, is_retryable=False)

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=SimpleNamespace(status_code=200))

    monkeypatch.setattr("api.main.get_session_context", _async_session_override(session))
    monkeypatch.setattr("api.main._call_image_provider", fake_call_image_provider)
    monkeypatch.setattr("api.main.get_job_max_retries", lambda task_type="image": 0)
    monkeypatch.setattr("services.job_runner.get_http_client", lambda: mock_http_client)
    monkeypatch.setattr("services.job_runner.ProviderService.get_load_balancing_config", lambda self: SimpleNamespace(strategy="priority"))

    await process_job(job.id)

    assert call_attempts == ["provider-1", "provider-2"]
    updated_job = await _get_job_from_fresh_session(session, job.id)
    assert updated_job.status == JobStatus.FAILED
    assert updated_job.error is not None
    assert "All providers failed" in updated_job.error
    assert "provider-1" in updated_job.error
    assert "provider-2" in updated_job.error

    stats = await LoadBalancer(session, strategy="priority").get_stats()
    provider_stats = {item["id"]: item for item in stats["provider_stats"]}
    assert provider_stats["provider-1"]["failures"] >= 1
    assert provider_stats["provider-2"]["failures"] >= 1

    LoadBalancer.reset_state()


@pytest.mark.asyncio
async def test_finalize_tolerates_deleted_chat(session: Session, monkeypatch):
    """A job whose chat was deleted mid-generation must still complete and emit
    JOB_COMPLETED instead of crashing on the FK violation (b10/b11 regression)."""
    from sqlalchemy import event as sa_event
    from sqlmodel import SQLModel, create_engine
    from sqlmodel.pool import StaticPool

    from services.job_processing import finalize_successful_job

    fk_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @sa_event.listens_for(fk_engine, "connect")
    def _enable_fk(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    SQLModel.metadata.create_all(fk_engine)
    monkeypatch.setattr("infrastructure.database.engine", fk_engine)

    job_service = JobService(session)
    job = await job_service.create_job(
        workflow={"messages": [{"role": "user", "content": "hi"}], "type": "chat_reply"},
        metadata={"chat_id": "00000000-0000-0000-0000-000000000000"},
        task_type="llm",
    )

    emitted = []

    async def fake_emit(event_type, data=None, **_kwargs):
        emitted.append((event_type, data))

    # Completion events are now emitted from job_service.update_job (single,
    # enriched JOB_COMPLETED carrying the chat routing fields).
    monkeypatch.setattr("services.job_service.emit_job_event", fake_emit)

    await job_service.update_job(job.id, status=JobStatus.SENT_TO_PROVIDER)

    await finalize_successful_job(
        job=job,
        job_id=job.id,
        job_service=job_service,
        load_balancer=SimpleNamespace(
            report_success=AsyncMock(),
            release_job=AsyncMock(),
        ),
        provider_id="provider-1",
        final_result={
            "type": "chat_reply",
            "outputs": [{"role": "assistant", "content": "hello there"}],
        },
        process_image_background_fn=AsyncMock(),
    )

    # Completion is scheduled in a background task — give the loop a chance to run it.
    for _ in range(100):
        if any(e[0].value == "job.completed" for e in emitted):
            break
        await asyncio.sleep(0.05)

    completed = [e for e in emitted if e[0].value == "job.completed"]
    assert completed, "JOB_COMPLETED must still be emitted when the chat was deleted"
    assert completed[0][1].get("type") == "chat_reply"
    assert completed[0][1].get("chat_id") == "00000000-0000-0000-0000-000000000000"


@pytest.mark.asyncio
async def test_finalize_successful_job_routes_by_task_type(session: Session, monkeypatch):
    """finalize_successful_job must dispatch on job.task_type (issue #4) so that an
    LLM job is never normalized through the image/text-file path."""
    from services.job_processing import finalize_successful_job

    llm_calls = []
    image_calls = []

    async def fake_finalize_llm(**kwargs):
        llm_calls.append(kwargs)

    async def fake_finalize_image(**kwargs):
        image_calls.append(kwargs)

    # LLM assistant text stays in memory — it must never be written to a
    # text file on disk or reach the image-file path.
    def _forbid_text_file(job, text, provider_id):
        raise AssertionError("LLM text must not be written to a text file")

    monkeypatch.setattr("services.job_processing._finalize_llm_job", fake_finalize_llm)
    monkeypatch.setattr("services.job_processing._finalize_image_job", fake_finalize_image)

    job_service = JobService(session)
    lb = SimpleNamespace(report_success=AsyncMock(), release_job=AsyncMock())

    # --- LLM job ---
    llm_job = await job_service.create_job(
        workflow={"messages": [{"role": "user", "content": "hi"}], "type": "chat_reply"},
        metadata={"chat_id": "00000000-0000-0000-0000-000000000000"},
        task_type="llm",
    )
    await finalize_successful_job(
        job=llm_job,
        job_id=llm_job.id,
        job_service=job_service,
        load_balancer=lb,
        provider_id="provider-1",
        final_result={"type": "chat_reply", "outputs": [{"role": "assistant", "content": "hello"}]},
        process_image_background_fn=AsyncMock(),
    )
    assert len(llm_calls) == 1, "_finalize_llm_job should be called once for an LLM job"
    assert len(image_calls) == 0, "LLM job must not reach _finalize_image_job"
    assert llm_calls[0]["outputs"] == [{"role": "assistant", "content": "hello"}]

    # --- image job (outputs passthrough, no disk write via build_job_outputs) ---
    image_calls.clear()
    img_job = await job_service.create_job(workflow={"3": {"class_id": "node"}}, metadata={}, task_type="image")
    await finalize_successful_job(
        job=img_job,
        job_id=img_job.id,
        job_service=job_service,
        load_balancer=lb,
        provider_id="provider-1",
        final_result={"outputs": [{"type": "image", "filename": "r.png", "relative_path": "r.png", "path": "/tmp/r.png"}]},
        process_image_background_fn=AsyncMock(),
    )
    assert len(image_calls) == 1, "image job must reach _finalize_image_job"
    assert len(llm_calls) == 1, "image job must not reach _finalize_llm_job"


# ── _classify_llm_job_type ──────────────────────────────────────────────────

def _llm_job(workflow=None, metadata=None):
    return SimpleNamespace(workflow=workflow or {}, metadata_=metadata or {})


def test_classify_impersonation_by_flag():
    job = _llm_job(metadata={"type": "impersonate", "source": "impersonation", "is_impersonation": True})
    assert _classify_llm_job_type(job, {}) == "impersonation"


def test_classify_impersonation_by_source():
    """Route builds type_='impersonate'/source='impersonation' — the source alone must classify."""
    job = _llm_job(workflow={"type": "impersonate"}, metadata={"type": "impersonate", "source": "impersonation"})
    assert _classify_llm_job_type(job, {"type": "text"}) == "impersonation"


def test_classify_chat_reply_default():
    job = _llm_job(workflow={"type": "chat_reply"}, metadata={"type": "chat_reply", "source": "chat"})
    assert _classify_llm_job_type(job, {"type": "text"}) == "chat_reply"


def test_classify_narrator_from_result():
    job = _llm_job(workflow={"type": "narrator"}, metadata={"source": "narrator"})
    assert _classify_llm_job_type(job, {"type": "narrator"}) == "narrator"


def test_classify_story_illustrate_prompt():
    job = _llm_job(metadata={"source": "story_illustrate_prompt"})
    assert _classify_llm_job_type(job, {}) == "story_illustrate_prompt"


def test_classify_suggest_reply():
    job = _llm_job(workflow={"type": "suggest_reply"}, metadata={"type": "suggest_reply"})
    assert _classify_llm_job_type(job, {}) == "suggest_reply"
