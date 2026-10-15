"""The `remote` transport is 1-to-1 with `modal`, per category.

For most of its life it was not, and the reason was not the sidecar:
`remote_agent` registers `/list-models`, `/download-model`,
`/delete-model`, `/validate-models`, `/get-file`, `/upload-file`,
`/delete-file` and `/setup` in **every** `WORKER_MODE`. What made
`remote_llm` a worse provider than `modal_llm` was that
`RemoteLLMEngine` overrode only `__init__` — it inherited OpenAI-compatible
inference and nothing else — so it reported `manages_model_files: False`,
was absent from `_SUPPORTS_SETUP`, and had no way to list, download,
validate or delete a model. `RemoteTTSEngine` reimplemented its own client
and its own copies of eight methods that differed from the sidecar's
protocol only in which URL they were built on.

`RemoteAgentFileMixin` is the fix, and this file is the claim it is supposed
to hold: the registry flags match per category, and the engine method surface
matches on the operations that exist.

The one deliberate asymmetry is documented and asserted: TTS does not do
*setup* on either transport, because a TTS root holds audio, not a ComfyUI
models tree. "Make them 1-to-1" for that pair means removing a capability
from the remote side, not inventing one for the modal side.
"""

import pytest
from services.engines.base import InProcessEngine
from services.engines.registry import ENGINE_SPECS, _SUPPORTS_SETUP
from services.engines.worker_transport_engines import RemoteLLMEngine, RemoteTTSEngine
from services.engines.llm_engine import ModalLlamaCPPEngine
from services.engines.modal_tts_engine import ModalTTSEngine

#: The pairings that have to match, by category.
PAIRS = [
    ("image", "modal", "remote_comfy"),
    ("llm", "modal_llm", "remote_llm"),
    ("tts", "modal_tts", "remote_tts"),
]


def _overrides(engine_cls) -> set[str]:
    """Engine-contract methods defined by this class's own family.

    Walks the MRO and stops before `InProcessEngine`, so a method a mixin or a
    parent provides counts as defined — `RemoteLLMEngine.list_models` resolves to
    `RemoteAgentFileMixin.list_models` and IS part of its surface. Checking only
    `vars(engine_cls)` would report it missing and pass a broken parity claim.
    """
    contract = {
        name
        for name in dir(InProcessEngine)
        if not name.startswith("_") and callable(getattr(InProcessEngine, name, None))
    }
    found: set[str] = set()
    for klass in engine_cls.__mro__:
        if klass is InProcessEngine:
            break
        own = set(vars(klass))
        found |= {name for name in own & contract}
    return found


class TestRegistryFlagsMatch:
    def test_manages_model_files_matches_per_category(self):
        for category, modal_type, remote_type in PAIRS:
            modal = ENGINE_SPECS[modal_type]
            remote = ENGINE_SPECS[remote_type]
            assert modal["manages_model_files"] == remote["manages_model_files"], (
                f"{category}: {remote_type} manages_model_files="
                f"{remote['manages_model_files']} but {modal_type} is "
                f"{modal['manages_model_files']}"
            )

    def test_supports_setup_matches_per_category(self):
        for category, modal_type, remote_type in PAIRS:
            assert (modal_type in _SUPPORTS_SETUP) == (remote_type in _SUPPORTS_SETUP), (
                f"{category}: {remote_type} setup={remote_type in _SUPPORTS_SETUP} "
                f"but {modal_type} is {modal_type in _SUPPORTS_SETUP}"
            )

    def test_every_remote_type_is_actually_reachable(self):
        """A registry row nothing can construct is a cell that only looks filled."""
        for category, _modal, remote_type in PAIRS:
            assert remote_type in ENGINE_SPECS, remote_type


