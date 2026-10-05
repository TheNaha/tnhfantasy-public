"""One definition of the asset SQL expressions, and no second transcription.

`services/statistics_service` and `services/session_detector` each held their own
copy of the resolved-completion-time expression and the checkpoint grouping key,
each with a comment saying the two had to stay identical — and no test asserting
that they did. A comment is not a constraint. If one side had been edited to
prefer `generated_at` over `job_completed_at`, the Statistics page would put an
image on one day and the Sessions panel would put it on another, and no test
would notice.

The guard is structural rather than behavioural: it walks the compiled SQL of
both expressions and asserts the two consumers reference the *same object*, so a
third transcription cannot be introduced without this failing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.asset_sql import CHECKPOINT_KEY, RESOLVED_TS
from services import session_detector, statistics_service

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _compiled(expr) -> str:
    return str(expr.compile(compile_kwargs={"literal_binds": True}))


class TestOneDefinition:
    def test_both_consumers_use_the_shared_expression_objects(self):
        assert session_detector.RESOLVED_TS is RESOLVED_TS
        assert session_detector.CHECKPOINT_KEY is CHECKPOINT_KEY
        # The statistics module keeps its private names for its many internal
        # references, but they must be the same objects, not copies.
        assert statistics_service._RESOLVED_TS is RESOLVED_TS
        assert statistics_service._CHECKPOINT is CHECKPOINT_KEY

    def test_the_resolved_timestamp_prefers_the_job_completion_time(self):
        sql = _compiled(RESOLVED_TS)
        assert "job_completed_at" in sql
        assert "generated_at" in sql
        assert "created_at" in sql
        # COALESCE order is the whole point: a row whose job has a completion
        # time must bucket by that instant, not by when the row was written.
        assert sql.index("job_completed_at") < sql.index("generated_at")
        assert sql.index("generated_at") < sql.index("created_at")

    def test_the_checkpoint_key_prefers_the_rollup_column(self):
        sql = _compiled(CHECKPOINT_KEY)
        assert "checkpoint_name" in sql
        assert sql.index("checkpoint_name") < sql.index("metadata_")


class TestNoSecondTranscription:
    """A guard that cannot see the code is not a guard.

    The point of `core.asset_sql` is that there is nowhere else to write these.
    This walks both service modules' ASTs and fails on any local assignment that
    rebuilds either expression — which is exactly how both copies got there.
    """

    @pytest.mark.parametrize(
        "module_path",
        [
            "services/statistics_service.py",
            "services/session_detector.py",
            "services/asset_reconciler.py",
            "api/routes/files.py",
        ],
    )
    def test_no_module_rebuilds_the_expressions(self, module_path):
        source = (BACKEND_ROOT / module_path).read_text()
        tree = ast.parse(source)
        offenders: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if not names:
                continue
            # An alias is fine — that is what `statistics_service` does.
            if all(name in {"_RESOLVED_TS", "RESOLVED_TS", "_CHECKPOINT", "CHECKPOINT_KEY"} for name in names):
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "job_completed_at" in segment and "generated_at" in segment:
                offenders.append(f"{module_path}:{node.lineno} rebuilds the resolved timestamp")
            if "checkpoint_name" in segment and "metadata_" in segment:
                offenders.append(f"{module_path}:{node.lineno} rebuilds the checkpoint key")

        assert not offenders, (
            "these expressions are defined in core/asset_sql.py; import them "
            "instead of writing a second copy:\n  " + "\n  ".join(offenders)
        )