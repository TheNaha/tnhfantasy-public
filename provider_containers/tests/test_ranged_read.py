"""Item 12: the Modal ranged read had no deadline and could not be cancelled.

`get_file` on both Modal clients is a loop of `read_file_range` RPCs against a
container somewhere else. Modal's client retries a dropped connection, so a
storage container that never comes back reads as a stream that never ends — and
because neither client defined `close()`, the worker lifespan teardown
(`hasattr(client, "close")`) found nothing to cancel it with. The image twin's
loop is ~875 RPCs for a 7 GB checkpoint; the LLM twin's was 14,336 at 512 KiB per
slice.
"""

from __future__ import annotations

import asyncio
import textwrap

import pytest

from provider_core.ranged_read import RangedReader, cancel_ranged_reads


def _reader(path_data: bytes, *, range_bytes: int, timeout: float = 30.0, registry=None):
    async def read_size(_path):
        return len(path_data)

    async def read_range(_path, offset, length):
        return path_data[offset:offset + length]

    return RangedReader(
        read_size=read_size,
        read_range=read_range,
        path="models/checkpoints/big.safetensors",
        range_bytes=range_bytes,
        timeout_seconds=timeout,
        registry=registry,
    )


async def _drain(reader):
    return b"".join([chunk async for chunk in reader.stream()])


class TestTheReadCompletes:
    @pytest.mark.asyncio
    async def test_every_byte_arrives_exactly_once(self):
        data = bytes(range(256)) * 40  # 10_240 bytes
        out = await _drain(_reader(data, range_bytes=1024))
        assert out == data

    @pytest.mark.asyncio
    async def test_a_short_final_read_stops_the_loop(self):
        """An empty result is end-of-file: a short file between calls, or a
        concurrent delete. Hanging instead would be worse than stopping."""
        calls = []

        async def read_size(_path):
            return 10_000  # more than actually exists

        async def read_range(_path, offset, length):
            calls.append(offset)
            if offset >= 2048:
                return b""
            return b"x" * min(length, 2048)

        reader = RangedReader(
            read_size=read_size,
            read_range=read_range,
            path="x",
            range_bytes=1024,
            timeout_seconds=30.0,
        )
        out = await _drain(reader)
        assert out == b"x" * 2048
        assert calls[-1] >= 2048, "the loop must actually observe the empty read"


class TestTheReadIsBounded:
    @pytest.mark.asyncio
    async def test_a_peer_that_never_answers_raises_instead_of_hanging(self):
        stalled = asyncio.Event()

        async def read_size(_path):
            return 1 << 30

        async def read_range(_path, offset, length):
            await stalled.wait()  # a container that stopped answering
            return b""

        reader = RangedReader(
            read_size=read_size,
            read_range=read_range,
            path="models/checkpoints/big.safetensors",
            range_bytes=8 * 1024 * 1024,
            timeout_seconds=0.05,
        )

        with pytest.raises(TimeoutError) as exc:
            await asyncio.wait_for(_drain(reader), timeout=5)
        assert "big.safetensors" in str(exc.value)
        assert "0.05" in str(exc.value)
        stalled.set()

    @pytest.mark.asyncio
    async def test_the_deadline_covers_the_transfer_not_the_consumer(self):
        """A caller reading the body slowly must not trip the transfer deadline —
        that would fail a healthy 7 GB download because the client is on a slow
        link."""
        reader = _reader(b"y" * 4096, range_bytes=1024, timeout=5.0)
        seen = 0
        async for _chunk in reader.stream():
            await asyncio.sleep(0.02)
            seen += 1
        assert seen == 4

    @pytest.mark.asyncio
    async def test_a_missing_file_surfaces_to_the_caller(self):
        async def read_size(_path):
            raise FileNotFoundError("nope")

        reader = RangedReader(
            read_size=read_size,
            read_range=lambda *_a: asyncio.sleep(0),
            path="gone.safetensors",
            range_bytes=1024,
            timeout_seconds=5.0,
        )
        with pytest.raises(FileNotFoundError):
            await _drain(reader)


class TestTheReadIsCancellable:
    @pytest.mark.asyncio
    async def test_close_stops_an_in_flight_read(self):
        """The regression: teardown's `hasattr(client, "close")` found nothing,
        so a stuck read was waited out rather than cancelled."""
        registry: set = set()
        release = asyncio.Event()

        async def read_size(_path):
            return 1 << 30

        async def read_range(_path, offset, length):
            await release.wait()
            return b""

        reader = RangedReader(
            read_size=read_size,
            read_range=read_range,
            path="big.safetensors",
            range_bytes=8 * 1024 * 1024,
            timeout_seconds=3600,
            registry=registry,
        )

        consuming = asyncio.create_task(_drain(reader))
        await asyncio.sleep(0.05)
        assert registry, "the in-flight read must be registered so close() can find it"

        await cancel_ranged_reads(registry)
        assert not registry

        with pytest.raises(asyncio.CancelledError):
            await consuming
        release.set()

    @pytest.mark.asyncio
    async def test_cancel_is_idempotent_and_survives_an_empty_registry(self):
        registry: set = set()
        await cancel_ranged_reads(registry)
        task = asyncio.create_task(asyncio.sleep(10))
        registry.add(task)
        await cancel_ranged_reads(registry)
        await cancel_ranged_reads(registry)
        assert task.cancelled()


class TestBothModalClientsAreWiredToIt:
    @pytest.mark.parametrize(
        "module", ["image_worker.engines.modal.client", "llm_worker.engines.modal.client"]
    )
    def test_the_client_uses_the_shared_reader_and_defines_close(self, module):
        import importlib
        import inspect

        client_module = importlib.import_module(module)
        # The class *defined* in this module, not the BaseProviderClient it
        # imports — that one is in vars() too and has no `close`.
        client_cls = next(
            obj
            for obj in vars(client_module).values()
            if inspect.isclass(obj)
            and obj.__module__ == module
            and issubclass(obj, client_module.BaseProviderClient)
        )
        assert hasattr(client_cls, "close"), (
            "the worker lifespan teardown looks for close() and found nothing"
        )
        source = inspect.getsource(client_module)
        assert "RangedReader" in source
        assert "timeout_seconds=MODAL_GET_FILE_TIMEOUT_SECONDS" in source, (
            "the seconds value must be the configurable one, not a literal"
        )
        # The deadline belongs to the shared reader; a second copy of the loop in
        # the client is the thing this replaced. Scoped to `get_file` on the AST,
        # because `inference()` legitimately keeps its own `asyncio.timeout` and
        # the docstrings mention the name.
        import ast

        tree = ast.parse(textwrap.dedent(inspect.getsource(client_module)))
        get_file = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_file"
        )
        assert not any(
            isinstance(node, ast.Attribute) and node.attr == "timeout"
            for node in ast.walk(get_file)
        ), "a per-client deadline is a second loop, not a fixed one"
        assert not any(
            isinstance(node, ast.While) for node in ast.walk(get_file)
        ), "the ranged loop belongs to provider_core.ranged_read, not to each client"
        assert not any(
            isinstance(node, ast.Await)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "aio"
            for node in ast.walk(get_file)
        ), "the client must hand the RPCs to RangedReader, not await them itself"

    def test_the_llm_slice_is_four_mebibytes(self):
        import llm_worker.engines.modal.client as llm_client

        assert llm_client._MODAL_RANGE_BYTES == 4 * 1024 * 1024, (
            "512 KiB was 14,336 RPCs for a 7 GB model"
        )
        assert llm_client._MODAL_RANGE_BYTES >= 4 * 1024 * 1024