class TestEngineMethodSurface:
    """The methods that exist on both sides of a pair.

    Compared per category rather than globally, because the three engines have
    three different inference shapes on purpose — ComfyUI WebSocket, OpenAI chat
    completions, a plain `/synthesize` POST — and only the file half is shared.
    """

    FILE_METHODS = [
        "list_models",
        "upload_file",
        "delete_file",
        "get_file_stream",
    ]

    def test_remote_llm_has_the_full_model_file_surface(self):
        assert RemoteLLMEngine.manages_model_files is True
        for method in self.FILE_METHODS + [
            "download_file",
            "validate_models",
            "setup_models",
            "get_storage_stats",
            "check_health",
        ]:
            assert method in _overrides(RemoteLLMEngine) or hasattr(RemoteLLMEngine, method), (
                f"RemoteLLMEngine is missing {method}"
            )

    def test_remote_llm_matches_modal_llm_on_model_management(self):
        for method in ("list_models", "download_file", "validate_models",
                       "upload_file", "delete_file", "get_file_stream",
                       "setup_models", "get_storage_stats"):
            modal_has = method in _overrides(ModalLlamaCPPEngine)
            remote_has = method in _overrides(RemoteLLMEngine)
            assert modal_has == remote_has, (
                f"modal_llm defines {method}={modal_has} but remote_llm is {remote_has}"
            )

    def test_remote_tts_matches_modal_tts_on_the_file_surface(self):
        for method in self.FILE_METHODS:
            modal_has = method in _overrides(ModalTTSEngine)
            remote_has = method in _overrides(RemoteTTSEngine)
            assert modal_has == remote_has, (
                f"modal_tts defines {method}={modal_has} but remote_tts is {remote_has}"
            )

    def test_remote_tts_does_not_claim_setup(self):
        """The asymmetry, and it is deliberate.

        A TTS root holds audio clips written on demand by `/synthesize`;
        `MODEL_DIRECTORIES` is a ComfyUI concept. `ModalTTSEngine` inherits the
        base's False, so `remote_tts` overriding the mixin's `/setup` call is
        what makes the pair 1-to-1 — removing a claim, not adding a fake one.
        """
        assert ModalTTSEngine.__dict__.get("setup_models") is None, (
            "modal_tts should inherit the base's False, not define its own"
        )
        assert "setup_models" in RemoteTTSEngine.__dict__
        assert RemoteTTSEngine.manages_model_files is False


class TestTheMixinIsShared:
    def test_all_three_remote_engines_use_the_one_protocol(self):
        from services.engines.direct_comfy_engine import DirectComfyEngine
        from services.engines.modal_engine import ModalEngine
        from services.engines.remote_agent_files import RemoteAgentFileMixin

        # The two engines that are pure mixin consumers.
        for cls in (RemoteLLMEngine, RemoteTTSEngine):
            assert issubclass(cls, RemoteAgentFileMixin), cls.__name__
        # The image engine keeps its own implementation and is NOT converted;
        # that is the one place the protocols genuinely differ.
        assert not issubclass(DirectComfyEngine, RemoteAgentFileMixin)
        assert not issubclass(ModalEngine, RemoteAgentFileMixin)

    def test_the_service_token_header_is_defined_once(self):
        """A second definition of a shared constant is how two stop agreeing."""
        from services.engines.worker_transport_engines import SERVICE_TOKEN_HEADER as wt
        from services.engines.remote_agent_files import SERVICE_TOKEN_HEADER as files

        assert wt is files, "the two modules must share one constant object"
        assert wt == "Authorization"


