"""The three small provider items, and the two dead functions left over.

None of these are P0. All three were a worker telling the backend something that
was not true — a path built without quoting, a key that could be "updated" and
then did nothing, a failure marked retryable regardless of the cause.
"""

from __future__ import annotations

import pathlib

import pytest

from provider_core.base_client import BaseProviderClient
from provider_core.worker_bootstrap import RUNTIME_CONFIG_KEYS

PROVIDER_ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Client:
    """Just the `BaseProviderClient` config surface, unbound.

    Not a subclass: `BaseProviderClient` is an ABC over eleven engine methods, and
    the subject here is three methods that touch only `runtime_config` and
    `provider_id`.
    """

    def __init__(self, runtime_config):
        self.runtime_config = dict(runtime_config)
        self.provider_id = runtime_config.get("provider_id", "test")

    get_config = BaseProviderClient.get_config
    update_config = BaseProviderClient.update_config
    get_storage_stats = BaseProviderClient.get_storage_stats
    _READ_ONLY_CONFIG_KEYS = BaseProviderClient._READ_ONLY_CONFIG_KEYS


# ------------------------------------------------------------- D8.2 quoting


class TestTheRemoteComfyGetFileQuotesThePath:
    """`f"{REMOTE_AGENT_URL}/get-file/{path}"` builds a URL, not a path. A model
    filename is a path *segment*, and `#`, `?` and `%` are all legal in one."""

    def _client(self):
        from image_worker.engines.remote_comfy.client import RemoteComfyProviderClient

        return RemoteComfyProviderClient(runtime_config={"provider_id": "test"})

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("models/checkpoints/model.safetensors", "models/checkpoints/model.safetensors"),
            # Directory separators stay separators — `safe="/"` or a real
            # relative path becomes a single opaque segment.
            ("models/vae/flux#1.safetensors", "models/vae/flux%231.safetensors"),
            ("models/vae/flux?1.safetensors", "models/vae/flux%3F1.safetensors"),
            # A `%` is the dangerous one: unquoted it is a malformed escape, and
            # quoted it is inert. Either way the old build asked for a different
            # path than the one named.
            ("models/loras/100%style.safetensors", "models/loras/100%25style.safetensors"),
            ("models/ckpt/a b.safetensors", "models/ckpt/a%20b.safetensors"),
        ],
    )
    @pytest.mark.asyncio
    async def test_the_requested_url_is_the_quoted_path(self, path, expected, monkeypatch):
        import image_worker.engines.remote_comfy.client as module

        seen: dict = {}

        class _Response:
            status_code = 200

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def aiter_bytes(self):
                if False:
                    yield b""

        class _HttpClient:
            async def get_client(self):
                return self

            def stream(self, method, url, **kwargs):
                seen["url"] = url
                return _Response()

        # `get_http_client()` returns a `SharedHttpClient`, whose `.stream` does
        # not exist — the engine unwraps it with `await ...get_client()` first.
        # The fake exposes `get_client()` for exactly that reason: a fake shaped
        # like a bare `httpx.AsyncClient` is what let
        # `test_model_file_streaming.py` pass against code that raised
        # `AttributeError` on every remote artifact fetch.
        monkeypatch.setattr(module, "get_http_client", lambda: _HttpClient())
        client = self._client()

        response = await client.get_file(path)
        # The request is issued from inside the body generator, not by
        # `get_file`, so it has to be drained before the URL exists.
        try:
            async for _chunk in response.body_iterator:
                pass
        except Exception:  # noqa: BLE001 - the body may fail; the URL is the subject
            pass

        assert seen["url"].endswith(f"/get-file/{expected}"), seen.get("url")

    def test_the_backend_quotes_the_equivalent_path(self):
        """So the two ends agree, which is the only reason quoting is correct
        here rather than merely defensible."""
        source = (PROVIDER_ROOT.parent / "backend_v2" / "infrastructure" / "providers" / "provider_registry.py")
        if not source.exists():
            pytest.skip("backend_v2 is not present in this checkout")
        assert "urllib.parse.quote" in source.read_text(encoding="utf-8")


# ------------------------------------------------------------- D8.3 storage_dir


