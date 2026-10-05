"""The in-flight job status set is one set, and no module re-spells it.

`ACTIVE_JOB_STATUSES` was defined in `services/job_service.py` and transcribed
twice more: in `services/load_balancer.py` and in `JobService.update_job`. Both
copies omitted `RETRYING`.

The load balancer's copy is the one that costs something. It counts in-flight
jobs per provider to feed `least-connections`; a job in retry backoff is still
occupying its provider, so excluding it reported zero and let the balancer hand
that provider a second job while the first was running. `update_job`'s copy is
the same omission with a different symptom: `started_at` was never stamped for a
job entering `RETRYING`, so every duration derived from it was wrong for exactly
the jobs that had already failed once.

The guard is structural: it walks the AST of every module under `services/` and
`api/` and fails on any local assignment that lists job statuses inline.
"""

from __future__ import annotations

import ast
from pathlib import Path


from core.entities import ACTIVE_JOB_STATUSES, JobStatus, TERMINAL_JOB_STATUSES

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEARCH_ROOTS = ("services", "api")

# The set every inline transcription was missing.
REQUIRED_ACTIVE = {
    JobStatus.SENT_TO_PROVIDER,
    JobStatus.CONNECTED,
    JobStatus.PRE_GENERATION,
    JobStatus.GENERATING,
    JobStatus.POST_PROCESSING,
    JobStatus.RETRYING,
}


class TestTheSet:
    def test_retrying_is_in_the_shared_set(self):
        """The state most easily forgotten: nothing about the name suggests the
        worker is still holding the job."""
        assert JobStatus.RETRYING in ACTIVE_JOB_STATUSES
        assert set(ACTIVE_JOB_STATUSES) == REQUIRED_ACTIVE

    def test_every_non_queued_status_is_classified(self):
        unclassified = {
            status
            for status in JobStatus
            if status
            not in set(ACTIVE_JOB_STATUSES) | set(TERMINAL_JOB_STATUSES) | {JobStatus.PENDING}
        }
        assert not unclassified, (
            f"{sorted(s.value for s in unclassified)} is neither active, terminal "
            "nor pending; add it to one of the three sets in core.entities"
        )


def _inline_status_lists():
    """Every module-local literal that names three or more statuses inline.

    A literal is excused if the comment block directly above it declares a
    *narrower question* with the `NARROWER THAN` marker. That is the whole
    escape hatch, and it is deliberately not a hand-maintained filename list: a
    module that writes a second copy of the in-flight rule has to say in prose
    why its set is different, and the marker is what this looks for. Without
    the marker the copy fails; with it, a reviewer sees the reasoning next to
    the code instead of in a test file that has drifted from it.
    """
    for root in SEARCH_ROOTS:
        for path in sorted((BACKEND_ROOT / root).rglob("*.py")):
            source = path.read_text()
            try:
                tree = ast.parse(source)
            except SyntaxError:  # pragma: no cover
                continue
            lines = source.splitlines()
            for node in ast.walk(tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names = [t.id for t in targets if isinstance(t, ast.Name)]
                segment = ast.get_source_segment(source, node) or ""
                if segment.count("JobStatus.") < 3:
                    continue
                # Deriving from the shared tuples is the fix, not a violation.
                if "ACTIVE_JOB_STATUSES" in segment or "TERMINAL_JOB_STATUSES" in segment:
                    continue
                # The FSM transition table is a different kind of literal.
                if "JOB_STATUS_TRANSITIONS" in names:
                    continue
                preceding = "\n".join(lines[max(0, node.lineno - 8) : node.lineno])
                if "NARROWER THAN" in preceding:
                    continue
                yield path.relative_to(BACKEND_ROOT), node.lineno, names


INLINE_COPIES = list(_inline_status_lists())


class TestNoTranscription:
    def test_no_module_lists_three_or_more_statuses_inline(self):
        offenders = [
            f"{path}:{lineno} assigns {names} from an inline JobStatus list"
            for path, lineno, names in INLINE_COPIES
        ]
        assert not offenders, (
            "use ACTIVE_JOB_STATUSES / TERMINAL_JOB_STATUSES from core.entities "
            "instead. If your set answers a narrower question, say so in a "
            "comment directly above it containing the words NARROWER THAN:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_transition_table_is_not_a_transcription_in_disguise(self):
        """If the FSM table ever absorbs the in-flight set, this names it."""
        from services.job_service import JOB_STATUS_TRANSITIONS

        # Every active status must have an explicit entry: a status that can be
        # entered but has no outgoing rule is a job that can get stuck.
        missing = [s.value for s in ACTIVE_JOB_STATUSES if s not in JOB_STATUS_TRANSITIONS]
        assert not missing, f"no transition rule declared for {missing}"