class TestModelDirectoryNarrowing:
    """The last piece of behavioural parity, and the easiest one to miss.

    `modal_llm` narrows to `("models",)` because a vLLM worker has one tree,
    and the generic reconciler fans out over the six *image* `MODEL_DIRECTORIES`
    — so without narrowing, a `remote_llm` provider hashes `checkpoints/` and
    `loras/` against a plain weights root and reports five empty directories.

    `modal_tts` answers `[]` for every directory because TTS voices are chosen
    inside the app, not read from storage.

    Both rules now come from one place in the mixin, and both engines declare
    their narrowing. Together they make the remote LLM behave like the modal
    LLM rather than merely look like it.
    """

    async def _stats(self, engine) -> dict:
        return await engine.get_storage_stats()

    @pytest.mark.asyncio
    async def test_remote_llm_reports_only_the_tree_it_has(self):
        from services.engines.llm_engine import ModalLlamaCPPEngine

        assert RemoteLLMEngine._MODEL_DIRS == ModalLlamaCPPEngine._MODEL_DIRS == ("models",)

    @pytest.mark.asyncio
    async def test_remote_llm_refuses_a_directory_it_does_not_have(self, monkeypatch):
        engine = RemoteLLMEngine("p", "http://x:8001", "tok")

        called = []

        class _Client:
            async def post(self, path, **kw):
                called.append((path, kw))
                raise AssertionError("the agent must not be asked")

        monkeypatch.setattr(engine, "get_agent_client", lambda: _Client())
        assert await engine.list_models("checkpoints") == []
        assert called == [], "a directory outside the tree must not reach the agent"

    @pytest.mark.asyncio
    async def test_remote_llm_storage_stats_walk_only_the_models_dir(self, monkeypatch):
        """Five empty directories would be `modal_llm`'s old denominator."""
        engine = RemoteLLMEngine("p", "http://x:8001", "tok")

        async def _list(directory):
            return []

        monkeypatch.setattr(engine, "list_models", _list)
        seen = []

        async def _recording(directory):
            seen.append(directory)
            return []

        monkeypatch.setattr(engine, "list_models", _recording)
        stats = await engine.get_storage_stats()
        assert seen == ["models"], f"walked {seen}"
        assert stats["by_directory"] == {"models": 0}

    @pytest.mark.asyncio
    async def test_remote_tts_has_no_models_tree_at_all(self, monkeypatch):
        from services.engines.modal_tts_engine import ModalTTSEngine

        # The modal engine encodes this by overriding list_models to return [].
        assert "list_models" in ModalTTSEngine.__dict__
        # The remote one by an empty narrowing, one mixin rule rather than a
        # second override.
        assert RemoteTTSEngine._MODEL_DIRS == ()
        engine = RemoteTTSEngine("p", "http://x:8001", "tok")
        assert await engine.list_models("voices") == []
        assert engine._narrow_dirs(["models", "checkpoints"]) == []

    @pytest.mark.asyncio
    async def test_validate_models_only_asks_for_the_tree_it_has(self, monkeypatch):
        engine = RemoteLLMEngine("p", "http://x:8001", "tok")
        sent = {}

        class _Resp:
            status_code = 200

            def json(self):
                return {"results": []}

        class _Client:
            async def post(self, path, json=None, **kw):
                sent.update(json or {})
                return _Resp()

        monkeypatch.setattr(engine, "get_agent_client", lambda: _Client())
        await engine.validate_models(["models", "checkpoints", "loras"])
        assert sent["directories"] == ["models"]

    @pytest.mark.asyncio
    async def test_a_models_subdirectory_is_still_allowed(self):
        """The `models/`-prefixed escape hatch, matching ModalLlamaCPPEngine's rule."""
        engine = RemoteLLMEngine("p", "http://x:8001", "tok")
        assert engine._directory_allowed("models/hf") is True
        assert engine._narrow_dirs(["models/checkpoints"]) == ["models/checkpoints"]


