"""Error-path regressions in the deployables (audit-2026-10-30c, FP-1/FP-6).

These are AST/source checks on purpose: the deployable modules import
`beta9`/`modal` and cannot be imported inside the backend container, and
`test_deployable_contract.py` pins names and route paths but not behaviour.

FP-1: `_reject` in `deployables/beam/llm_tts_app.py` was a SYNC def whose
body called the async `websocket.send_text` without awaiting it. Every call
site does `await _reject(...)`, so the discarded coroutine made that
`await None` → TypeError: no `{"event":"failed"}` frame was ever delivered on
any error path (auth, cold-start retryable, upstream failure), and the
backend's receive loop — which waits for `completed|failed|cancelled` — lost
the retryable signal.

FP-6: `deployables/modal/tts/modal_app.py` built its `comfy launch` argv as
`--port <p> --cpu 0.0.0.0 --port <p>` in CPU mode: `--cpu` is a flag, so
`0.0.0.0` became an unexpected positional (argparse error → ComfyUI never
starts) and `--listen` was never passed. The sibling launch sites use
`--listen 0.0.0.0 --port <p>` with `--cpu` appended last.
"""
from __future__ import annotations

import ast
from pathlib import Path

from repo_paths import require_repo_root

ROOT = require_repo_root("deployables/beam/llm_tts_app.py")
BEAM_LLM_TTS = ROOT / "deployables/beam/llm_tts_app.py"
MODAL_TTS = ROOT / "deployables/modal/tts/modal_app.py"


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"))


def _function(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parent: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    return parent


class TestBeamRejectFrameIsAwaited:
    def test_reject_is_a_coroutine(self):
        tree = _parse(BEAM_LLM_TTS)
        reject = _function(tree, "_reject")
        assert isinstance(reject, ast.AsyncFunctionDef), (
            "_reject must be async: as a sync def its send_text coroutine was "
            "discarded and every `await _reject(...)` raised TypeError, so no "
            "error frame was ever delivered"
        )

    def test_reject_awaits_the_send(self):
        tree = _parse(BEAM_LLM_TTS)
        reject = _function(tree, "_reject")
        awaits = [n for n in ast.walk(reject) if isinstance(n, ast.Await)]
        assert awaits, "_reject never awaits the websocket send"
        sent = [
            n for n in ast.walk(reject)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "send_text"
        ]
        assert sent, "_reject does not call websocket.send_text"

    def test_every_call_site_awaits_reject(self):
        tree = _parse(BEAM_LLM_TTS)
        parent = _parent_map(tree)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_reject"
        ]
        assert len(calls) >= 10, (
            f"only {len(calls)} _reject call sites found; the error paths "
            "moved — re-audit them"
        )
        unawaited = [
            node.lineno for node in calls
            if not isinstance(parent.get(node), ast.Await)
        ]
        assert not unawaited, (
            f"_reject called without await at lines {unawaited}; the frame "
            "would be built and dropped"
        )


class TestModalTtsLaunchArgv:
    def test_cpu_mode_keeps_listen_and_has_no_positional(self):
        source = MODAL_TTS.read_text(encoding="utf-8")
        tree = ast.parse(source)

        launches = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "Popen"
        ]
        assert launches, "comfy launch Popen call not found"
        # The argv is a list expression (+ conditional) inside the Popen call.
        joined = ast.unparse(launches[0])
        assert '"--listen"' in joined or "'--listen'" in joined, (
            "the launch argv no longer passes --listen; CPU mode used to drop "
            "it and hand 0.0.0.0 to --cpu as a positional (argparse error)"
        )
        assert '"--cpu" if GPU_TYPE == "cpu" else "--listen"' not in joined, (
            "the malformed conditional argv is back: --cpu is a flag, so "
            "`--cpu 0.0.0.0` errors and ComfyUI never starts"
        )