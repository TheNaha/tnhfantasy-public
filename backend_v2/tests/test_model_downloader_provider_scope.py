"""A model must not be tracked against providers that cannot hold it.

The downloader wrote a `pending` status row for EVERY enabled provider
before it worked out which ones could actually act on it - and the LLM and
TTS providers, which have no ComfyUI model tree, are skipped a few lines
later.

So every LLM and TTS provider accumulated a `pending` row for every image
model, forever. Those rows are in the availability badge's denominator, so
an image model on two image providers read "Partial - 2 of 4 online
providers ready", and no model ever read as fully available.
"""

import pytest
from sqlmodel import select

from core.entities import Provider


class _FakeEngine:
    """An engine that does or does not manage model files."""

    def __init__(self, manages: bool):
        if manages:
            self.manages_model_files = True
        else:
            self.manages_model_files = False
            self.supports_discovery_reconcile = False


@pytest.fixture
def downloader(session, monkeypatch):
    from services.model_downloader import ModelDownloader

    service = ModelDownloader(session)
    return service


def _provider(session, provider_id: str, **kwargs) -> Provider:
    provider = Provider(
        id=provider_id,
        name=provider_id,
        type=kwargs.get("type", "remote_comfy"),
        worker_type=kwargs.get("worker_type", "remote_comfy"),
        enabled=kwargs.get("enabled", True),
        url=kwargs.get("url", "https://example.invalid"),
    )
    session.add(provider)
    session.commit()
    return provider


def _engine_for(non_managing: set[str]):
    """The engine lookup, with the named providers not managing model files."""

    def _get_engine(pid, provider=None):
        return _FakeEngine(pid not in non_managing)

    return _get_engine


def _model(session):
    """A model with one version and one file, so a status row can attach."""
    from core.entities import ModelFile, ModelV2, ModelVersion

    model = ModelV2(name="A checkpoint", type="Checkpoint", directory="checkpoints")
    session.add(model)
    session.commit()

    version = ModelVersion(
        model_id=model.id,
        name="v1",
        base_model="SD 1.5",
        base_model_type="checkpoint",
    )
    session.add(version)
    session.commit()

    file = ModelFile(
        version_id=version.id,
        original_filename="a.safetensors",
        storage_filename="a.safetensors",
        file_type="Model",
    )
    session.add(file)
    session.commit()
    return model, file


async def _noop_reconciliation(provider_id, provider=None, engine=None, quick_sync=False):
    return {"status": "started", "message": "ok"}


class TestThePendingRows:
    @pytest.mark.asyncio
    async def test_an_llm_provider_gets_no_pending_row(
        self, session, downloader, monkeypatch
    ):
        """The LLM provider is skipped - and it must leave no trace.

        The row it used to leave was in the availability badge's
        denominator, so it made every image model look partly
        unavailable.
        """
        _provider(session, "image-provider", type="remote_comfy", worker_type="remote_comfy")
        _provider(session, "llm-provider", type="llm", worker_type="llm")
        _provider(session, "tts-provider", type="tts", worker_type="tts")

        monkeypatch.setattr(
            "services.engines.engine_factory.get_engine",
            _engine_for({"llm-provider", "tts-provider"}),
        )
        monkeypatch.setattr(
            "services.in_process_reconciliation.trigger_in_process_reconciliation",
            _noop_reconciliation,
        )

        model, file = _model(session)
        result = await downloader.trigger_download_to_providers(model_id=model.id)

        skipped = {
            entry["provider_id"]
            for entry in result["providers"]
            if entry.get("status") == "skipped"
        }
        assert "llm-provider" in skipped
        assert "tts-provider" in skipped
        assert "image-provider" not in skipped

        # And the row it used to leave is gone.
        from core.entities import ProviderVersionStatus

        rows = session.exec(
            select(ProviderVersionStatus).where(
                ProviderVersionStatus.file_id == file.id
            )
        ).all()
        by_provider = {row.provider_id: row.status for row in rows}
        assert "llm-provider" not in by_provider
        assert "tts-provider" not in by_provider
        assert by_provider.get("image-provider") == "pending"

    @pytest.mark.asyncio
    async def test_an_image_provider_is_still_tracked(
        self, session, downloader, monkeypatch
    ):
        _provider(session, "image-provider", type="remote_comfy", worker_type="remote_comfy")

        monkeypatch.setattr(
            "services.engines.engine_factory.get_engine",
            _engine_for(set()),
        )
        monkeypatch.setattr(
            "services.in_process_reconciliation.trigger_in_process_reconciliation",
            _noop_reconciliation,
        )

        model, _file = _model(session)
        result = await downloader.trigger_download_to_providers(model_id=model.id)

        skipped = {
            entry["provider_id"]
            for entry in result["providers"]
            if entry.get("status") == "skipped"
        }
        assert "image-provider" not in skipped
