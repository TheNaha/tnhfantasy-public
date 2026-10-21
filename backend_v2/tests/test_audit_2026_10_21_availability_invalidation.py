"""Changing a model's availability must change the answer immediately
(audit-2026-10-21 §3.19, §3.20).

The availability caches have a 30 s TTL, and the ONLY thing that cleared
them was a provider being enabled or disabled. So:

  * a DELETED checkpoint stayed selectable, and stayed in the generation
    path, for up to half a minute after it was gone - and the user got
    "Missing Models" from ComfyUI instead of the model simply not being
    there any more;
  * a DISABLED version stayed eligible, and an ENABLED one stayed
    ineligible;
  * and the reconciler - the path whose whole job is to make a model
    servable - wrote provider status straight to the repository, bypassing
    the one writer that invalidates. So a model the reconciler had just
    marked `ready` stayed ineligible for the TTL, on the exact path that
    exists to make it servable.

These are behavioural: the assertion is that the cache is actually
invalidated, not that a particular string is present in a file.
"""

from unittest.mock import MagicMock, patch

import pytest

from services import in_process_reconciliation, model_reconciliation, model_service


@pytest.fixture
def caches(monkeypatch):
    """A stand-in for the availability caches, and a counter."""
    from services import load_balancer as lb
    from services import load_balancer as lb
    from services import model_availability_service as mas
    from services.load_balancer import LoadBalancer

    calls: list[str] = []

    def _invalidate(provider_id=None, runtime_state=None):
        calls.append(provider_id or "*")
        mas._available_models_cache.clear()
        lb._model_availability_cache.clear()

    monkeypatch.setattr(
        LoadBalancer, "invalidate_model_availability_cache",
        staticmethod(_invalidate),
    )
    return calls


class TestInvalidationEntryPoints:
    def test_deleting_a_model_invalidates(self, caches):
        service = model_service.ModelServiceV2.__new__(model_service.ModelServiceV2)
        service.repo = MagicMock()
        service.repo.get_model.return_value = MagicMock(directory="checkpoints")
        service.repo.get_files_for_model.return_value = []
        service.repo.delete_model.return_value = True
        service.downloader = MagicMock()
        service.downloader.trigger_delete_from_providers = _async_none()

        import asyncio

        asyncio.run(service.delete_model(7))

        assert caches, "deleting a model did not invalidate the availability cache"

    def test_toggling_a_version_invalidates(self, caches):
        service = model_service.ModelServiceV2.__new__(model_service.ModelServiceV2)
        service.repo = MagicMock()
        service.repo.toggle_version_enabled.return_value = MagicMock(id=3)
        service.repo._version_to_dict.return_value = {"id": 3}

        import asyncio

        asyncio.run(service.toggle_version_enabled(3))

        assert caches, "toggling a version did not invalidate the availability cache"

    def test_a_toggle_that_found_nothing_does_not_invalidate(self, caches):
        """Nothing changed, so nothing needs invalidating."""
        service = model_service.ModelServiceV2.__new__(model_service.ModelServiceV2)
        service.repo = MagicMock()
        service.repo.toggle_version_enabled.return_value = None

        import asyncio

        asyncio.run(service.toggle_version_enabled(999))

        assert not caches

    def test_the_invalidation_clears_both_caches(self):
        """The load balancer's routing memo AND the availability service's
        own TTL cache. `LoadBalancer.invalidate_model_availability_cache` is
        the one entry point that clears both."""
        from services import load_balancer as lb
        from services import model_availability_service as mas
        from services.load_balancer import LoadBalancer

        mas._available_models_cache["checkpoints"] = (mas.time.monotonic(), ["a.safetensors"])
        lb._model_availability_cache["x"] = object()
        try:
            LoadBalancer.invalidate_model_availability_cache()
            assert "checkpoints" not in mas._available_models_cache
            assert "x" not in lb._model_availability_cache
        finally:
            mas._available_models_cache.clear()
            lb._model_availability_cache.clear()

    def test_the_service_helper_uses_that_entry_point(self, caches):
        model_service.ModelServiceV2.invalidate_availability_caches()
        assert caches


def _async_none():
    async def _none(*args, **kwargs):
        return None

    return _none


class TestReconcilerWrites:
    def test_the_in_process_reconciler_invalidates(self, caches):
        """Its status write must go through the invalidating path."""
        fake_service = MagicMock()
        fake_service.repo.update_provider_status.return_value = MagicMock(
            provider_id="p1", file_id="f1", status="ready"
        )

        in_process_reconciliation._write_provider_status(
            fake_service, file_id="f1", provider_id="p1", status="ready"
        )

        fake_service.repo.update_provider_status.assert_called_once()
        fake_service.invalidate_availability_caches.assert_called_once()

    def test_the_model_reconciler_invalidates(self):
        service = model_reconciliation.ModelReconciliationService.__new__(
            model_reconciliation.ModelReconciliationService
        )
        service.repo = MagicMock()
        service.repo.update_provider_status.return_value = MagicMock()

        with patch(
            "services.load_balancer.LoadBalancer.invalidate_model_availability_cache"
        ) as mock_invalidate:
            service._write_provider_status(file_id="f1", provider_id="p1", status="ready")

        service.repo.update_provider_status.assert_called_once()
        mock_invalidate.assert_called_once()
