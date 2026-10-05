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
import ast
import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from provider_core.responses import (
    failed, files_from, files_response, from_upstream, model_file_entries, ok, outcome,
)

PROVIDER_ROOT = Path(__file__).resolve().parents[1]
# `remote_agent/` is a sibling of `provider_containers/`, not a package inside it;
# tests/conftest.py puts the repo root on sys.path and sets the import-time token.
REPO_ROOT = PROVIDER_ROOT.parent
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


class TestFilesFrom:
    """The `response.json().get("files", [])` three call sites inlined.

    A non-dict body — a proxy's 401 HTML page, or a bare JSON array — made that
    expression an `AttributeError` and a 500 that discarded the real status, so an
    odd upstream read as a worker bug instead of the empty listing it is.
    """

    def test_a_dict_keeps_its_list(self):
        assert files_from({"files": [{"name": "a"}]}) == [{"name": "a"}]

    def test_a_bare_array_is_the_list(self):
        assert files_from([{"name": "a"}]) == [{"name": "a"}]

    @pytest.mark.parametrize("body", ["<html>401</html>", 42, None, {"files": "nope"}, {}])
    def test_anything_else_is_an_empty_listing(self, body):
        assert files_from(body) == []

    @pytest.mark.asyncio
    async def test_a_401_html_page_does_not_500_the_remote_comfy_listing(self, monkeypatch):
        """The behavioural half: the old expression raised here."""
        from image_worker.engines.remote_comfy.client import RemoteComfyProviderClient
        from provider_core.models import ListModelsRequest

        client = RemoteComfyProviderClient(runtime_config={})
        response = MagicMock(status_code=200)
        # A proxy in front of the agent answering an HTML error page with 200.
        response.json.return_value = "<html><body>401 Unauthorized</body></html>"
        shared = MagicMock()
        shared.post = AsyncMock(return_value=response)
        monkeypatch.setattr(
            "image_worker.engines.remote_comfy.client.get_http_client", lambda: shared
        )

        payload = await client.list_models(ListModelsRequest(directory="models"))
        assert payload["status"] == "success"
        assert payload["files"] == []
        await client.close()


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
#   run_reconciliation — hands these closures to run_reconciliation_v2, which
#   validate_existing    reads total_invalid / total_partial from, so wrapping
#                        it in the shared envelope would nest the counts under
#                        `result` and reconciliation would read zero of them.
#                        The engine is also required to `raise` when the call
#                        fails (a returned `{}` reads to reconciliation as a clean
#                        sweep), which is only expressible as a plain return.
#   list_existing_files — likewise: a `{path: {...}}` map, not an envelope.
#   download_file       — returns nothing; it raises on failure so reconciliation
#                        records a failed download.
#   delete_file         — returns a bool, the callback contract reconciliation
#                        increments `deletions_completed` on.
#   get_health / get_info / get_storage_stats / get_reconciliation_status /
#   get_config / cancel_job — snapshots, already consistent between engines
#
# The four closures are named here as well as `run_reconciliation` because
# `_dialect_returns` walks nested functions and reads each one's own name.
PASSTHROUGH_METHODS = {
    "get_object_info",
    "run_reconciliation",
    "validate_existing",
    "list_existing_files",
    "download_file",
    "delete_file",
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

    HANDLERS = {
        "list_models", "delete_model", "delete_file", "upload_file",
        "validate_models", "validate_all_models", "setup",
        "download_model_endpoint", "shared_download_model",
    }

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


class TestTheServerSideFilesSpeakTheSameDialect:
    """The two files the ENGINES list above did not cover.

    `provider_core/responses.py`'s module docstring claims four dialects were
    unified and a fifth cannot appear by accident. That was true of the eight
    *worker clients* and nothing else. Five more were live in the two server-side
    files, which a client forwards verbatim through `from_upstream`:

      bare {"files": [...]} with no status   remote_agent list-models,
                                            remote_agent /validate-models,
                                            beam_app /validate-models
      {"success": bool} with no status       remote_agent /delete-model,
                                            /delete-file  (the exact dialect the
                                            docstring claims was eliminated)
      {"status": "success"} with no success  remote_agent /setup, /upload-file
      {"error": "..."} at HTTP 200           beam_app get_object_info

    `remote_agent` is importable here (tests/conftest.py puts the repo root on
    sys.path and supplies the import-time token), so those routes are asserted
    behaviourally. `beam_app` needs beta9 and stays a source check.
    """

    AGENT_ROUTES = [
        "setup", "download_model", "list_models", "delete_model",
        "upload_file", "validate_models",
    ]

    @staticmethod
    def _agent():
        import remote_agent.server as server

        return server

    @pytest.mark.asyncio
    async def test_the_agent_routes_all_answer_in_the_envelope(self, monkeypatch, tmp_path):
        """One call per route, asserting the shape rather than the message."""
        import base64

        server = self._agent()
        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        # /setup seeds eight models and /download-model fetches one. Both are
        # stubbed at the pipeline seam: this test is about the response envelope,
        # and a real seed download would make it network-dependent and slow.
        monkeypatch.setattr(server, "download_model_to_path", lambda **_kw: {"status": "success", "size": 1})
        request = MagicMock()
        request.headers = {"content-length": "1024"}

        payloads = {
            "setup": await server.setup(),
            "download_model": await server.download_model(
                server.DownloadRequest(url="http://127.0.0.1:1/x", path="models/x.safetensors")
            ),
            "list_models": await server.list_models(server.ListModelsRequest(directory="models")),
            "delete_model": await server.delete_model(
                server.DeleteModelRequest(path="models/checkpoints/gone.safetensors")
            ),
            "upload_file": await server.upload_file(
                server.UploadFileRequest(
                    filename="a.txt",
                    content_base64=base64.b64encode(b"hello").decode(),
                    directory="input",
                ),
                request,
            ),
            "validate_models": await server.validate_models(
                server.ValidateModelsRequest(directory=["models/checkpoints"])
            ),
        }

        assert set(payloads) == set(self.AGENT_ROUTES)
        for route, payload in payloads.items():
            assert isinstance(payload, dict), route
            assert "status" in payload, f"{route} answers with no status: {payload}"
            assert "success" in payload, f"{route} answers with no success flag: {payload}"
            assert isinstance(payload["message"], str) and payload["message"], route
            assert payload["success"] is (payload["status"] != "error"), route

    @pytest.mark.asyncio
    async def test_an_oversized_upload_is_refused_before_the_body_is_kept(self, monkeypatch, tmp_path):
        import base64

        server = self._agent()
        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        request = MagicMock()
        request.headers = {"content-length": str(server.UPLOAD_MAX_BYTES_ENCODED + 1)}

        with pytest.raises(HTTPException) as exc:
            await server.upload_file(
                server.UploadFileRequest(
                    filename="a.bin",
                    content_base64=base64.b64encode(b"hello").decode(),
                    directory="input",
                ),
                request,
            )
        assert exc.value.status_code == 413

    def test_the_model_rejects_an_over_long_encoded_field(self):
        import pydantic

        server = self._agent()
        with pytest.raises(pydantic.ValidationError):
            server.UploadFileRequest(
                filename="a.bin",
                content_base64="A" * (server.UPLOAD_MAX_BYTES_ENCODED + 1),
                directory="input",
            )

    def test_get_file_applies_the_shared_size_cap(self, monkeypatch, tmp_path):
        server = self._agent()
        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        (tmp_path / "big.bin").write_bytes(b"x" * 4096)
        monkeypatch.setattr(server, "get_file_size_cap", lambda: 1024)

        with pytest.raises(HTTPException) as exc:
            asyncio.run(server.get_file("big.bin", type="output", subfolder=""))
        assert exc.value.status_code == 413

    def test_get_file_still_serves_a_file_under_the_cap(self, monkeypatch, tmp_path):
        server = self._agent()
        monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
        (tmp_path / "small.bin").write_bytes(b"x" * 16)
        monkeypatch.setattr(server, "get_file_size_cap", lambda: 1024)

        response = asyncio.run(server.get_file("small.bin", type="output", subfolder=""))
        assert os.path.basename(response.path) == "small.bin"

    def test_every_to_thread_in_the_agent_is_bounded(self):
        """Unbounded fan-out is what stopped a single-process agent answering at
        all: 16 /validate-models scans plus a walk plus a download can occupy every
        thread the default executor has."""
        source = (REPO_ROOT / "remote_agent" / "server.py").read_text()
        tree = ast.parse(source)
        # The one legitimate `asyncio.to_thread` is inside `_bounded_to_thread`
        # itself; every other one must go through it.
        bounded = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_bounded_to_thread"
        )
        unbounded = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_thread"
            and getattr(node.func.value, "id", None) == "asyncio"
            and node not in set(ast.walk(bounded))
        ]
        assert not unbounded, f"unbounded asyncio.to_thread at line(s) {unbounded}"
        assert "REMOTE_AGENT_THREAD_MAX_CONCURRENT" in source

    def test_the_agent_imports_the_shared_helpers(self):
        source = (REPO_ROOT / "remote_agent" / "server.py").read_text()
        assert "from provider_core.responses import" in source

    def test_the_agent_carries_no_bare_dialect_return(self):
        """Grep guard, so a new route cannot reintroduce one."""
        source = (REPO_ROOT / "remote_agent" / "server.py").read_text()
        hits = [
            (method, what, line)
            for method, what, line in _dialect_returns(source)
            if method in self.AGENT_ROUTES
        ]
        assert not hits, hits

    def test_beam_app_routes_carry_no_raw_dialect_return(self):
        source = (PROVIDER_ROOT / "image_worker/engines/beam/beam_app.py").read_text()
        hits = [
            (method, what, line)
            for method, what, line in _dialect_returns(source)
            if method in TestBeamStorageAppUsesTheSameDialect.HANDLERS
            or method == "get_object_info"
        ]
        assert not hits, hits

    def test_the_extractor_cannot_hit_unboundlocalerror(self):
        """The audit claimed `return data` after a `try/finally` could run with `data`
        unbound. As written it could not — an exception in the `try` propagates
        after the `finally`, so the `return` is unreachable — but the shape is
        gone anyway, and the assertion below is the one that would catch a
        regression: a function that returns a name it binds inside a `Try` body
        and that can also fall through to that `return`."""
        import ast

        source = (PROVIDER_ROOT / "image_worker/engines/beam/beam_app.py").read_text()
        tree = ast.parse(source)

        for fn in (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)):
            returned = {
                node.value.id
                for node in ast.walk(fn)
                if isinstance(node, ast.Return)
                and isinstance(node.value, ast.Name)
            }
            if not returned:
                continue
            bound_inside_try = {
                target.id
                for stmt in ast.walk(fn)
                if isinstance(stmt, ast.Try)
                for inner in ast.walk(stmt)
                if isinstance(inner, ast.Assign)
                for target in inner.targets
                if isinstance(target, ast.Name)
            }
            # A `Return` that is lexically inside the same `Try` is fine: the
            # exception path never reaches it. One after the `Try` is the bug.
            for stmt in fn.body:
                if not isinstance(stmt, ast.Return) or not isinstance(stmt.value, ast.Name):
                    continue
                assert stmt.value.id not in bound_inside_try, (
                    f"{fn.name} returns {stmt.value.id!r} at the end of the function "
                    "but only ever binds it inside a try — the finally runs first, "
                    "so an early exception turns this into an UnboundLocalError"
                )

    def test_the_extractor_route_delegates_and_answers_with_a_status(self):
        """`get_object_info` used to return `{"error": ...}` at HTTP 200, which no
        client can distinguish from a successful extraction with no nodes."""
        import ast

        source = (PROVIDER_ROOT / "image_worker/engines/beam/beam_app.py").read_text()
        tree = ast.parse(source)
        route = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_object_info"
        )
        assert any(
            isinstance(node, ast.Await)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "to_thread"
            for node in ast.walk(route)
        ), (
            "a 60 s ready-poll plus a 60 s requests.get on the event loop stopped the "
            "whole extractor deployment answering; it must be in a thread"
        )
        assert any(
            isinstance(node, ast.Raise) and "HTTPException" in ast.dump(node.exc)
            for node in ast.walk(route)
        ), "the failure paths must be HTTP statuses, not a 200 with an error key"


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
