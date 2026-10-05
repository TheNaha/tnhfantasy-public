"""A failed `/validate-all-models` must not read as "every model is valid".

Reconciliation's step 0 (`provider_core/reconciliation.py`) is:

    try:
        validation_result = await validate_existing(True)
        invalid_count = validation_result.get("total_invalid", 0)
        partial_count = validation_result.get("total_partial", 0)
        ...
        logger.info("[V2 Reconciliation] ✓ All existing models are valid")
    except Exception as exc:
        logger.warning(f"[V2 Reconciliation] ⚠ Validation step failed: {exc}")

`{}` and `{"total_invalid": 0}` are the same thing to that code. So an engine that
returned `{}` for a *failed* HTTP call reported a clean sweep, and the operator
saw a green line on a provider it could not authenticate to. The Modal twin
already raised and already produced "⚠ Validation step failed" — three engines,
one logical sweep, two answers, and the wrong one was silent.

Both halves are asserted, because they are the two things that were wrong: the
engine's closure must raise, and reconciliation must record the raise as a failure
rather than as a clean bill of health.
"""

from __future__ import annotations

import ast
import logging
import pathlib
from unittest.mock import AsyncMock

import pytest

CLEAN_SWEEP = "✓ All existing models are valid"
VALIDATION_FAILED = "⚠ Validation step failed"

ENGINES = (
    ("image_worker.engines.beam.client", "BeamProviderClient", "beam-worker"),
    (
        "image_worker.engines.remote_comfy.client",
        "RemoteComfyProviderClient",
        "remote-comfy-worker",
    ),
)


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class _Http:
    """Answers each POST from `responses`, matched on a URL fragment."""

    def __init__(self, responses):
        self.responses = responses

    async def post(self, url, **kwargs):
        for fragment, response in self.responses.items():
            if fragment in url:
                return response
        return _Response(200, {})


async def _capture_validate_existing(client, module, monkeypatch, http):
    """Run the engine's `run_reconciliation` and hand back its real closures.

    The same interception `tests/test_storage_contracts.py` uses, and for the same
    reason: `validate_existing` is a closure, and the closure is the seam whose
    behaviour diverged — a test that re-types its body proves nothing.
    """
    captured = {}

    async def _capture(**kwargs):
        captured.update(kwargs)
        return {"status": "started"}

    monkeypatch.setattr(client, "_start_reconciliation_task", _capture)
    monkeypatch.setattr(module, "get_http_client", lambda: http)
    await client.run_reconciliation(quick_sync=False)
    return captured["validate_existing_fn"]


