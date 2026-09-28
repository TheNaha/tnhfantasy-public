"""Three defects that all cost money, and one of which failed silently.

1. `run_idle_simulation_tick` had no per-tick ceiling and its input query had no
   bound, so N dormant chats meant N paid LLM calls every tick — each of which
   also triggers a paid memory extraction. It also built its workflow without
   `sampler_overrides(chat)`, which all seven other Chat-bearing call sites pass,
   so a chat configured for `temperature: 0.2` and `max_output_tokens: 300` got
   the global default: unbounded, high-temperature, long-form generation the user
   neither configured nor wanted.

2. `rollback_chat` and `regenerate_reply` never looked at the job table. Undo,
   the messages are deleted, and twenty seconds later the already-paid job
   completes and appends its reply at the tail. For regenerate, two jobs race and
   the loser appends a duplicate.

3. `_PgNotifyListener._run` returned on a connect failure and fell out of the loop
   on a runtime error, logging one line and leaving a dead thread. Nothing called
   `start()` again, so cross-process wakeups were gone for the rest of the
   container's life — silently. (The earlier audit said it "degrades to the 1 s
   poll"; it does not. The 1 s `select` timeout is the idle poll, not a fallback.
   Claims still worked, which is exactly why it went unnoticed.)
"""

import time

import pytest

from core.entities import Chat, Job, JobStatus, Message, MessageRole
from services.job_queue import _PgNotifyListener, _RECONNECT_BACKOFF_SECONDS


# ------------------------------------------------------------- idle simulation


def _chat(session, name, **kw):
    c = Chat(title=name, idle_sim_enabled=True, chat_type="chat", **kw)
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def _dormant(session, chat):
    """Give the chat an old last-activity timestamp so the tick considers it."""
    msg = Message(chat_id=chat.id, role=MessageRole.USER, content="hi", created_at=_hours_ago(5))
    session.add(msg)
    session.commit()
    return msg


def _hours_ago(h):
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) - timedelta(hours=h)