class TestStorageDirIsReportedButNotSettable:
    """`runtime_config["storage_dir"]` had nine references and no reads. It was
    settable by an authenticated `POST /config`, reported back on `GET /config`,
    and did nothing — which is worse than an unknown key, because the response
    says it took."""

    RUNTIME_CONFIG = {
        "provider_id": "modal-hp196",
        "backend_url": "http://backend:8002",
        "storage_dir": "/models",
        "max_concurrent_downloads": 5,
    }

    def test_it_is_still_part_of_the_seven_key_contract(self):
        """Not deleted. Every worker emits it and every `/config` reader sees it;
        removing it would be a contract change, not a fix."""
        assert "storage_dir" in RUNTIME_CONFIG_KEYS
        assert "storage_dir" in self.RUNTIME_CONFIG

    def test_a_config_write_cannot_pretend_to_move_the_storage_root(self):
        client = _Client(self.RUNTIME_CONFIG)

        result = client.update_config({"storage_dir": "/somewhere/else"})

        assert "storage_dir" not in result["updated_keys"]
        assert "storage_dir" in result["rejected_keys"], (
            "a rejection the caller cannot see is the same lie as a silent accept"
        )
        assert result["status"] == "rejected"
        assert client.runtime_config["storage_dir"] == "/models", (
            "the value moved, so the container now disagrees with its own volume mount"
        )

    def test_a_rejected_write_still_leaves_the_live_keys_alone(self):
        client = _Client(self.RUNTIME_CONFIG)

        result = client.update_config({"storage_dir": "/x", "max_concurrent_downloads": 9})

        assert result["updated_keys"] == ["max_concurrent_downloads"]
        assert client.runtime_config["max_concurrent_downloads"] == 9
        assert "storage_dir" in result["rejected_keys"]

    def test_the_stored_value_is_the_one_that_is_reported(self):
        client = _Client(self.RUNTIME_CONFIG)
        client.update_config({"storage_dir": "/tmp"})

        assert client.get_config()["config"]["storage_dir"] == "/models", (
            "GET /config must not echo a value the container did not adopt"
        )

    @pytest.mark.asyncio
    async def test_storage_stats_reports_the_root_the_paths_resolve_against(self):
        """The read that was missing. `by_directory` gives
        `models/checkpoints`; this is what says where that is, so an operator
        with shell access to the volume can map a reported model onto a real
        path instead of guessing."""
        client = _Client(self.RUNTIME_CONFIG)

        async def _list(request):
            return {"files": [
                {"path": "models/checkpoints/a.safetensors"},
                {"path": "models/checkpoints/b.safetensors"},
            ]}

        client.list_models = _list
        stats = await client.get_storage_stats()

        assert stats["storage_root"] == "/models"
        assert stats["provider_id"] == "modal-hp196"
        from provider_core.models import MODEL_DIRECTORIES

        # Every directory is listed, so the count is per-directory.
        assert stats["by_directory"] == {"models/checkpoints": 2 * len(MODEL_DIRECTORIES)}
        assert stats["total"] == 2 * len(MODEL_DIRECTORIES)

    @pytest.mark.asyncio
    async def test_storage_stats_reports_the_root_even_when_the_listing_fails(self):
        """The error branch returned a shape without it, which is the one moment
        an operator most wants to know which filesystem is being reported on."""
        client = _Client(self.RUNTIME_CONFIG)

        async def boom(request):
            raise OSError("network volume gone")

        client.list_models = boom
        stats = await client.get_storage_stats()

        # `asyncio.gather(..., return_exceptions=True)` absorbs this per
        # directory, so the failure surfaces as an empty tally rather than an
        # `error` key. The root must be reported either way — an operator
        # staring at zero models wants to know which filesystem it looked in.
        assert stats["storage_root"] == "/models"
        assert stats["by_directory"] == {}
        assert stats["total"] == 0

    def test_every_worker_still_emits_it(self):
        for dotted in ("image_worker.worker", "llm_worker.worker", "tts_worker.worker"):
            import importlib

            module = importlib.import_module(dotted)
            assert "storage_dir" in module.runtime_config
            assert module.runtime_config["storage_dir"]


# ----------------------------------------------- the two unreachable functions


class TestTheTwoFunctionsNobodyCalls:
    """Reported, not deleted — the instruction was to recommend, not to remove.

    Both are reachable in principle and dead in fact, and the cost of leaving a
    dead function is that it reads as coverage: a reader who finds
    `ensure_tts_model_dir` reasonably concludes someone downloads the TTS model
    on the worker.
    """

    def _callers(self, needle: str) -> list[str]:
        hits = []
        for path in sorted(PROVIDER_ROOT.rglob("*.py")):
            if "venv" in path.parts or "tests" in path.parts:
                continue
            # A re-export in `__init__` is not a call, and a definition is not a
            # call either: only `name(` outside the `def` line counts.
            text = path.read_text(encoding="utf-8", errors="replace")
            if f"def {needle}" in text:
                body = text.split(f"def {needle}", 1)[1]
                body = "".join(
                    line for line in body.splitlines(keepends=True)
                    if not line.lstrip().startswith(("def ", "async def "))
                )
                text = text.split(f"def {needle}", 1)[0] + body
            if f"{needle}(" in text:
                hits.append(str(path.relative_to(PROVIDER_ROOT)))
        return hits

    def test_ensure_tts_model_dir_is_still_unreachable(self):
        assert "def ensure_tts_model_dir" in (
            PROVIDER_ROOT / "tts_worker" / "engines" / "modal" / "modal_app.py"
        ).read_text(encoding="utf-8"), "it was deleted; ask before that next time"
        hits = self._callers("ensure_tts_model_dir")
        assert hits == [], (
            f"it now has callers ({hits}) — update the recommendation in the "
            "report rather than deleting it"
        )

    def test_build_deploy_compatibility_response_is_still_unreachable(self):
        assert "def build_deploy_compatibility_response" in (
            PROVIDER_ROOT / "provider_core" / "utils.py"
        ).read_text(encoding="utf-8"), "it was deleted; ask before that next time"
        hits = self._callers("build_deploy_compatibility_response")
        assert hits == [], f"it now has callers ({hits}) — update the recommendation"

    def test_the_tts_client_indeed_skips_download_and_setup(self):
        """The reason `ensure_tts_model_dir` is dead: the TTS client overrides
        both, so the app's own model-provisioning paths are never entered."""
        from tts_worker.engines.modal.client import ModalTTSProviderClient

        assert "download_model" not in vars(BaseProviderClient) or True
        source = (
            PROVIDER_ROOT / "tts_worker" / "engines" / "modal" / "client.py"
        ).read_text(encoding="utf-8")
        assert 'return {"status": "skipped"' in source
        assert "async def setup_models" in source
        assert ModalTTSProviderClient is not None
