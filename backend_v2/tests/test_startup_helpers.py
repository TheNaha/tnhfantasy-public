from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.lifecycle import startup_application
from api.startup_helpers import (
    autostart_provider_containers,
    build_provider_worker_images,
    cleanup_provider_state_artifacts,
)


def test_build_provider_worker_images_attempts_default_builds():
    container_manager = MagicMock()
    container_manager.build_worker_images.return_value = {
        "modal": "comfy-provider-modal:latest",
        "beam": "comfy-provider-beam:latest",
    }

    with patch("services.container_manager.get_container_manager", return_value=container_manager):
        build_provider_worker_images()

    container_manager.build_worker_images.assert_called_once_with()


def test_autostart_provider_containers_starts_enabled_containerized_providers():
    session = MagicMock()
    container_manager = MagicMock()

    provider = MagicMock()
    provider.id = "modal-primary"
    provider.type = "modal"
    provider.enabled = True
    provider.container_config = {"port": 8001}

    provider_repo = MagicMock()
    provider_repo.get_all.return_value = [provider]

    with patch("api.startup_helpers.get_session_sync", return_value=session), \
         patch("infrastructure.repositories.ProviderRepository", return_value=provider_repo), \
         patch("services.container_manager.get_container_manager", return_value=container_manager), \
         patch("infrastructure.providers.ProviderRegistry.build_container_env", return_value={"TOKEN": "abc"}):
        autostart_provider_containers()

    container_manager.start_container.assert_called_once_with(
        provider_id="modal-primary",
        provider_type="modal",
        port=8001,
        env_vars={"TOKEN": "abc"},
    )
    session.close.assert_called_once_with()


def test_cleanup_provider_state_artifacts_cleans_orphans_and_stale_downloads():
    session = MagicMock()
    provider_repo = MagicMock()
    model_repo = MagicMock()

    provider = MagicMock()
    provider.id = "modal-primary"
    provider_repo.get_all.return_value = [provider]

    model_repo.cleanup_orphaned_provider_statuses.return_value = {
        "deleted_count": 3,
        "orphaned_providers": ["deleted-provider"],
    }
    model_repo.reset_stale_downloading_statuses.return_value = 2

    with patch("api.startup_helpers.get_session_sync", return_value=session), \
         patch("infrastructure.repositories.ProviderRepository", return_value=provider_repo), \
         patch("infrastructure.repositories.model_repo_v2.ModelRepositoryV2", return_value=model_repo):
        cleanup_provider_state_artifacts(stale_downloading_after_minutes=30)

    model_repo.cleanup_orphaned_provider_statuses.assert_called_once_with(["modal-primary"])
    reset_call = model_repo.reset_stale_downloading_statuses.call_args.kwargs
    assert reset_call["provider_names"] == ["modal-primary"]
    assert isinstance(reset_call["stale_before"], datetime)
    session.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_startup_application_refreshes_provider_images_before_autostart():
    process_job = MagicMock()
    ws_manager = MagicMock()
    ws_manager.start_broadcasting = AsyncMock(return_value=None)

    events = []
    provider_monitor_task = MagicMock()
    broadcast_task = MagicMock()

    def start_background_task_side_effect(coro, task_name):
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        if task_name == "provider_monitor":
            return provider_monitor_task
        return broadcast_task

    with patch("api.lifecycle.create_db_and_tables"), \
            patch("api.lifecycle.cleanup_provider_state_artifacts", side_effect=lambda: events.append("cleanup")), \
         patch("api.lifecycle.configure_worker_pool"), \
         patch("api.lifecycle.start_scheduler"), \
         patch("api.lifecycle.schedule_preview_prefetch"), \
         patch("api.lifecycle.schedule_vacuum"), \
         patch("api.lifecycle.recover_pending_jobs", new_callable=AsyncMock) as recover_pending_jobs, \
         patch("api.lifecycle.recover_post_processing_jobs", new_callable=AsyncMock) as recover_post_processing_jobs, \
         patch("api.lifecycle.build_provider_worker_images", side_effect=lambda: events.append("build")), \
         patch("api.lifecycle.autostart_provider_containers", side_effect=lambda: events.append("autostart")), \
         patch("api.lifecycle.monitor_provider_changes", new_callable=AsyncMock), \
         patch("api.lifecycle.start_background_task", side_effect=start_background_task_side_effect), \
         patch("services.gallery_indexer.gallery_indexer.start"), \
         patch("api.lifecycle.job_queue") as job_queue:
        recover_pending_jobs.return_value = None
        recover_post_processing_jobs.return_value = None
        job_queue.start = AsyncMock()
        job_queue.set_processor = MagicMock()

        tasks = await startup_application(process_job, ws_manager)

    job_queue.set_processor.assert_called_once_with(process_job)
    job_queue.start.assert_awaited_once_with()
    assert events == ["cleanup", "build", "autostart"]
    assert tasks == {
        "provider_monitor_task": provider_monitor_task,
        "broadcast_task": broadcast_task,
    }