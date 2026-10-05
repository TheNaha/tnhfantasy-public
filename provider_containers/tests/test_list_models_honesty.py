"""`list_models` must not invent model ids.

The backend's fallback (`backend_v2/api/routes/world_vault/llm_config.py`) reads
`data.get("files")` and substitutes `[{"id": "default"}]` **only when the list
comes back empty**. So a provider that fabricates ids on failure does not merely
return a wrong answer — it suppresses the backend's own honest fallback, and the
user gets a populated model dropdown in which every entry fails:

    Anthropic key revoked -> 401 -> "claude-sonnet-4-20250514" offered
                           -> user picks it -> every turn fails

`openai_compat` and `modal` already returned `[]`; anthropic and google returned
five hardcoded ids, and did so on an *empty successful* response too. All four now
return `[]`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

#: The three HTTP engines. They share a seam — `get_http_client().get_client()` —
#: so one pair of helpers covers all of them. The Modal engine reaches its listing
#: through an RPC instead and is covered separately below.
ENGINES = (
    ("llm_worker.engines.anthropic.client", "AnthropicProviderClient", "ANTHROPIC_API_KEY"),
    ("llm_worker.engines.google.client", "GoogleProviderClient", "GOOGLE_API_KEY"),
    ("llm_worker.engines.openai_compat.client", "OpenAICompatProviderClient", "OPENAI_API_KEY"),
)

ALL_FILES = ENGINES + (
    ("llm_worker.engines.modal.client", "VLLMModalProviderClient", "HF_TOKEN"),
)


def _client(dotted: str, class_name: str, **kwargs):
    module = __import__(dotted, fromlist=[class_name])
    return getattr(module, class_name)(provider_id="test", runtime_config=kwargs)


def _raise_on_get(monkeypatch, dotted: str, exc: Exception):
    """Every engine reaches its model list through `get_http_client().get_client()`."""
    module = __import__(dotted, fromlist=["x"])

    client = MagicMock()
    client.get = AsyncMock(side_effect=exc)
    shared = MagicMock()
    shared.get_client = AsyncMock(return_value=client)

    monkeypatch.setattr(module, "get_http_client", lambda: shared)
    return client


def _ok_on_get(monkeypatch, dotted: str, payload: dict):
    module = __import__(dotted, fromlist=["x"])

    response = MagicMock(status_code=200)
    response.json = MagicMock(return_value=payload)
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.get = AsyncMock(return_value=response)
    shared = MagicMock()
    shared.get_client = AsyncMock(return_value=client)

    monkeypatch.setattr(module, "get_http_client", lambda: shared)
    return client


class TestAFailedListingInventsNothing:
    @pytest.mark.parametrize("dotted,class_name,key_env", ENGINES)
    @pytest.mark.parametrize(
        "failure",
        [
            RuntimeError("connection reset"),
            RuntimeError("401 Unauthorized: invalid x-api-key"),
            TimeoutError("timed out"),
        ],
        ids=["reset", "401", "timeout"],
    )
    @pytest.mark.asyncio
    async def test_the_files_list_is_empty(self, dotted, class_name, key_env, failure, monkeypatch):
        monkeypatch.setenv(key_env, "test-key")
        _raise_on_get(monkeypatch, dotted, failure)

        payload = await _client(dotted, class_name).list_models()

        assert payload.get("files") == [], (
            f"{dotted} invented {payload.get('files')} for a failed listing"
        )

    @pytest.mark.parametrize("dotted,class_name,key_env", ENGINES)
    @pytest.mark.asyncio
    async def test_no_key_configured_also_lists_nothing(self, dotted, class_name, key_env, monkeypatch):
        """A missing key and a revoked key are the same thing to the caller:
        nothing can be served. Offering models that cannot answer is the same
        defect either way."""
        monkeypatch.delenv(key_env, raising=False)
        for other in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(other, raising=False)

        payload = await _client(dotted, class_name).list_models()

        assert payload.get("files") == [], f"{dotted} invented {payload.get('files')}"

    @pytest.mark.parametrize("dotted,class_name,key_env", ENGINES)
    @pytest.mark.asyncio
    async def test_an_empty_successful_response_stays_empty(
        self, dotted, class_name, key_env, monkeypatch
    ):
        """The other half of `if not models: models = fallback`.

        An account that has no usable models, or (Google) a set of models none of
        which support `generateContent`, is a real answer and must not be replaced
        with five names from a hardcoded list.
        """
        monkeypatch.setenv(key_env, "test-key")
        _ok_on_get(monkeypatch, dotted, {"data": [], "models": []})

        payload = await _client(dotted, class_name).list_models()

        assert payload.get("files") == [], (
            f"{dotted} replaced an empty successful response with "
            f"{payload.get('files')}"
        )


class TestAPopulatedResponseIsStillReported:
    """The control. "Never fabricate" must not become "never list"."""

    @pytest.mark.asyncio
    async def test_anthropic_reports_its_real_models(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        _ok_on_get(
            monkeypatch,
            "llm_worker.engines.anthropic.client",
            {"data": [{"id": "claude-b"}, {"id": "claude-a"}, {"id": ""}]},
        )

        payload = await _client(
            "llm_worker.engines.anthropic.client", "AnthropicProviderClient"
        ).list_models()

        assert [f["path"] for f in payload["files"]] == ["claude-a", "claude-b"], payload

    @pytest.mark.asyncio
    async def test_google_reports_only_generate_content_models(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        _ok_on_get(
            monkeypatch,
            "llm_worker.engines.google.client",
            {
                "models": [
                    {
                        "name": "models/gemini-b",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/embedding-only",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
        )

        payload = await _client(
            "llm_worker.engines.google.client", "GoogleProviderClient"
        ).list_models()

        assert [f["path"] for f in payload["files"]] == ["gemini-b"], payload


class TestNoEngineCarriesAHardcodedModelList:
    """Structural, so the next engine cannot reintroduce the shape.

    The fabricated ids were module-level literals in two files and nothing else,
    so their absence is checkable — and a comment that merely *mentions* one of
    them (as the fix's own note does) would defeat a substring match. Matched on
    the assignment shape instead.
    """

    FILES = (
        "llm_worker/engines/anthropic/client.py",
        "llm_worker/engines/google/client.py",
        "llm_worker/engines/openai_compat/client.py",
        "llm_worker/engines/modal/client.py",
    )

    @pytest.mark.parametrize("relpath", FILES)
    def test_no_fallback_model_id_list(self, relpath):
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        tree = ast.parse((root / relpath).read_text())

        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if not isinstance(value, (ast.List, ast.Tuple)):
                continue
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if not names:
                continue
            # A list of model identifiers: every element is a string literal that
            # looks like a model id rather than a message or a URL.
            literals = [
                element.value
                for element in value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            ]
            if not literals or len(literals) != len(value.elts):
                continue
            if sum(1 for lit in literals if lit[:1].isalpha() and "-" in lit) >= 2:
                offenders.append((names, literals))

        assert not offenders, f"{relpath} still hardcodes a model id list: {offenders}"


class TestTheModalEngineAgrees:
    """It reached `[]` first; the point is that it still does.

    Its seam is an RPC, not `get_http_client`, so it needs its own setup.
    """

    @pytest.mark.asyncio
    async def test_a_failed_rpc_lists_nothing(self, monkeypatch):
        import llm_worker.engines.modal.client as mod

        monkeypatch.setenv("HF_TOKEN", "hf_test")
        client = mod.VLLMModalProviderClient(provider_id="test", runtime_config={})

        def _raise(name):
            raise RuntimeError("volume is not reachable")

        monkeypatch.setattr(client, "_get_modal_function", _raise)

        payload = await client.list_models()
        assert payload.get("files") == [], payload

    @pytest.mark.asyncio
    async def test_a_populated_rpc_is_still_reported(self, monkeypatch):
        import llm_worker.engines.modal.client as mod

        monkeypatch.setenv("HF_TOKEN", "hf_test")
        client = mod.VLLMModalProviderClient(provider_id="test", runtime_config={})

        class _Fn:
            class remote:
                @staticmethod
                async def aio(directory):
                    return [{"name": "a.gguf", "size": 10}]

        monkeypatch.setattr(client, "_get_modal_function", lambda name: _Fn)

        payload = await client.list_models()
        assert [f["name"] for f in payload["files"]] == ["a.gguf"], payload


class TestTheBackendFallbackIsWhatTheUserSees:
    """The seam, restated from the backend's own code.

    `llm_config.py` reads `data.get("files")` and falls back to `[{"id":
    "default"}]` only for an empty list. So `files == []` is the answer that leaves
    the backend's honest fallback in place, and any fabricated entry removes it.
    """

    @pytest.mark.parametrize("dotted,class_name,key_env", ENGINES)
    @pytest.mark.asyncio
    async def test_a_failed_listing_leaves_the_backend_free_to_fall_back(
        self, dotted, class_name, key_env, monkeypatch
    ):
        monkeypatch.setenv(key_env, "test-key")
        _raise_on_get(monkeypatch, dotted, RuntimeError("boom"))

        payload = await _client(dotted, class_name).list_models()
        files = payload.get("files")

        # llm_config.py's rule, verbatim.
        offered = files if files else [{"id": "default"}]

        assert offered == [{"id": "default"}], (
            f"{dotted} suppressed the backend's fallback and offered {offered}"
        )
