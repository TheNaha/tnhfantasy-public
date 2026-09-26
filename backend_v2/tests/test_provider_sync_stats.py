"""Tests for the corrected per-provider model sync counters.

Live proof of the defect, on the running system: all five providers reported the
identical `total_models: 521`, including `llm-local` — an LLM worker with no
image models at all. `get_provider_sync_stats` counted the whole model catalog
(no provider filter) and then computed `pending` as
`global_total - this_provider's_rows`, so a provider that had never been asked
to install anything claimed the entire library was queued on it. The providers
page rendered that as "521 queued" and the sidebar derived "needs attention"
from it.

Corrected semantics, asserted here:
  * `total_models`  — files THIS provider has a ProviderVersionStatus row for
  * `stats`         — this provider's rows by status, nothing derived from a global
  * `catalog_models`— the global count, under a name that says so
  * an LLM provider  — all zeros, because it installs no image models
"""

import pytest
from sqlmodel import Session

from core.entities import (
    ModelFile,
    ModelV2,
    ModelVersion,
    Provider,
    ProviderVersionStatus,
)
from services.provider_status_service import ProviderStatusService


def _make_file(session: Session, filename: str, *, directory: str = "checkpoints") -> str:
    model = ModelV2(name=f"model-{filename}", type="Checkpoint", directory=directory)
    session.add(model)
    session.commit()
    version = ModelVersion(model_id=model.id, name="v1")
    session.add(version)
    session.commit()
    file = ModelFile(
        version_id=version.id,
        original_filename=filename,
        storage_filename=filename,
        size_kb=1024.0,
    )
    session.add(file)
    session.commit()
    return file.id


def _make_provider(session: Session, provider_id: str, *, worker_type: str | None = None) -> Provider:
    provider = Provider(
        id=provider_id,
        type="modal",
        worker_type=worker_type,
        enabled=True,
        priority=1,
        credentials={},
        config={},
    )
    session.add(provider)
    session.commit()
    return provider


def _track(session: Session, file_id: str, provider_id: str, status: str) -> None:
    session.add(ProviderVersionStatus(file_id=file_id, provider_id=provider_id, status=status))
    session.commit()


@pytest.fixture(autouse=True)
def _clear_provider_status_caches():
    from services.provider_status_service import invalidate_provider_status_caches

    invalidate_provider_status_caches()
    yield
    invalidate_provider_status_caches()


@pytest.fixture(name="status_service")
def status_service_fixture(session):
    return ProviderStatusService(session=session)


# ── the two-provider case that the live data got wrong ───────────────────────

@pytest.mark.asyncio
async def test_two_providers_with_different_tracks_report_different_numbers(
    session, status_service
):
    """The exact failure: both providers reported the same global 521."""
    file_a = _make_file(session, "alpha.safetensors")
    file_b = _make_file(session, "beta.safetensors")
    file_c = _make_file(session, "gamma.safetensors")
    _make_provider(session, "modal-a")
    _make_provider(session, "modal-b")

    # modal-a has two files ready and one queued; modal-b has one, failed.
    _track(session, file_a, "modal-a", "ready")
    _track(session, file_b, "modal-a", "ready")
    _track(session, file_c, "modal-a", "pending")
    _track(session, file_b, "modal-b", "failed")

    a = await status_service.get_provider_sync_stats("modal-a")
    b = await status_service.get_provider_sync_stats("modal-b")

    assert a["total_models"] == 3
    assert a["stats"] == {"installed": 2, "pending": 1, "downloading": 0, "failed": 0}
    assert b["total_models"] == 1
    assert b["stats"] == {"installed": 0, "pending": 0, "downloading": 0, "failed": 1}

    # The two must NOT collapse to the same number any more.
    assert a["total_models"] != b["total_models"]
    assert a["stats"] != b["stats"]


@pytest.mark.asyncio
async def test_provider_with_no_tracked_rows_reports_zero_not_the_catalog(
    session, status_service
):
    """`direct_url` claimed 521 pending while tracking nothing."""
    for name in ("one.safetensors", "two.safetensors", "three.safetensors"):
        _make_file(session, name)
    _make_provider(session, "direct_url")
    _make_provider(session, "modal-full")

    result = await status_service.get_provider_sync_stats("direct_url")

    assert result["total_models"] == 0
    assert result["stats"]["pending"] == 0
    assert result["stats"]["installed"] == 0
    assert result["has_install_intent"] is False
    # The global number is still available, but under its own name.
    assert result["catalog_models"] == 3


