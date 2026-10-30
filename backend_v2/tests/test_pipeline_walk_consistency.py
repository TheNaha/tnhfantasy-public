"""The two chat-pipeline walks must stay in step (audit-2026-10-30b, m3).

`services.pipeline_runner.run_from` (the request path, walked from `triage`
in `_send_message`) and `services.job_processing._run_pipeline_stages_isolated`
(the post-turn path walked from `audit` after an LLM job completes)
deliberately duplicate the same manifest walk with different error isolation:
the request path propagates a stage failure, the post-turn path isolates each
stage so one broken stage cannot delete the rest of an already-paid-for turn.

The duplication is intentional; the DIVERGENCE is not. If one walk is edited
without the other — the `halt` check, the `user`-stage break, the
`next_stages` iteration — the manifest stops being the single source of truth
and the two paths run different pipelines. This test pins the shared control
flow and the docstrings' cross-references so neither can drift silently.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]

#: The control-flow facts both walks must contain, verbatim in source.
#: These are not incidental words: each one is a semantic decision
#: (stop-on-halt, stop-before-user, iterate the manifest's declared order,
#: invoke the stage executor).
SHARED_MARKERS = (
    'stage(start_key).next_stages',
    'ctx.get("halt")',
    "USER_STAGE",
    "run_stage(",
)

WALKS = (
    ("services/pipeline_runner.py", "run_from"),
    ("services/job_processing.py", "_run_pipeline_stages_isolated"),
)


def _function_source(rel: str, name: str) -> str:
    path = SRC / rel
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            segment = ast.get_source_segment(path.read_text(encoding="utf-8"), node)
            assert segment, f"could not read source of {rel}:{name}"
            return segment
    raise AssertionError(f"{rel} no longer defines {name} — the walk moved; re-audit both paths")


class TestBothWalksShareControlFlow:
    def test_every_shared_marker_appears_in_both_walks(self):
        sources = {rel: _function_source(rel, name) for rel, name in WALKS}
        for rel, source in sources.items():
            for marker in SHARED_MARKERS:
                assert marker in source, (
                    f"{rel} lost `{marker}` — one of the two pipeline walks no "
                    "longer shares the other's halt/user/order semantics; if "
                    "the change is intentional, update BOTH walks and this test"
                )

    def test_walks_cross_reference_each_other(self):
        """The docstrings must keep pointing the next reader at the twin."""
        runner = _function_source("services/pipeline_runner.py", "run_from")
        job = _function_source("services/job_processing.py", "_run_pipeline_stages_isolated")
        assert "_run_pipeline_stages_isolated" in runner, (
            "run_from's docstring no longer names the post-turn twin; a reader "
            "editing one walk would not learn the other exists"
        )
        assert "pipeline_runner" in job, (
            "_run_pipeline_stages_isolated's docstring no longer names run_from"
        )