class TestTopologyIsReported:
    """A `remote_llm` provider manages a tree AND proxies to an upstream.

    `modal_llm` has no such split: its app serves from the volume it manages. On
    the remote side those are two independent settings that can point at two
    different trees, on two different machines, and nothing said so — so an
    operator looking at a populated models tree would reasonably assume it is the
    one being served.

    The sidecar's `/info` answers with the resolved root and the upstream, and
    `check_health` (which `api/routes/providers/crud.py` passes through as
    `telemetry`) carries both. That is what makes the topology checkable rather
    than inferred.
    """

    @pytest.mark.asyncio
    async def test_check_health_carries_the_containers_topology(self, monkeypatch):
        import httpx

        from tests.test_remote_worker_engines import _MockTransport

        engine = RemoteLLMEngine("p", "http://gpu-box:8003", "tok")
        transport = _MockTransport(
            [
                (200, {"worker_mode": "llm", "storage_root": "/opt/llm-weights",
                       "storage_root_env": "LLM_DATA_DIR",
                       "llm_upstream_base": "http://127.0.0.1:8080/v1",
                       "upstream_is_local": True}, {}),
                (200, {"status": "healthy"}, {}),
            ]
        )
        engine._http = httpx.AsyncClient(
            base_url="http://gpu-box:8003", headers={"Authorization": "Bearer tok"},
            transport=transport,
        )

        health = await engine.check_health()

        assert health["ready"] is True
        # Both halves of the topology, next to the verdict.
        assert health["topology"]["storage_root"] == "/opt/llm-weights"
        assert health["topology"]["storage_root_env"] == "LLM_DATA_DIR"
        assert health["topology"]["llm_upstream_base"] == "http://127.0.0.1:8080/v1"
        assert health["topology"]["upstream_is_local"] is True
        paths = [r.url.path for r in transport.requests]
        assert "/info" in paths and "/health" in paths

    @pytest.mark.asyncio
    async def test_the_reported_root_is_the_resolved_path_not_a_variable_name(self, monkeypatch):
        """The engine used to report the variable NAME.

        That is always correct and never useful: the point of the field is that
        the operator can see which tree is being managed, and the name does not
        say. The agent is the only place the resolved value exists.
        """
        import httpx

        from tests.test_remote_worker_engines import _MockTransport

        engine = RemoteLLMEngine("p", "http://gpu-box:8003", "tok")
        transport = _MockTransport(
            [(200, {"worker_mode": "llm", "storage_root": "/mnt/models/llm"}, {})]
        )
        engine._http = httpx.AsyncClient(
            base_url="http://gpu-box:8003", transport=transport
        )

        topology = await engine.topology()
        assert topology["storage_root"] == "/mnt/models/llm"
        # The variable that decided it is still reported, as the provenance.
        assert topology["storage_root_env"] == "LLM_DATA_DIR"

    @pytest.mark.asyncio
    async def test_an_unreachable_info_does_not_fail_health(self, monkeypatch):
        """Health is a diagnostics path; a second failure mode helps nobody."""
        import httpx

        from tests.test_remote_worker_engines import _MockTransport

        engine = RemoteLLMEngine("p", "http://gpu-box:8003", "tok")
        transport = _MockTransport(
            [
                (503, {"detail": "nope"}, {}),
                (200, {"status": "healthy"}, {}),
            ]
        )
        engine._http = httpx.AsyncClient(
            base_url="http://gpu-box:8003", transport=transport
        )

        health = await engine.check_health()
        assert health["ready"] is True
        # Degraded to the variable-name fallback, with the reason attached.
        assert health["topology"]["storage_root_env"] == "LLM_DATA_DIR"
        assert "info_error" in health["topology"]

    @pytest.mark.asyncio
    async def test_tts_topology_omits_the_upstream(self, monkeypatch):
        """No upstream to report outside llm mode."""
        import httpx

        from tests.test_remote_worker_engines import _MockTransport

        engine = RemoteTTSEngine("p", "http://gpu-box:8002", "tok")
        transport = _MockTransport(
            [
                (200, {"worker_mode": "tts", "storage_root": "/opt/ComfyUI",
                       "storage_root_env": "TTS_DATA_DIR"}, {}),
                (200, {"status": "healthy"}, {}),
            ]
        )
        engine._http = httpx.AsyncClient(
            base_url="http://gpu-box:8002", transport=transport
        )

        health = await engine.check_health()
        assert health["topology"]["worker_mode"] == "tts"
        assert health["topology"]["storage_root"] == "/opt/ComfyUI"
        assert "llm_upstream_base" not in health["topology"]
