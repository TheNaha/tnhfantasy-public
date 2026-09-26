"""Findings 17, 18, 24 and 26 — the smaller items, and the invariants that keep
them fixed.

17: `raise_for_status()` on the storage backends destroyed the upstream diagnosis.
    `provider_core/router.py`'s catch-all turns any exception into
    `failed("Internal server error", code=500)`, discarding the upstream status,
    message and httpx's own text. Beam's storage app returns `failed(..., code=404)`
    and `failed(..., code=500, retryable=True)` precisely so the worker can relay
    them. Four call sites threw that away.

18: `/object_info` was refetched in full once per MODEL_DIRECTORIES entry — 16
    times per `/provider-stats` click — because the 30s cache was a shared,
    lock-free dict, so 16 concurrent callers all missed a cold cache and all
    fetched. ComfyUI's /object_info is multi-megabyte on a production install.

24: `_collect_images_via_view_api` awaited `client.get(url)` per image in a loop, so
    an SDXL batch of 4 was 4 sequential round trips on a shared 10-connection pool.

26: `llm_worker/worker.py` started `auto_discovery_loop` but never
    `reconciliation_loop`, though it is the only engine with a `run_reconciliation`
    implementation.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from provider_core.models import MODEL_DIRECTORIES


def _http(status_code: int, payload=None):
    response = MagicMock(status_code=status_code)
    response.json.return_value = payload if payload is not None else {}
    response.text = str(payload)
    response.raise_for_status.side_effect = AssertionError(
        "raise_for_status() discards the upstream's own diagnosis"
    )
    return response


# ── 17: the upstream's answer reaches the caller ─────────────────────────────


class TestStorageUpstreamsAreAdoptedNotRaised:
    @pytest.mark.asyncio
    async def test_beam_validate_all_models_reports_a_404(self, monkeypatch):
        import image_worker.engines.beam.client as beam_client

        client = beam_client.BeamProviderClient(runtime_config={})
        http = MagicMock()
        http.post = AsyncMock(return_value=_http(404))
        monkeypatch.setattr(beam_client, "get_http_client", lambda: http)

        payload = await client.validate_all_models()
        assert payload["success"] is False
        assert payload["code"] == 404, (
            "the storage app's own code must survive; the router turns a raise into "
            "a flat 500 'Internal server error'"
        )
        assert payload["status"] == "error"

    @pytest.mark.asyncio
    async def test_beam_validate_all_models_marks_a_5xx_retryable(self, monkeypatch):
        import image_worker.engines.beam.client as beam_client

        client = beam_client.BeamProviderClient(runtime_config={})
        http = MagicMock()
        http.post = AsyncMock(return_value=_http(503))
        monkeypatch.setattr(beam_client, "get_http_client", lambda: http)

        payload = await client.validate_all_models()
        assert payload["code"] == 503
        assert payload["retryable"] is True

    @pytest.mark.asyncio
    async def test_beam_get_object_info_keeps_the_upstream_status(self, monkeypatch):
        import image_worker.engines.beam.client as beam_client
        from fastapi import HTTPException

        client = beam_client.BeamProviderClient(runtime_config={})
        http = MagicMock()
        http.get = AsyncMock(return_value=_http(401))
        monkeypatch.setattr(beam_client, "get_http_client", lambda: http)

        with pytest.raises(HTTPException) as exc:
            await client.get_object_info()
        assert exc.value.status_code == 401, (
            "a rejected Beam API key must not read as a generic 500"
        )

    @pytest.mark.asyncio
    async def test_remote_comfy_validate_all_models_reports_a_401(self, monkeypatch):
        import image_worker.engines.remote_comfy.client as rc_client

        client = rc_client.RemoteComfyProviderClient(runtime_config={})
        http = MagicMock()
        http.post = AsyncMock(return_value=_http(401))
        monkeypatch.setattr(rc_client, "get_http_client", lambda: http)

        payload = await client.validate_all_models()
        assert payload["success"] is False
        assert payload["code"] == 401
        assert payload["retryable"] is False, "4xx is never retryable"

    @pytest.mark.asyncio
    async def test_a_list_models_401_keeps_its_status_in_the_message(self, monkeypatch):
        """The reconciliation closure raises, but with the diagnosis inside it, so
        the failure lands in `reconciliation_state.errors` readably."""
        import image_worker.engines.remote_comfy.client as rc_client

        client = rc_client.RemoteComfyProviderClient(runtime_config={})
        captured = {}

        async def _capture(**kwargs):
            captured.update(kwargs)
            return {"status": "started"}

        monkeypatch.setattr(client, "_start_reconciliation_task", _capture)
        await client.run_reconciliation()

        http = MagicMock()
        http.post = AsyncMock(return_value=_http(401, {"detail": "Unauthorized"}))
        monkeypatch.setattr(rc_client, "get_http_client", lambda: http)

        with pytest.raises(RuntimeError) as exc:
            await captured["list_existing_files_fn"]()
        assert "401" in str(exc.value)
        assert "Unauthorized" in str(exc.value)


# ── 18: one fetch for sixteen callers ────────────────────────────────────────


class TestObjectInfoIsSingleFlight:
    @staticmethod
    def _client(engine: str):
        if engine == "direct_url":
            from image_worker.engines.direct_url.client import DirectUrlProviderClient

            return DirectUrlProviderClient(runtime_config={})
        from image_worker.engines.remote_comfy.client import RemoteComfyProviderClient

        return RemoteComfyProviderClient(runtime_config={})

    @staticmethod
    def _stub_slow_object_info(client):
        """A slow /object_info, so without a lock every caller overlaps the fetch."""

        async def _slow(*_args, **_kwargs):
            await asyncio.sleep(0.05)
            return MagicMock(status_code=200, json=lambda: {"CheckpointLoaderSimple": {}})

        client._http = MagicMock()
        client._http.aclose = AsyncMock()
        client._http.close = AsyncMock()
        client._http.get = AsyncMock(side_effect=_slow)
        return client

    @pytest.mark.asyncio
    async def test_direct_url_sixteen_concurrent_callers_cause_one_fetch(self):
        """The 16x fan-out, and it is `direct_url`'s.

        `get_storage_stats` (provider_core/base_client.py:38) gathers `list_models`
        over all 16 MODEL_DIRECTORIES, and `direct_url.list_models` is derived from
        ComfyUI's /object_info. ComfyUI's /object_info is multi-megabyte on a
        production install, so one /provider-stats click used to be 16 full
        downloads and 16 full JSON parses.
        """
        from provider_core.models import ListModelsRequest

        assert len(MODEL_DIRECTORIES) >= 16, "the premise of the finding changed"

        client = self._stub_slow_object_info(self._client("direct_url"))
        try:
            await asyncio.gather(*[
                client.list_models(ListModelsRequest(directory=directory))
                for directory in MODEL_DIRECTORIES
            ])
        finally:
            await client.close()

        assert client._http.get.await_count == 1, (
            f"16 concurrent list_models caused {client._http.get.await_count} full "
            "/object_info downloads and parses"
        )

    @pytest.mark.asyncio
    async def test_remote_comfy_concurrent_object_info_callers_cause_one_fetch(self):
        """`remote_comfy` is the same shape, with a narrower fan-out — stated
        accurately here rather than borrowed from direct_url's.

        `remote_comfy.list_models` goes to the AGENT, not to ComfyUI, so the 16x
        fan-out described above is `direct_url`'s alone. What is shared is the
        uncached /object_info: `get_object_info` re-fetched it on every call, and
        the description's "its own 30s cache" did not exist on this engine.
        Concurrent `/object-info` callers (the UI polls it) each paid a full
        multi-megabyte download, so the same lock is worth having here.
        """
        client = self._stub_slow_object_info(self._client("remote_comfy"))
        try:
            await asyncio.gather(*[client.get_object_info() for _ in range(8)])
        finally:
            await client.close()

        assert client._http.get.await_count == 1


class TestDirectUrlObjectInfoCache:
    @pytest.mark.asyncio
    async def test_a_second_list_models_within_the_ttl_does_not_refetch(self, monkeypatch):
        from image_worker.engines.direct_url.client import DirectUrlProviderClient
        from provider_core.models import ListModelsRequest

        client = DirectUrlProviderClient(runtime_config={})
        client._http = MagicMock()
        client._http.aclose = AsyncMock()
        response = MagicMock(status_code=200)
        response.json.return_value = {"CheckpointLoaderSimple": {}}
        client._http.get = AsyncMock(return_value=response)

        try:
            await client.list_models(ListModelsRequest(directory="checkpoints"))
            first = client._http.get.await_count
            await client.list_models(ListModelsRequest(directory="loras"))
            second = client._http.get.await_count
        finally:
            await client.close()

        assert first == 1
        assert second == 1, "the second listing should have hit the cache"

    @pytest.mark.asyncio
    async def test_a_failure_is_not_cached(self, monkeypatch):
        """A ComfyUI that is restarting must be retried, not pinned as an error for
        the whole TTL."""
        from image_worker.engines.direct_url.client import DirectUrlProviderClient
        from provider_core.models import ListModelsRequest

        client = DirectUrlProviderClient(runtime_config={})
        client._http = MagicMock()
        client._http.aclose = AsyncMock()
        client._http.get = AsyncMock(side_effect=RuntimeError("connection refused"))

        try:
            first = await client.list_models(ListModelsRequest(directory="checkpoints"))
            second = await client.list_models(ListModelsRequest(directory="checkpoints"))
        finally:
            await client.close()

        assert first["success"] is False
        assert second["success"] is False
        assert client._http.get.await_count == 2, "the error was cached"

    @pytest.mark.asyncio
    async def test_a_ttl_expiry_refetches(self, monkeypatch):
        from image_worker.engines.direct_url import client as direct_url_module
        from image_worker.engines.direct_url.client import DirectUrlProviderClient
        from provider_core.models import ListModelsRequest

        monkeypatch.setattr(direct_url_module, "OBJECT_INFO_CACHE_TTL", 0.05)
        client = DirectUrlProviderClient(runtime_config={})
        client._http = MagicMock()
        client._http.aclose = AsyncMock()
        response = MagicMock(status_code=200)
        response.json.return_value = {"CheckpointLoaderSimple": {}}
        client._http.get = AsyncMock(return_value=response)

        try:
            await client.list_models(ListModelsRequest(directory="checkpoints"))
            await asyncio.sleep(0.08)
            await client.list_models(ListModelsRequest(directory="checkpoints"))
        finally:
            await client.close()

        assert client._http.get.await_count == 2

    def test_both_engines_declare_the_ttl(self):
        import inspect

        import image_worker.engines.direct_url.client as direct_url_module
        import image_worker.engines.remote_comfy.client as rc_module

        assert "OBJECT_INFO_CACHE_TTL" in inspect.getsource(direct_url_module)
        assert "OBJECT_INFO_CACHE_TTL" in inspect.getsource(rc_module)

    def test_both_engines_hold_a_lock(self):
        import inspect

        import image_worker.engines.direct_url.client as direct_url_module
        import image_worker.engines.remote_comfy.client as rc_module

        for module in (direct_url_module, rc_module):
            source = inspect.getsource(module)
            assert "asyncio.Lock" in source, (
                "a lock-free dict cache is what 16 concurrent cold callers all miss"
            )


# ── 24: concurrent image collection ───────────────────────────────────────────


class TestImagesAreFetchedConcurrently:
    @pytest.mark.asyncio
    async def test_a_batch_of_four_is_four_overlapping_fetches(self, monkeypatch):
        """An SDXL batch of 4 was 4 sequential round trips on a pool with 10
        connections free."""
        from image_worker.comfy import workflow_executor as executor

        history = {
            "outputs": {
                "9": {"images": [{"filename": f"image_{i}.png", "type": "output"} for i in range(4)]}
            }
        }

        in_flight = {"now": 0, "peak": 0}

        async def _slow_get(url, **_kwargs):
            in_flight["now"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
            await asyncio.sleep(0.05)
            in_flight["now"] -= 1
            return MagicMock(content=b"x" * 8)

        fake_client = MagicMock()
        fake_client.get = AsyncMock(side_effect=_slow_get)
        monkeypatch.setattr(executor, "get_http_client", lambda: fake_client)

        images = await executor._collect_images_via_view_api(
            history,
            server_address="http://comfy:8188",
            view_timeout_seconds=5.0,
            logger=None,
        )

        assert len(images) == 4
        assert in_flight["peak"] == 4, (
            f"peak concurrency was {in_flight['peak']}, not 4: the fetches are serial"
        )

    @pytest.mark.asyncio
    async def test_the_order_is_preserved(self, monkeypatch):
        from image_worker.comfy import workflow_executor as executor

        history = {
            "outputs": {
                "9": {"images": [{"filename": "a.png"}, {"filename": "b.png"}, {"filename": "c.png"}]}
            }
        }

        # Reverse the arrival order, so a positional gather is the only thing that
        # can keep the output stable.
        async def _out_of_order(url, **_kwargs):
            import urllib.parse

            name = urllib.parse.unquote(url.split("filename=")[1].split("&")[0])
            await asyncio.sleep({"a.png": 0.03, "b.png": 0.02, "c.png": 0.01}[name])
            return MagicMock(content=b"x")

        fake_client = MagicMock()
        fake_client.get = AsyncMock(side_effect=_out_of_order)
        monkeypatch.setattr(executor, "get_http_client", lambda: fake_client)

        images = await executor._collect_images_via_view_api(
            history,
            server_address="http://comfy:8188",
            view_timeout_seconds=5.0,
            logger=None,
        )
        assert [image["filename"] for image in images] == ["a.png", "b.png", "c.png"]

    @pytest.mark.asyncio
    async def test_one_failure_does_not_lose_the_others(self, monkeypatch):
        from image_worker.comfy import workflow_executor as executor

        history = {"outputs": {"9": {"images": [{"filename": "ok.png"}, {"filename": "bad.png"}]}}}

        async def _selective(url, **_kwargs):
            if "bad.png" in url:
                raise RuntimeError("404")
            return MagicMock(content=b"x")

        fake_client = MagicMock()
        fake_client.get = AsyncMock(side_effect=_selective)
        monkeypatch.setattr(executor, "get_http_client", lambda: fake_client)

        images = await executor._collect_images_via_view_api(
            history,
            server_address="http://comfy:8188",
            view_timeout_seconds=5.0,
            logger=None,
        )
        assert [image["filename"] for image in images] == ["ok.png"]

    @pytest.mark.asyncio
    async def test_an_image_with_no_filename_is_still_skipped(self, monkeypatch):
        from image_worker.comfy import workflow_executor as executor

        history = {"outputs": {"9": {"images": [{"subfolder": ""}, {"filename": "ok.png"}]}}}
        fake_client = MagicMock()
        fake_client.get = AsyncMock(return_value=MagicMock(content=b"x"))
        monkeypatch.setattr(executor, "get_http_client", lambda: fake_client)

        images = await executor._collect_images_via_view_api(
            history,
            server_address="http://comfy:8188",
            view_timeout_seconds=5.0,
            logger=None,
        )
        assert [image["filename"] for image in images] == ["ok.png"]


# ── 26: the LLM worker reconciles ────────────────────────────────────────────


class TestTheLlmWorkerStartsBothLoops:
    def _source(self) -> str:
        import pathlib

        return (
            pathlib.Path(__file__).resolve().parents[1] / "llm_worker/worker.py"
        ).read_text()

    def test_it_starts_reconciliation(self):
        source = self._source()
        assert "reconciliation_loop(" in source, (
            "llm_worker/worker.py started only auto_discovery_loop; the `modal` LLM "
            "engine is the only one with a run_reconciliation implementation and "
            "nothing ever triggered it, so its volume drifted out of the database "
            "with no error anywhere"
        )
        assert "auto_discovery_loop(" in source, "the existing loop must stay"

    def test_it_retains_both_task_references(self):
        """A bare create_task is GC-eligible while it runs."""
        source = self._source()
        assert source.count("_background_tasks.append(") == 2

    def test_it_reads_the_same_reconciliation_knobs_as_the_image_worker(self):
        source = self._source()
        for knob in (
            "RECONCILIATION_INTERVAL_SECONDS",
            "RECONCILIATION_STARTUP_DELAY_SECONDS",
        ):
            assert knob in source, f"the LLM worker must read {knob}"

    def test_the_image_worker_still_starts_both(self):
        """The control: the twin that was already correct must stay correct."""
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1] / "image_worker/worker.py"
        ).read_text()
        assert "reconciliation_loop(" in source
        assert "auto_discovery_loop(" in source

    def test_reconciliation_loop_is_importable_and_callable_with_these_kwargs(self):
        import inspect

        from provider_core.background import reconciliation_loop

        signature = inspect.signature(reconciliation_loop)
        for name in ("interval_seconds", "startup_delay_seconds", "http_client"):
            assert name in signature.parameters, f"reconciliation_loop has no {name}"
