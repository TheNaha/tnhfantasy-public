"""One response dialect across every engine (audit follow-up items 2 and 3).

Four shapes were live across nine engine methods, all HTTP 200:

  {"success": bool, ...}             modal / beam / remote_comfy / direct_url
  {"status": "error", ...} + 200     direct_url.upload_file
  bare {"files": [...]}              every LLM engine's list_models
  raw ``response.json()``            beam / remote_comfy

so a caller could not tell success from failure by status code, and
`direct_url.validate_models` passed `available=` to a `StatusResponse` that
declares no such field, so Pydantic v2's `extra='ignore'` dropped the entire
result.

Every test here also asserts the *backend contract* — the keys
`backend_v2` actually reads:

  * ``data.get("files")``      — llm_config.py, api/routes/models/maintenance.py
  * ``body.get("status") == "error"`` for a failed upload — api/routes/files.py
  * HTTP 200 for a successful delete-model / delete-file — the provider configs
    in ``backend_v2/infrastructure/providers/*_config.py`` decide from the
    status code alone and never look at the body
  * ``result.get("status") in {"queued", "started"}`` for /setup —
    services/provider_lifecycle_service.py
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from provider_core.responses import (
    failed, files_response, from_upstream, model_file_entries, ok, outcome,
)

PROVIDER_ROOT = Path(__file__).resolve().parents[1]
ENGINES = [
    "image_worker/engines/modal/client.py",
    "image_worker/engines/beam/client.py",
    "image_worker/engines/remote_comfy/client.py",
    "image_worker/engines/direct_url/client.py",
    "llm_worker/engines/openai_compat/client.py",
    "llm_worker/engines/anthropic/client.py",
    "llm_worker/engines/google/client.py",
    "llm_worker/engines/modal/client.py",
]


class TestBuilders:
    def test_ok_shape(self):
        payload = ok("done", provider="p1")
        assert payload == {
            "status": "success",
            "success": True,
            "message": "done",
            "provider": "p1",
            "files": [],
        }

    def test_ok_always_carries_files(self):
        """`files` is the key the backend reads on /list-models."""
        assert ok("nothing")["files"] == []

    def test_ok_queued(self):
        assert ok("queued", status="queued")["status"] == "queued"

    def test_ok_passes_result_through(self):
        assert ok("done", result={"a": 1})["result"] == {"a": 1}

    def test_ok_keeps_extra_keys(self):
        payload = ok("uploaded", path="models/a.safetensors", size=12)
        assert payload["path"] == "models/a.safetensors"
        assert payload["size"] == 12

    def test_extra_cannot_clobber_the_envelope(self):
        """An adopted upstream body must not be able to downgrade a success."""
        payload = from_upstream({"status": "success", "success": True, "message": "mine"})
        assert payload["status"] == "success"
        assert payload["success"] is True

    def test_failed_defaults_to_permanent(self):
        payload = failed("nope")
        assert payload == {"status": "error", "success": False, "message": "nope", "retryable": False}

    def test_failed_carries_code_and_retryable(self):
        payload = failed("gateway", code=502, retryable=True, provider="p1")
        assert payload["code"] == 502
        assert payload["retryable"] is True
        assert payload["provider"] == "p1"

    def test_outcome_splits_the_bool(self):
        assert outcome(True, "Deleted x")["status"] == "success"
        bad = outcome(False, "Failed to delete x", code=404)
        assert bad["status"] == "error"
        assert bad["success"] is False
        assert bad["code"] == 404

    def test_files_response_wraps_bare_files(self):
        payload = files_response([{"path": "m", "name": "m"}], provider="p1")
        assert payload["status"] == "success"
        assert payload["files"] == [{"path": "m", "name": "m"}]
        assert payload["message"] == "Listed 1 models"

    def test_model_file_entries_wraps_bare_strings(self):
        """llm_config.py accepts dicts or strings; a string must not be dropped."""
        assert model_file_entries(["a", {"path": "b"}, "", None]) == [
            {"path": "a", "name": "a"},
            {"path": "b"},
        ]


class TestFromUpstream:
    def test_preserves_upstream_keys(self):
        payload = from_upstream(
            {"status": "success", "directories": ["/mnt/data/models"]}, provider="p1"
        )
        assert payload["directories"] == ["/mnt/data/models"]
        assert payload["status"] == "success"
        assert payload["provider"] == "p1"

    def test_upstream_error_becomes_a_failure(self):
        payload = from_upstream({"status": "error", "message": "Invalid path"}, provider="p1")
        assert payload["status"] == "error"
        assert payload["success"] is False
        assert payload["message"] == "Invalid path"

    def test_upstream_success_false_becomes_a_failure(self):
        payload = from_upstream({"success": False, "message": "File not found"})
        assert payload["status"] == "error"
        assert payload["message"] == "File not found"

    def test_upstream_retryable_is_honoured(self):
        payload = from_upstream({"status": "error", "message": "x", "retryable": True})
        assert payload["retryable"] is True

    def test_upstream_files_become_the_files_key(self):
        payload = from_upstream({"files": [{"path": "a"}]})
        assert payload["files"] == [{"path": "a"}]

    def test_non_dict_upstream_is_survivable(self):
        payload = from_upstream(["not", "a", "dict"], provider="p1")
        assert payload["status"] == "success"
        assert payload["files"] == []


class TestDirectUrlValidateModelsKeepsItsResult:
    """Audit item 23. `build_status_response(..., available=available)` was a
    silent no-op: StatusResponse declares status/message/provider/result/files
    and sets no model_config, so Pydantic v2 dropped `available`. The whole
    method — and `validate_all_models`, which delegates to it — returned
    nothing.
    """

    OBJECT_INFO = {
        "CheckpointLoaderSimple": {
            "input": {"required": [["ckpt_name", [["a.safetensors", "b.safetensors"]]]]},
        },
        "LoraLoader": {"input": {"required": [["model_name", [["l.safetensors"]]]]}},
    }

    @pytest.mark.asyncio
    async def test_available_survives(self):
        from image_worker.engines.direct_url.client import DirectUrlProviderClient
        from provider_core.models import ValidateModelsRequest

        client = DirectUrlProviderClient(runtime_config={})
        response = MagicMock()
        response.json.return_value = self.OBJECT_INFO
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=response)
        client._http.aclose = AsyncMock()
        try:
            payload = await client.validate_models(ValidateModelsRequest(directory=""))
        finally:
            await client.close()

        assert payload["available"] == [
            "checkpoints/a.safetensors",
            "checkpoints/b.safetensors",
            "loras/l.safetensors",
        ]
        assert payload["result"] == payload["available"], (
            "the declared StatusResponse slot must carry the result too"
        )
        assert payload["status"] == "success"
        assert payload["success"] is True

    @pytest.mark.asyncio
    async def test_validate_all_models_delegates_and_keeps_it(self):
        from image_worker.engines.direct_url.client import DirectUrlProviderClient

        client = DirectUrlProviderClient(runtime_config={})
        response = MagicMock()
        response.json.return_value = self.OBJECT_INFO
        client._http = MagicMock()
        client._http.get = AsyncMock(return_value=response)
        client._http.aclose = AsyncMock()
        try:
            payload = await client.validate_all_models()
        finally:
            await client.close()

        assert len(payload["available"]) == 3

    def test_pydantic_really_would_have_dropped_it(self):
        """Pins the mechanism, so the regression cannot be reintroduced as
        "harmless" if StatusResponse ever grows an `available` field.

        Note the actual failure mode: `build_status_response` has an explicit
        keyword-only signature, so the old call did not silently drop
        `available` — it raised TypeError, which the router's generic handler
        turned into a 500 "Internal server error". Passing the extra to the
        model *directly* is the shape that drops it, and that is what the
        Pydantic `extra='ignore'` default does.
        """
        from provider_core.models import StatusResponse, build_status_response

        with pytest.raises(TypeError):
            build_status_response("success", "x", available=["a"])

        assert StatusResponse(status="success", message="x", available=["a"]).model_dump(
            exclude_none=True
        ) == {"status": "success", "message": "x"}

        assert "available" in ok("x", available=["a"])


class TestDirectUrlUnimplementedOperations:
    """The three direct_url methods that used to answer `{"success": False}` /
    `{"status": "error"}` with HTTP 200. The backend detects a failed upload by
    `body["status"] == "error"` (api/routes/files.py), so that key must stay.
    """

    @pytest.mark.asyncio
    async def test_upload_file_is_still_detected_as_an_error(self):
        from image_worker.engines.direct_url.client import DirectUrlProviderClient
        from provider_core.models import UploadFileRequest

        client = DirectUrlProviderClient(runtime_config={})
        try:
            payload = await client.upload_file(
                UploadFileRequest(filename="f", content_base64="", directory="d")
            )
        finally:
            await client.close()

        assert payload["status"] == "error", (
            "files.py counts this as synced_failed on anything else"
        )
        assert payload["success"] is False
        assert payload["retryable"] is False

    @pytest.mark.asyncio
    async def test_delete_model_and_delete_file_report_failure(self):
        from image_worker.engines.direct_url.client import DirectUrlProviderClient
        from provider_core.models import DeleteModelRequest

        client = DirectUrlProviderClient(runtime_config={})
        try:
            deleted = await client.delete_model(DeleteModelRequest(path="models/a"))
            removed = await client.delete_file("models/a")
        finally:
            await client.close()

        for payload in (deleted, removed):
            assert payload["status"] == "error"
            assert payload["success"] is False


class TestLLMListModelsKeepsFiles:
    """The LLM engines answered a bare {"files": [...]} with no status key at
    all. llm_config.py reads `data.get("files")`; that must keep working.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("engine_path", [
        "llm_worker/engines/openai_compat/client.py",
        "llm_worker/engines/anthropic/client.py",
        "llm_worker/engines/google/client.py",
    ])
    async def test_list_models_always_has_a_status_and_files(self, engine_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        monkeypatch.setenv("GOOGLE_API_KEY", "")
        monkeypatch.setenv("OPENAI_API_BASE", "http://127.0.0.1:9/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "")

        if "openai_compat" in engine_path:
            from llm_worker.engines.openai_compat.client import OpenAICompatProviderClient as Client
        elif "anthropic" in engine_path:
            from llm_worker.engines.anthropic.client import AnthropicProviderClient as Client
        else:
            from llm_worker.engines.google.client import GoogleProviderClient as Client

        client = Client(provider_id="llm-test", runtime_config={})
        payload = await client.list_models()

        assert payload["status"] == "success"
        assert payload["success"] is True
        assert isinstance(payload["files"], list)
        # what llm_config.py does with it
        files = payload.get("files") or payload.get("models") or []
        assert isinstance(files, list)

    @pytest.mark.asyncio
    async def test_openai_compat_list_models_survives_a_dead_upstream(self):
        from llm_worker.engines.openai_compat.client import OpenAICompatProviderClient

        client = OpenAICompatProviderClient(provider_id="llm-test", runtime_config={})
        client.api_base = "http://127.0.0.1:9/v1"
        client.api_key = ""
        payload = await client.list_models()
        assert payload["status"] == "success"
        assert payload["files"] == []


class TestBeamAndRemoteComfyAdoptUpstream:
    @pytest.mark.asyncio
    async def test_beam_setup_keeps_directories(self, monkeypatch):
        from image_worker.engines.beam.client import BeamProviderClient

        client = BeamProviderClient(runtime_config={})
        response = MagicMock(status_code=200)
        response.json.return_value = {"status": "success", "directories": ["/mnt/data/models"]}
        shared = MagicMock()
        shared.post = AsyncMock(return_value=response)
        monkeypatch.setattr(
            "image_worker.engines.beam.client.get_http_client", lambda: shared
        )
        payload = await client.setup_models()
        assert payload["directories"] == ["/mnt/data/models"]
        assert payload["status"] == "success"
        assert payload["success"] is True

    @pytest.mark.asyncio
    async def test_remote_comfy_upload_keeps_path_and_size(self, monkeypatch):
        from image_worker.engines.remote_comfy.client import RemoteComfyProviderClient
        from provider_core.models import UploadFileRequest

        client = RemoteComfyProviderClient(runtime_config={})
        response = MagicMock(status_code=200)
        response.json.return_value = {"status": "success", "path": "models/a", "size": 3}
        shared = MagicMock()
        shared.post = AsyncMock(return_value=response)
        monkeypatch.setattr(
            "image_worker.engines.remote_comfy.client.get_http_client", lambda: shared
        )
        payload = await client.upload_file(
            UploadFileRequest(filename="a", content_base64="", directory="models")
        )
        assert payload["path"] == "models/a"
        assert payload["size"] == 3
        assert payload["status"] == "success"
        assert payload["success"] is True

    @pytest.mark.asyncio
    async def test_validate_models_failure_keeps_the_empty_lists(self, monkeypatch):
        """`valid`/`invalid`/`partial` are read by reconciliation consumers."""
        from image_worker.engines.remote_comfy.client import RemoteComfyProviderClient
        from provider_core.models import ValidateModelsRequest

        client = RemoteComfyProviderClient(runtime_config={})
        shared = MagicMock()
        shared.post = AsyncMock(return_value=MagicMock(status_code=500, text="boom"))
        monkeypatch.setattr(
            "image_worker.engines.remote_comfy.client.get_http_client", lambda: shared
        )
        payload = await client.validate_models(ValidateModelsRequest(directory="models"))
        assert payload["status"] == "error"
        assert payload["valid"] == []
        assert payload["invalid"] == []
        assert payload["partial"] == []

    @pytest.mark.asyncio
    async def test_validate_models_success_keeps_every_key(self, monkeypatch):
        from image_worker.engines.remote_comfy.client import RemoteComfyProviderClient
        from provider_core.models import ValidateModelsRequest

        client = RemoteComfyProviderClient(runtime_config={})
        response = MagicMock(status_code=200)
        response.json.return_value = {"valid": [{"name": "a"}], "invalid": [], "partial": []}
        shared = MagicMock()
        shared.post = AsyncMock(return_value=response)
        monkeypatch.setattr(
            "image_worker.engines.remote_comfy.client.get_http_client", lambda: shared
        )
        payload = await client.validate_models(ValidateModelsRequest(directory="models"))
        assert payload["valid"] == [{"name": "a"}]
        assert payload["by_directory"] == {"models": {"valid": [{"name": "a"}], "invalid": [], "partial": []}}
        assert payload["result"]["valid"] == [{"name": "a"}]
        assert payload["status"] == "success"


# Methods whose return value is a foreign document, an internal contract, or a
# state snapshot read by key name — so the dialect does not apply:
#   get_object_info    — a verbatim pass-through of ComfyUI's /object_info,
#                        which api/routes/nodes.py returns unchanged to the UI
#   run_reconciliation — the inner closures feed run_reconciliation_v2, which
#                        reads total_invalid / total_partial from them
#   get_health / get_info / get_storage_stats / get_reconciliation_status /
#   get_config / cancel_job — snapshots, already consistent between engines
PASSTHROUGH_METHODS = {
    "get_object_info",
    "run_reconciliation",
    "get_health",
    "get_info",
    "get_storage_stats",
    "get_reconciliation_status",
    "get_config",
    "update_config",
    "cancel_job",
}


def _dialect_returns(source: str):
    """Yield (method, description) for every remaining old-dialect return."""
    import ast

    tree = ast.parse(source)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        method = node.name
        for child in ast.walk(node):
            if not isinstance(child, ast.Return) or child.value is None:
                continue
            value = child.value
            if isinstance(value, ast.Dict):
                keys = [k.value for k in value.keys if isinstance(k, ast.Constant)]
                if keys and set(keys) & {"success", "status", "files"}:
                    hits.append((method, f"dict literal with {sorted(set(keys))}", child.lineno))
            elif isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                if value.func.attr == "json":
                    hits.append((method, "raw response.json()", child.lineno))
    return hits


class TestNoDialectLeftInTheEngines:
    """Grep guard: the four shapes must not come back."""

    @pytest.mark.parametrize("engine", ENGINES)
    def test_engine_has_no_raw_dialect_return(self, engine):
        source = (PROVIDER_ROOT / engine).read_text()
        offenders = [
            (method, what, line)
            for method, what, line in _dialect_returns(source)
            if method not in PASSTHROUGH_METHODS
        ]
        assert not offenders, (
            f"{engine} still returns a raw dialect outside the documented "
            f"pass-through methods: {offenders}"
        )

    @pytest.mark.parametrize("engine", ENGINES)
    def test_engine_no_longer_imports_the_old_builders(self, engine):
        import ast

        source = (PROVIDER_ROOT / engine).read_text()
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        assert "build_status_response" not in imported, engine
        assert "build_error_response" not in imported, engine


class TestBeamStorageAppUsesTheSameDialect:
    """`beam_app.py` is the deployed storage server; its client adopts whatever
    it answers, so it is worth holding to the same shape. It cannot be
    imported in tests (it needs beta9), so the handlers are checked by source.
    """

    HANDLERS = {"list_models", "delete_model", "delete_file", "upload_file"}

    def test_handlers_have_no_raw_dialect_return(self):
        source = (PROVIDER_ROOT / "image_worker/engines/beam/beam_app.py").read_text()
        hits = [
            (method, what, line)
            for method, what, line in _dialect_returns(source)
            if method in self.HANDLERS
        ]
        assert not hits, hits

    def test_it_imports_the_shared_helpers(self):
        source = (PROVIDER_ROOT / "image_worker/engines/beam/beam_app.py").read_text()
        assert "from provider_core.responses import" in source

    @pytest.mark.asyncio
    async def test_client_honours_an_upstream_delete_failure(self, monkeypatch):
        """HTTP 200 with `success: false` used to be reported as a deletion."""
        from image_worker.engines.beam.client import BeamProviderClient
        from provider_core.models import DeleteModelRequest

        client = BeamProviderClient(runtime_config={})
        response = MagicMock(status_code=200)
        response.json.return_value = {"success": False, "message": "Not found: models/a"}
        shared = MagicMock()
        shared.post = AsyncMock(return_value=response)
        monkeypatch.setattr(
            "image_worker.engines.beam.client.get_http_client", lambda: shared
        )

        payload = await client.delete_model(DeleteModelRequest(path="models/a"))
        assert payload["status"] == "error"
        assert payload["success"] is False
        assert payload["message"] == "Not found: models/a"

    @pytest.mark.asyncio
    async def test_client_reports_a_real_deletion(self, monkeypatch):
        from image_worker.engines.beam.client import BeamProviderClient
        from provider_core.models import DeleteModelRequest

        client = BeamProviderClient(runtime_config={})
        response = MagicMock(status_code=200)
        response.json.return_value = {"success": True, "message": "Deleted models/a", "files": []}
        shared = MagicMock()
        shared.post = AsyncMock(return_value=response)
        monkeypatch.setattr(
            "image_worker.engines.beam.client.get_http_client", lambda: shared
        )

        payload = await client.delete_model(DeleteModelRequest(path="models/a"))
        assert payload["status"] == "success"
        assert payload["success"] is True


class TestDialectIsSerialisable:
    def test_every_builder_output_is_json(self):
        for payload in (
            ok("a", provider="p", result={"x": 1}),
            failed("b", code=500, retryable=True, provider="p"),
            outcome(False, "c", code=404),
            files_response([{"path": "m"}]),
            from_upstream({"status": "error", "message": "d"}),
        ):
            assert json.loads(json.dumps(payload)) == payload