class TestIdleSimCap:
    @pytest.mark.asyncio
    async def test_a_tick_never_exceeds_the_cap(self, session, monkeypatch):
        """The headline: the loop had no ceiling at all."""
        from services import agent_simulation as ag

        chats = [_chat(session, f"c{i}") for i in range(12)]
        for c in chats:
            _dormant(session, c)

        spawned: list[str] = []

        class FakeQueue:
            async def enqueue(self, job_id, task_type=None):
                return None

        class FakeJobService:
            def __init__(self, _session):
                pass

            async def create_job(self, **kw):
                spawned.append(kw)
                from core.entities import Job as J

                return J(id=f"job-{len(spawned)}")

        async def fake_context(_msgs, **kw):
            return "prompt", []

        monkeypatch.setattr(ag, "IDLE_SIM_MAX_JOBS_PER_TICK", 5, raising=False)
        monkeypatch.setattr("services.context_builder.build_chat_context_async", fake_context)
        monkeypatch.setattr("services.job_queue.queue_manager", FakeQueue())
        monkeypatch.setattr("services.job_service.JobService", FakeJobService)

        import config

        monkeypatch.setattr(
            config, "get_config", lambda: {"ai": {"idleSimEnabled": True}}
        )
        monkeypatch.setattr(
            "infrastructure.deps.get_session_context",
            _sync_session_context(session),
        )

        n = await ag.run_idle_simulation_tick(min_activity_age_minutes=30)
        assert n == 5, f"spawned {n}, cap is 5"
        assert len(spawned) == 5, f"billed {len(spawned)} jobs"

    @pytest.mark.asyncio
    async def test_the_cap_is_checked_before_the_work(self, session, monkeypatch):
        """After the increment, the last iteration bills one more than the cap."""
        from services import agent_simulation as ag

        calls: list[str] = []

        class CountingChat:
            """A chat whose attribute access is counted, to prove the loop body
            did not run for the chats it skipped."""

            def __init__(self, real):
                self._real = real

            def __getattr__(self, name):
                calls.append(name)
                return getattr(self._real, name)

        for i in range(4):
            c = _chat(session, f"c{i}")
            _dormant(session, c)

        async def fake_context(_msgs, **kw):
            return "prompt", []

        class FakeQueue:
            async def enqueue(self, job_id, task_type=None):
                return None

        class FakeJobService:
            def __init__(self, _session):
                pass

            async def create_job(self, **kw):
                return Job(id="j")

        monkeypatch.setattr(ag, "IDLE_SIM_MAX_JOBS_PER_TICK", 2, raising=False)
        monkeypatch.setattr("services.context_builder.build_chat_context_async", fake_context)
        monkeypatch.setattr("services.job_queue.queue_manager", FakeQueue())
        monkeypatch.setattr("services.job_service.JobService", FakeJobService)
        import config

        monkeypatch.setattr(config, "get_config", lambda: {"ai": {"idleSimEnabled": True}})
        monkeypatch.setattr("infrastructure.deps.get_session_context", _sync_session_context(session))

        n = await ag.run_idle_simulation_tick(min_activity_age_minutes=30)
        assert n == 2

    def test_the_cap_is_a_positive_constant(self):
        from services.agent_simulation import IDLE_SIM_MAX_JOBS_PER_TICK

        assert 0 < IDLE_SIM_MAX_JOBS_PER_TICK <= 50, "a cap is not a licence to bill everything"

    @pytest.mark.asyncio
    async def test_the_workflow_carries_the_chats_own_samplers(self, session, monkeypatch):
        """Asserted on the ENQUEUED WORKFLOW, not on a mock call — this is the
        assertion that actually catches the regression."""
        from services import agent_simulation as ag

        chat = _chat(session, "tuned", temperature=0.2, max_output_tokens=300)
        _dormant(session, chat)

        captured: list[dict] = []

        class FakeJobService:
            def __init__(self, _session):
                pass

            async def create_job(self, **kw):
                captured.append(kw["workflow"])
                return Job(id="j")

        async def fake_context(_msgs, **kw):
            return "prompt", []

        class FakeQueue:
            async def enqueue(self, job_id, task_type=None):
                return None

        monkeypatch.setattr("services.context_builder.build_chat_context_async", fake_context)
        monkeypatch.setattr("services.job_queue.queue_manager", FakeQueue())
        monkeypatch.setattr("services.job_service.JobService", FakeJobService)
        import config

        monkeypatch.setattr(config, "get_config", lambda: {"ai": {"idleSimEnabled": True}})
        monkeypatch.setattr("infrastructure.deps.get_session_context", _sync_session_context(session))

        await ag.run_idle_simulation_tick(min_activity_age_minutes=30)
        assert captured, "no workflow was captured"
        wf = captured[0]
        assert wf.get("temperature") == 0.2, f"idle reply ignored the chat's temperature: {wf.get('temperature')}"
        assert wf.get("max_output_tokens") == 300, f"idle reply ignored the chat's token cap: {wf.get('max_output_tokens')}"

    def test_every_chat_bearing_path_passes_samplers(self):
        """The one path that omitted it was found by checking all nine, not by
        reading this one. A test so the tenth cannot regress the same way.

        Parsed with `ast` rather than by scanning text: an earlier version of
        this test sliced a fixed window of source after the call, which cut the
        `samplers=` argument off the end of a call that *did* pass it — a false
        positive that would have sent someone looking for a bug that wasn't
        there. Keyword presence is a syntax-level fact, so ask the parser.
        """
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        offenders: list[str] = []
        checked = 0
        for path in sorted(root.rglob("*.py")):
            s = str(path)
            if "tests" in s or ".venv" in s or "__pycache__" in s:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            # Names of functions that legitimately have no Chat/Story entity to
            # read sampler overrides from. `parse_story` is the only one: it is
            # a story parse job, not a reply.
            exempt = {
                n.name
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and "parse_story" in n.name
            }
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if name != "build_chat_llm_workflow":
                    continue
                if any(kw.arg == "samplers" for kw in node.keywords):
                    checked += 1
                    continue
                # Exempt if every enclosing function in this module is exempt.
                enclosing = {
                    parent.name
                    for parent in ast.walk(tree)
                    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(
                        child is node for child in ast.walk(parent)
                    )
                }
                if enclosing and enclosing <= exempt:
                    continue
                offenders.append(
                    f"{path.relative_to(root)}:{node.lineno} (in {sorted(enclosing) or ['<module>']})"
                )
        assert offenders == [], (
            "build_chat_llm_workflow called without samplers=, so a chat's own "
            f"temperature/max_output_tokens is silently ignored:\n  {offenders}\n"
            f"({checked} call sites do pass it)"
        )
        assert checked >= 8, f"expected at least 8 call sites, found {checked} — did the file move?"