@pytest.mark.asyncio
async def test_llm_provider_reports_no_image_model_counts(session, status_service):
    """`llm-local` reported total_models=521, pending=521."""
    _make_file(session, "a.safetensors")
    _make_file(session, "b.safetensors")
    llm = _make_provider(session, "llm-local", worker_type="llm")
    # Even if something recorded a row for it, an LLM worker installs no images.
    _track(session, _make_file(session, "c.safetensors"), "llm-local", "pending")

    result = await status_service.get_provider_sync_stats("llm-local", provider=llm)

    assert result["total_models"] == 0
    assert result["stats"] == {"installed": 0, "pending": 0, "downloading": 0, "failed": 0}
    assert result["catalog_models"] is None
    assert result["has_install_intent"] is False
    assert result["is_image_provider"] is False


@pytest.mark.asyncio
async def test_downloading_and_failed_statuses_are_counted_per_provider(
    session, status_service
):
    f1 = _make_file(session, "d1.safetensors")
    f2 = _make_file(session, "d2.safetensors")
    f3 = _make_file(session, "d3.safetensors")
    _make_provider(session, "p-downloading")
    _track(session, f1, "p-downloading", "downloading")
    _track(session, f2, "p-downloading", "failed")
    _track(session, f3, "p-downloading", "failed")

    result = await status_service.get_provider_sync_stats("p-downloading")

    assert result["stats"] == {"installed": 0, "pending": 0, "downloading": 1, "failed": 2}


@pytest.mark.asyncio
async def test_row_detail_also_stops_reporting_untracked_files_as_pending(
    session, status_service
):
    """get_provider_sync_status had the same fabrication, at row level."""
    tracked = _make_file(session, "tracked.safetensors")
    _make_file(session, "untracked.safetensors")
    _make_provider(session, "p-one")
    _track(session, tracked, "p-one", "ready")

    result = await status_service.get_provider_sync_status("p-one")

    assert result["total_models"] == 1
    assert [m["name"] for m in result["models"]] == ["tracked.safetensors"]
    assert result["stats"] == {"installed": 1, "pending": 0, "downloading": 0, "failed": 0}


@pytest.mark.asyncio
async def test_model_sync_on_the_status_card_is_per_provider(session, status_service, monkeypatch):
    """The card is what the providers page and the sidebar actually read."""
    import services.provider_status_service as pss

    _make_file(session, "x1.safetensors")
    _make_file(session, "x2.safetensors")
    _make_provider(session, "card-provider")

    monkeypatch.setattr(
        pss, "resolve_provider_runtime_async",
        lambda _p: _async_value(type("R", (), {"worker_url": None, "mode": "local", "connected": False,
                                               "supports_setup": False, "supports_reconciliation": False})()),
    )
    monkeypatch.setattr(
        ProviderStatusService, "get_live_reconciliation_state",
        lambda self, pid, provider=None: _async_value({"status": "idle"}),
    )
    monkeypatch.setattr(
        ProviderStatusService, "get_live_deploy_state",
        lambda self, pid, provider=None: _async_value({"status": "idle"}),
    )
    monkeypatch.setattr(
        ProviderStatusService, "get_provider_storage_stats",
        lambda self, pid, provider=None, reconciliation_state=None: _async_value({"provider_id": pid, "total": 0, "by_directory": {}}),
    )
    monkeypatch.setattr(
        ProviderStatusService, "get_provider_sync_stats",
        lambda self, pid, provider=None: _async_value({
            "total_models": 0,
            "stats": {"installed": 0, "pending": 0, "downloading": 0, "failed": 0},
            "catalog_models": 2,
            "has_install_intent": False,
            "is_image_provider": True,
        }),
    )
    monkeypatch.setattr(
        ProviderStatusService, "get_provider_sync_status",
        lambda self, pid: _async_value({"total_models": 0, "stats": {}, "models": []}),
    )

    card = await status_service.build_provider_status_card("card-provider")

    assert card["model_sync"]["total_models"] == 0
    assert card["model_sync"]["stats"]["pending"] == 0
    assert card["model_sync"]["catalog_models"] == 2
    assert card["model_sync"]["has_install_intent"] is False


async def _async_value(value):
    return value