@pytest.fixture
def worker_log():
    """Collect `provider_core.reconciliation`'s output.

    `provider_core/logging.py::get_logger` sets `propagate = False` and installs
    its own stdout handler, so `caplog` sees nothing — the reconciliation lines
    this file is about go to the container's stdout and nowhere else.
    """
    import provider_core.logging as core_logging

    captured = []

    class _Collect(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    logger = core_logging.get_logger("provider_core.reconciliation")
    previous_level = logger.level
    handler = _Collect()
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield captured
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


async def _run_step_zero(validate_existing, monkeypatch):
    """Drive `run_reconciliation_v2` with the engine's own closure and nothing else."""
    from provider_core.reconciliation import run_reconciliation_v2
    from provider_core.state import ReconciliationState

    monkeypatch.setattr(
        "provider_core.reconciliation.get_pending_downloads", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        "provider_core.reconciliation.get_all_expected_paths", AsyncMock(return_value=set())
    )
    monkeypatch.setattr(
        "provider_core.reconciliation.batch_update_file_status_v2", AsyncMock()
    )
    monkeypatch.setattr(
        "provider_core.reconciliation.push_reconciliation_event", AsyncMock(return_value=True)
    )

    await run_reconciliation_v2(
        provider_id="beam-worker",
        backend_url="http://backend",
        reconciliation_state=ReconciliationState("beam-worker"),
        max_concurrent_downloads=1,
        hf_token="",
        civitai_token="",
        storage_label="Beam",
        validate_existing=validate_existing,
        list_existing_files=AsyncMock(return_value={}),
        download_file=AsyncMock(),
        delete_file=AsyncMock(),
    )


class TestTheValidateSeamRaises:
    @pytest.mark.parametrize("dotted,class_name,provider_id", ENGINES)
    @pytest.mark.parametrize(
        ("status", "body"),
        [
            (401, "Unauthorized: bad API key"),
            (500, "storage deployment is down"),
            (404, "no such deployment"),
        ],
    )
    @pytest.mark.asyncio
    async def test_a_non_200_raises_with_the_diagnosis(
        self, dotted, class_name, provider_id, status, body, monkeypatch
    ):
        module = __import__(dotted, fromlist=[class_name])
        client = getattr(module, class_name)(runtime_config={})
        http = _Http({"validate-all-models": _Response(status, {}, text=body)})

        validate_existing = await _capture_validate_existing(client, module, monkeypatch, http)

        with pytest.raises(RuntimeError) as raised:
            await validate_existing(True)

        message = str(raised.value)
        assert "validate-all-models" in message, message
        assert str(status) in message, message
        assert body in message, "the upstream's own body is the diagnosis"

    @pytest.mark.parametrize("dotted,class_name,provider_id", ENGINES)
    @pytest.mark.asyncio
    async def test_a_200_is_returned_unchanged(self, dotted, class_name, provider_id, monkeypatch):
        """The control: the raise must not be satisfied by always raising."""
        module = __import__(dotted, fromlist=[class_name])
        client = getattr(module, class_name)(runtime_config={})
        body = {"total_invalid": 2, "total_partial": 1, "total_indeterminate": 0}
        http = _Http({"validate-all-models": _Response(200, body)})

        validate_existing = await _capture_validate_existing(client, module, monkeypatch, http)

        assert await validate_existing(True) == body


class TestReconciliationRecordsTheFailure:
    """The user-visible half: what reconciliation logs is what the operator sees."""

    @pytest.mark.parametrize("dotted,class_name,provider_id", ENGINES)
    @pytest.mark.parametrize("status", [401, 500, 404])
    @pytest.mark.asyncio
    async def test_a_failed_call_is_never_reported_as_a_clean_sweep(
        self, dotted, class_name, provider_id, status, monkeypatch, worker_log
    ):
        module = __import__(dotted, fromlist=[class_name])
        client = getattr(module, class_name)(runtime_config={})
        http = _Http({"validate-all-models": _Response(status, {}, text="upstream said no")})

        validate_existing = await _capture_validate_existing(client, module, monkeypatch, http)
        await _run_step_zero(validate_existing, monkeypatch)

        messages = list(worker_log)
        assert not any(CLEAN_SWEEP in m for m in messages), (
            f"{dotted} reported '{CLEAN_SWEEP}' on an HTTP {status}: {messages}"
        )
        assert any(VALIDATION_FAILED in m for m in messages), (
            f"{dotted} failed the validation call without recording it: {messages}"
        )

    @pytest.mark.parametrize("dotted,class_name,provider_id", ENGINES)
    @pytest.mark.asyncio
    async def test_a_successful_clean_sweep_still_says_so(
        self, dotted, class_name, provider_id, monkeypatch, worker_log
    ):
        """The control, so the fix cannot be satisfied by failing every sweep."""
        module = __import__(dotted, fromlist=[class_name])
        client = getattr(module, class_name)(runtime_config={})
        http = _Http(
            {"validate-all-models": _Response(200, {"total_invalid": 0, "total_partial": 0})}
        )

        validate_existing = await _capture_validate_existing(client, module, monkeypatch, http)
        await _run_step_zero(validate_existing, monkeypatch)

        messages = list(worker_log)
        assert any(CLEAN_SWEEP in m for m in messages), messages
        assert not any(VALIDATION_FAILED in m for m in messages), messages


class TestNoEngineSubstitutesAnEmptyDictForAFailedCall:
    """Structural, by AST, so a fourth engine cannot reintroduce the shape.

    Matching a substring would be satisfied by the comment that documents the
    bug — which is what happened the first time this was attempted. The construct
    being banned is an `IfExp` whose test compares `.status_code` and whose
    body-or-else is an empty dict: that is the shape, however it is spelled.
    """

    FILES = (
        "image_worker/engines/beam/client.py",
        "image_worker/engines/remote_comfy/client.py",
        "image_worker/engines/modal/client.py",
    )

    def _status_gated_empty_dict(self, source):
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.IfExp):
                continue
            has_empty_dict = any(
                isinstance(branch, ast.Dict) and not branch.keys
                for branch in (node.body, node.orelse)
            )
            if has_empty_dict and "status_code" in ast.unparse(node.test):
                return ast.unparse(node.test)
        return None

    @pytest.mark.parametrize("relpath", FILES)
    def test_no_status_gated_empty_dict(self, relpath):
        root = pathlib.Path(__file__).resolve().parents[1]
        source = (root / relpath).read_text()

        offending = self._status_gated_empty_dict(source)
        assert offending is None, (
            f"{relpath} returns an empty dict when {offending!r}, and "
            f"reconciliation reads an empty dict as a clean sweep"
        )