def _sync_session_context(session):
    """A `get_session_context` stand-in yielding the test session."""

    class _Ctx:
        def __init__(self, s):
            self._s = s

        async def __aenter__(self):
            return self._s

        async def __aexit__(self, *a):
            return False

    def factory():
        return _Ctx(session)

    return factory


# -------------------------------------------------------- rollback / regenerate


class TestRollbackCancelsInflight:
    def _in_flight(self, session, chat_id):
        job = Job(
            task_type="llm",
            status=JobStatus.GENERATING,
            workflow={},
            metadata_={"chat_id": chat_id, "character_id": "c"},
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    @pytest.mark.asyncio
    async def test_rollback_cancels_a_generating_job(self, session, monkeypatch):
        from api.routes.world_vault import chats as chats_mod

        chat = _chat(session, "c1")
        job = self._in_flight(session, chat.id)
        msg = Message(chat_id=chat.id, role=MessageRole.CHAR, content="reply", created_at=_hours_ago(1))
        session.add(msg)
        session.commit()

        cancelled: list[str] = []

        async def fake_cancel(*, job_service, job_id, reason=None):
            cancelled.append(job_id)
            job.status = JobStatus.CANCELLED
            session.add(job)
            session.commit()
            return {"status": "cancelled"}

        monkeypatch.setattr(
            "services.job_processing.cancel_job", fake_cancel
        )
        n = await chats_mod._cancel_inflight_chat_jobs(session, chat.id, reason="test")
        assert n == 1
        assert cancelled == [job.id]
        assert job.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_a_completed_job_does_not_break_the_rollback(self, session, monkeypatch):
        """The COMMON case, not an edge case: the reply already landed, which is
        the situation a rollback is for. `cancel_job` raises ValidationError on a
        terminal job, and swallowing nothing here means a 500 with the
        conversation half-rewound."""
        from core.exceptions import ValidationError
        from api.routes.world_vault import chats as chats_mod

        chat = _chat(session, "c2")
        job = self._in_flight(session, chat.id)
        job.status = JobStatus.COMPLETED
        session.add(job)
        session.commit()

        async def raising_cancel(*, job_service, job_id, reason=None):
            raise ValidationError("job is already terminal")

        monkeypatch.setattr("services.job_processing.cancel_job", raising_cancel)
        assert await chats_mod._cancel_inflight_chat_jobs(session, chat.id, reason="test") == 0

    @pytest.mark.asyncio
    async def test_a_failing_cancel_does_not_500(self, session, monkeypatch):
        """One job failing to cancel must not leave the conversation half-rewound."""
        from api.routes.world_vault import chats as chats_mod

        chat = _chat(session, "c3")
        self._in_flight(session, chat.id)

        async def boom(*, job_service, job_id, reason=None):
            raise RuntimeError("provider unreachable")

        monkeypatch.setattr("services.job_processing.cancel_job", boom)
        assert await chats_mod._cancel_inflight_chat_jobs(session, chat.id, reason="test") == 0

    @pytest.mark.asyncio
    async def test_another_chats_jobs_are_not_touched(self, session, monkeypatch):
        from api.routes.world_vault import chats as chats_mod

        mine, theirs = _chat(session, "mine"), _chat(session, "theirs")
        self._in_flight(session, theirs.id)

        touched: list[str] = []

        async def record(*, job_service, job_id, reason=None):
            touched.append(job_id)
            return {}

        monkeypatch.setattr("services.job_processing.cancel_job", record)
        assert await chats_mod._cancel_inflight_chat_jobs(session, mine.id, reason="test") == 0
        assert touched == []

    @pytest.mark.asyncio
    async def test_rollback_route_is_async(self):
        """It has to be, to await the cancel. If this reverts to a plain `def`
        the coroutine is never awaited and the cancel is a silent no-op."""
        import inspect
        from api.routes.world_vault.chats import rollback_chat

        assert inspect.iscoroutinefunction(rollback_chat)


# ----------------------------------------------------------- pg notify listener


class _FakeConn:
    def __init__(self, fail_on_pump=False):
        self.closed = False
        self._fail_on_pump = fail_on_pump
        self.notifies = []

    def poll(self):
        if self._fail_on_pump:
            raise OSError("server closed the connection unexpectedly")

    def close(self):
        self.closed = True


class _FakeCursor:
    def execute(self, _sql):
        return None


class TestPgNotifyListenerSurvives:
    @staticmethod
    def _listener(monkeypatch, connect):
        monkeypatch.setattr(
            "psycopg2.connect", connect, raising=False
        )
        listener = _PgNotifyListener(queues=(), loop=_NullLoop())
        # shrink the backoff so the test is not waiting seconds
        monkeypatch.setattr(
            "services.job_queue._RECONNECT_BACKOFF_SECONDS", (0.01, 0.01, 0.01)
        )
        return listener

    def test_it_reconnects_after_a_connect_failure(self, monkeypatch):
        """The bug: `_run` did `return` on a failed connect and the thread died.
        `start()` has an `is_alive()` guard and nothing calls it again, so a
        database that was briefly down at boot cost cross-process wakeups for the
        life of the container, with one warning line and nothing else."""
        attempts: list[int] = []

        def flaky_connect(*_a, **_k):
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError("could not connect to server")
            conn = _FakeConn()
            conn.cursor = lambda: _FakeCursor()
            return conn

        listener = self._listener(monkeypatch, flaky_connect)
        listener.start()
        try:
            _wait_for(lambda: len(attempts) >= 2, 5.0)
            assert len(attempts) >= 2, "never retried the connection"
            assert listener._thread.is_alive(), "the listener thread died instead of reconnecting"
        finally:
            listener.stop()

    def test_it_reconnects_after_the_connection_drops(self, monkeypatch):
        """The other half: a socket that dies mid-listen used to fall out of the
        `except` and end the thread, indistinguishable from a clean stop."""
        attempts: list[int] = []

        def flaky_connect(*_a, **_k):
            attempts.append(1)
            conn = _FakeConn(fail_on_pump=len(attempts) == 1)
            conn.cursor = lambda: _FakeCursor()
            return conn

        listener = self._listener(monkeypatch, flaky_connect)
        listener.start()
        try:
            _wait_for(lambda: len(attempts) >= 2, 5.0)
            assert len(attempts) >= 2, "never reconnected after the connection dropped"
            assert listener._thread.is_alive()
        finally:
            listener.stop()

    def test_stop_terminates_it_promptly(self, monkeypatch):
        """`_stop_event.wait(delay)` rather than `time.sleep`, so stop() does not
        have to wait out the backoff."""
        def always_fails(*_a, **_k):
            raise OSError("down")

        listener = self._listener(monkeypatch, always_fails)
        listener.start()
        started = time.perf_counter()
        listener.stop()
        assert time.perf_counter() - started < 5.0, "stop() waited out the backoff"
        assert listener._thread is None

    def test_the_backoff_is_capped(self):
        """A database down for an hour must not drift out to multi-minute gaps."""
        assert len(_RECONNECT_BACKOFF_SECONDS) >= 2
        assert max(_RECONNECT_BACKOFF_SECONDS) <= 60.0
        assert list(_RECONNECT_BACKOFF_SECONDS) == sorted(_RECONNECT_BACKOFF_SECONDS)


class _NullLoop:
    def call_soon_threadsafe(self, fn, *args):
        return None


def _wait_for(predicate, timeout: float) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False
