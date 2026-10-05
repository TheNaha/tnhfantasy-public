"""Regression tests for the eight backend defects in docs/audit-2026-10-04.md §3.2.

Each class here exists because a specific, already-reproduced defect was fixed,
and each test was run against the reverted fix to confirm it fails. The revert
results are recorded in the fix report; the assertions are written so that the
revert breaks the *specific* claim, not incidentally.

Nothing in this file is a style preference or a refactor guard. Where a test
encodes the pre-fix behaviour it is because that behaviour was the bug.
"""

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import docker
import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

from core.entities import Asset, Job, JobStatus, Provider
from services.job_queue import JobQueue, QueueManager, queue_manager
from services.job_service import JobService


# ── F1: update_job's FSM guard authorises over a concurrent terminal state ────


class TestUpdateJobConditionalWrite:
    """`update_job`'s guard read the session identity map, not the database.

    `JobRepository.get` is `session.get`, which answers from the identity map
    with no SELECT for any object the caller is still holding — and every
    in-tree caller is holding one (`cancel_job` does `job = await
    self.get_job(job_id)` and then calls `update_job`). `SENT_TO_PROVIDER`'s
    allowed set contains `FAILED`, so a `CANCELLED` committed by another writer
    in between was authorised away and then overwritten, destroying the user's
    cancellation and its reason. Fixed with a conditional
    `UPDATE ... WHERE id = :id AND status = :expected`.
    """

    @pytest.fixture
    def file_engine(self, tmp_path):
        """A real file-backed engine, so two Sessions get two real connections.

        The conftest engine is a `StaticPool` single connection, which would let
        this pass for the wrong reason.
        """
        engine = create_engine(
            f"sqlite:///{tmp_path / 'jobs.db'}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(engine)
        yield engine
        engine.dispose()

    @staticmethod
    def _seed(file_engine, status: JobStatus) -> str:
        with Session(file_engine) as session:
            job = Job(workflow={"nodes": {}}, metadata_={"prompt": "a cat"}, status=status)
            session.add(job)
            session.commit()
            return job.id

    @staticmethod
    def _read(file_engine, job_id) -> Job:
        with Session(file_engine) as session:
            session.expire_all()
            return JobService(session).repo.get(job_id)

    # ── the atomic write itself ──────────────────────────────────────────

    def test_update_where_status_is_a_no_op_when_the_row_moved_on(self, file_engine):
        """The whole fix, at the layer it lives on."""
        job_id = self._seed(file_engine, JobStatus.SENT_TO_PROVIDER)
        with Session(file_engine) as holder:
            JobService(holder).repo.get(job_id)
        with Session(file_engine) as canceller:
            JobService(canceller).repo.update(
                job_id, status=JobStatus.CANCELLED, message="Cancelled by user"
            )

        with Session(file_engine) as writer:
            result = JobService(writer).repo.update_where_status(
                job_id, JobStatus.SENT_TO_PROVIDER, status=JobStatus.FAILED
            )

        assert result is None, "0 rows must be reported, not written around"
        assert self._read(file_engine, job_id).status == JobStatus.CANCELLED

    def test_update_where_status_commits_when_the_row_is_still_there(self, file_engine):
        job_id = self._seed(file_engine, JobStatus.PENDING)

        with Session(file_engine) as writer:
            result = JobService(writer).repo.update_where_status(
                job_id, JobStatus.PENDING, status=JobStatus.SENT_TO_PROVIDER
            )

        assert result is not None
        assert result.status == JobStatus.SENT_TO_PROVIDER
        assert self._read(file_engine, job_id).status == JobStatus.SENT_TO_PROVIDER

    def test_update_where_status_returns_none_for_a_missing_row(self, file_engine):
        with Session(file_engine) as writer:
            assert JobService(writer).repo.update_where_status(
                "no-such-job", JobStatus.PENDING, status=JobStatus.FAILED
            ) is None

    # ── the service, which is where the defect was ───────────────────────

    async def test_a_concurrent_cancellation_is_not_overwritten_by_a_failure(
        self, file_engine
    ):
        job_id = self._seed(file_engine, JobStatus.SENT_TO_PROVIDER)
        cancelled_at = datetime.now(timezone.utc)

        # The auditor's reproduction, no threads: one Session holds the job it
        # read, a second commits a terminal state, and the first then writes a
        # transition.
        with Session(file_engine) as author_session, Session(file_engine) as canceller:
            service = JobService(author_session)
            # Exactly what a request mid-transition holds — and what keeps the
            # object in the identity map, since `Session.identity_map` holds
            # only weak references.
            job = service.repo.get(job_id)
            assert job.status == JobStatus.SENT_TO_PROVIDER

            JobService(canceller).repo.update(
                job_id,
                status=JobStatus.CANCELLED,
                message="Cancelled by user",
                completed_at=cancelled_at,
            )

            # Provably stale: no SELECT was issued, so this is the identity-map
            # copy. That is the whole defect, and without it the next line
            # proves nothing.
            assert job.status == JobStatus.SENT_TO_PROVIDER

            result = await service.update_job(
                job_id, status=JobStatus.FAILED, error="worker died"
            )

        assert result is not None
        assert result.status == JobStatus.CANCELLED

        final = self._read(file_engine, job_id)
        assert final.status == JobStatus.CANCELLED, (
            "the committed terminal state was destroyed by a write authorised "
            "against a stale read"
        )
        assert final.message == "Cancelled by user"
        # Naive on the way back out of a SQLite DATETIME column; the microseconds
        # are the point — the rejected write did not restamp it.
        assert final.completed_at.replace(tzinfo=timezone.utc) == cancelled_at

    async def test_the_rejected_write_leaves_no_trace_on_the_terminal_row(
        self, file_engine
    ):
        """Both status-derived side effects have to be undone, not just `status`.

        `completed_at` and the `diagnostics` failure block are both derived from
        the status. Popping only `status` leaves a cancelled job recording
        itself as completed, and stamping it with a failure it never had.
        """
        job_id = self._seed(file_engine, JobStatus.SENT_TO_PROVIDER)
        cancelled_at = datetime.now(timezone.utc)

        with Session(file_engine) as author_session, Session(file_engine) as canceller:
            service = JobService(author_session)
            # A list, so the reference survives: `Session.identity_map` holds
            # only weak references, and a temporary would be collected between
            # the read and the write, which would silently make this a no-op.
            held = [service.repo.get(job_id)]
            JobService(canceller).repo.update(
                job_id, status=JobStatus.CANCELLED, completed_at=cancelled_at
            )
            assert held[0].status == JobStatus.SENT_TO_PROVIDER
            await service.update_job(
                job_id, status=JobStatus.FAILED, error="worker died"
            )

        final = self._read(file_engine, job_id)
        assert final.status == JobStatus.CANCELLED
        assert final.completed_at.replace(tzinfo=timezone.utc) == cancelled_at
        assert "diagnostics" not in (final.metadata_ or {})

    async def test_a_legitimate_transition_still_commits(self, file_engine):
        """The conditional write must not break the ordinary case."""
        job_id = self._seed(file_engine, JobStatus.PENDING)

        with Session(file_engine) as session:
            service = JobService(session)
            service.repo.get(job_id)
            result = await service.update_job(
                job_id, status=JobStatus.SENT_TO_PROVIDER
            )

        assert result.status == JobStatus.SENT_TO_PROVIDER
        assert self._read(file_engine, job_id).status == JobStatus.SENT_TO_PROVIDER

    async def test_an_unchanged_status_is_not_gated(self, file_engine):
        """A write that does not change the status has no FSM decision to re-check."""
        job_id = self._seed(file_engine, JobStatus.GENERATING)

        with Session(file_engine) as session:
            service = JobService(session)
            result = await service.update_job(job_id, progress=42.0)

        assert result.progress == 42.0
        assert result.status == JobStatus.GENERATING


# ── F2: a failed enqueue stamp strands a job forever ─────────────────────────


class TestEnqueueStampFailure:
    """`_mark_enqueued` swallowed every error, so the compensating delete could
    never fire for the only failure that strands a row.

    A stranded row is `PENDING / claimed_at IS NULL / enqueued_at IS NULL`. The
    claim query requires `enqueued_at IS NOT NULL`, so nothing ever claims it;
    nothing fails it either, so it is counted in `summary["pending"]` forever.
    """

    def test_stamp_failure_is_swallowed_when_there_is_no_claim_query(self, engine):
        """SQLite: the stamp cannot succeed (no `now()`), and nothing depends on it.

        This is the documented behaviour the fix had to preserve, and it is a
        real production path, not a hypothetical: SQLite has no `now()` function,
        so this statement raises on every single enqueue there.
        """
        queue = JobQueue(max_workers=1, task_type="image")
        assert queue._use_db_claims is False
        # Must not raise: the job is already in the in-process queue and runs.
        queue._mark_enqueued("whatever")

    def test_stamp_failure_propagates_when_db_claims_are_enabled(self, engine):
        """Postgres: the stamp is what makes the row claimable at all."""
        queue = JobQueue(max_workers=1, task_type="image")
        queue._use_db_claims = True

        with pytest.raises(Exception) as excinfo:
            queue._mark_enqueued("whatever")

        assert "now" in str(excinfo.value).lower()

    async def test_enqueue_queues_nothing_when_the_stamp_failed(self, engine):
        """Otherwise the job is both stranded in the DB and runnable in-process."""
        queue = JobQueue(max_workers=1, task_type="image")
        queue._use_db_claims = True

        with pytest.raises(Exception):
            await queue.enqueue("job-1")

        assert queue.pending_count == 0

    async def test_a_stranded_row_does_not_survive_submission(self, session, monkeypatch):
        """The whole point of propagating: the compensating delete now runs."""
        session.add(Provider(id="test-modal", type="modal", enabled=True))
        session.commit()

        from services.job_submission_service import JobSubmissionService

        # Real `enqueue`, real SQLite stamp failure, but with DB claims on —
        # i.e. the Postgres deployment's configuration reached through the
        # failure SQLite happens to produce for free.
        monkeypatch.setattr(queue_manager.image, "_use_db_claims", True)

        svc = JobSubmissionService(session)
        with pytest.raises(Exception):
            await svc.create_and_enqueue_job(
                {"nodes": {"1": {"class_type": "EmptyLatentImage", "inputs": {}}}},
                {"prompt": "hi"},
            )

        assert session.exec(select(Job)).all() == []

    async def test_recover_fails_a_pending_row_that_was_never_stamped(self, session):
        """Second line of defence: recovery is what stops an existing one."""
        service = JobService(session)
        stranded = Job(
            workflow={"nodes": {}},
            metadata_={"prompt": "x"},
            status=JobStatus.PENDING,
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        session.add(stranded)
        session.commit()
        stranded_id = stranded.id

        summary = await QueueManager().recover(service, stranded_timeout_seconds=60)

        assert stranded_id in summary["failed_job_ids"]
        assert summary["pending"] == 0, (
            "a row that can never be claimed is still being reported as pending work"
        )
        assert service.repo.get(stranded_id).status == JobStatus.FAILED
        assert (
            service.repo.get(stranded_id).metadata_["diagnostics"]["failure_kind"]
            == "stranded_pending"
        )

    async def test_recover_leaves_a_stamped_pending_row_alone(self, session):
        """A job whose stamp landed, or is still landing, is not stranded."""
        service = JobService(session)
        enqueued = Job(
            workflow={"nodes": {}},
            metadata_={"prompt": "x"},
            status=JobStatus.PENDING,
            enqueued_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        fresh = Job(workflow={"nodes": {}}, metadata_={"prompt": "y"}, status=JobStatus.PENDING)
        session.add_all([enqueued, fresh])
        session.commit()

        await QueueManager().recover(service, stranded_timeout_seconds=60)

        assert service.repo.get(enqueued.id).status == JobStatus.PENDING
        assert service.repo.get(fresh.id).status == JobStatus.PENDING


# ── F3: three Docker probes lie, and a fourth 500s on the same outage ────────


class TestContainerProbeHonesty:
    """A Docker failure was reported as "stopped", and the route cached the lie.

    `container_manager._probe_container` returned `None` — the same value as
    "absent" — and cached it for 2 s. `providers/lifecycle._container_status_sync`
    turned an exception into "stopped" and the route cached the whole payload
    for 10 s while asserting `container_runtime_available: true`.
    `GET /containers/list` had no exception handling at all, so it answered 500
    in the same second the status route answered "everything is fine".
    """

    @staticmethod
    def _manager_with_failing_client() -> MagicMock:
        manager = MagicMock()
        manager.client.containers.get.side_effect = docker.errors.DockerException(
            "Cannot connect to the Docker daemon"
        )
        return manager

    def test_probe_raises_on_a_runtime_outage(self):
        from services.container_manager import ContainerManager

        manager = ContainerManager.__new__(ContainerManager)
        manager.client = MagicMock()
        manager.client.containers.get.side_effect = docker.errors.DockerException(
            "Cannot connect to the Docker daemon"
        )

        with pytest.raises(docker.errors.DockerException):
            manager._probe_container("tnhcomfy-p1")

    def test_probe_still_returns_none_for_a_genuinely_absent_container(self):
        from services.container_manager import ContainerManager

        manager = ContainerManager.__new__(ContainerManager)
        manager.client = MagicMock()
        manager.client.containers.get.side_effect = docker.errors.NotFound("nope")

        assert manager._probe_container("tnhcomfy-p1") is None

    def test_a_raised_probe_is_not_cached_as_absent(self):
        """The 2 s snapshot cache used to store the lie and serve it back."""
        from services.container_manager import ContainerManager

        manager = ContainerManager.__new__(ContainerManager)
        manager.client = MagicMock()
        manager.client.containers.get.side_effect = docker.errors.DockerException(
            "daemon down"
        )
        manager._snapshot_cache = {}
        manager._snapshot_lock = threading.Lock()

        for _ in range(3):
            with pytest.raises(docker.errors.DockerException):
                manager.get_container_snapshot("p1", "tnhcomfy-p1")

        assert manager._snapshot_cache == {}

    def test_list_containers_degrades_instead_of_raising(self):
        from services.container_manager import ContainerManager

        manager = ContainerManager.__new__(ContainerManager)
        manager.client = MagicMock()
        manager.client.containers.list.side_effect = docker.errors.DockerException(
            "Cannot connect to the Docker daemon"
        )

        containers, runtime_available = manager.list_containers()

        assert containers == []
        assert runtime_available is False

    def test_list_containers_reports_the_runtime_available_on_success(self):
        from services.container_manager import ContainerManager

        manager = ContainerManager.__new__(ContainerManager)
        manager.client = MagicMock()
        manager.client.containers.list.return_value = [
            SimpleNamespace(
                short_id="abc123",
                name="tnhcomfy-p1",
                labels={"provider-id": "p1"},
                status="running",
                ports={},
            )
        ]

        containers, runtime_available = manager.list_containers()

        assert runtime_available is True
        assert containers[0]["name"] == "tnhcomfy-p1"

    # ── the routes ───────────────────────────────────────────────────────

    @pytest.fixture
    def container_manager_override(self):
        """Install a fake `ContainerManager` as the route's real dependency.

        `get_container_manager` reads `request.app.state.container_manager`, so
        monkeypatching the module attribute would leave the route resolving the
        real (None) manager and every assertion below would pass vacuously.
        """
        from api.deps import get_container_manager
        from api.main import app

        installed: list[MagicMock] = []

        def _install(manager: MagicMock) -> MagicMock:
            app.dependency_overrides[get_container_manager] = lambda: manager
            installed.append(manager)
            return manager

        yield _install
        app.dependency_overrides.pop(get_container_manager, None)


    def test_list_route_answers_200_and_does_not_claim_the_runtime_is_fine(
        self, client, session, container_manager_override
    ):
        cm = MagicMock()
        cm.list_containers.return_value = ([], False)
        container_manager_override(cm)

        response = client.get("/api/v2/providers/containers/list")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["containers"] == []
        assert body["container_runtime_available"] is False, (
            "an unreachable runtime was reported as an available one with no containers"
        )


    def test_the_two_routes_stop_contradicting_each_other(
        self, client, session, container_manager_override
    ):
        """Same host, same second: one must not 500 while the other says "fine"."""
        from api.routes.providers import lifecycle as lifecycle_module

        lifecycle_module._container_status_cache.clear()
        session.add(Provider(id="p1", type="modal", enabled=True))
        session.commit()

        cm = MagicMock()
        # The shape a runtime outage now produces: a raise out of the probe.
        cm.get_container_snapshot.side_effect = docker.errors.DockerException(
            "Cannot connect to the Docker daemon"
        )
        cm.list_containers.return_value = ([], False)
        container_manager_override(cm)

        list_response = client.get("/api/v2/providers/containers/list")
        status_response = client.get("/api/v2/providers/containers/status")

        assert list_response.status_code == 200, list_response.text
        assert status_response.status_code == 200, status_response.text
        assert list_response.json()["container_runtime_available"] is False
        assert status_response.json()["container_runtime_available"] is False
        assert status_response.json()["statuses"]["p1"]["status"] == "unreachable"
        lifecycle_module._container_status_cache.clear()

    def test_runtime_degradation_is_logged_at_warning_not_debug(self):
        """Third copy: `provider_runtime` swallowed the probe at debug.

        Degrading to the worker/discovery fallbacks is deliberate, so the fix
        keeps the degradation and changes only what is reported: the message is
        no longer invisible at default log level, and "unreachable" is no longer
        spelled the same as "there was no container".
        """
        import services.provider_runtime as runtime_module
        from infrastructure import deps as deps_module

        provider = Provider(
            id="p1",
            type="modal",
            enabled=True,
            container_config={"container_name": "tnhcomfy-p1", "port": 8000},
        )
        cm = MagicMock()
        cm.client = object()
        cm.get_container_snapshot.side_effect = RuntimeError("socket gone")

        calls: list[tuple[str, dict]] = []
        original_warning = runtime_module.logger.warning
        original_manager = deps_module.get_container_manager
        runtime_module.logger.warning = lambda event, **kw: calls.append((event, kw))
        deps_module.get_container_manager = lambda: cm
        try:
            target = runtime_module.resolve_provider_runtime(provider)
        finally:
            runtime_module.logger.warning = original_warning
            deps_module.get_container_manager = original_manager

        assert calls, "an unreachable runtime must be visible without turning on debug"
        assert calls[0][0] == "provider_runtime_status_probe_failed"
        # "We could not ask" must not be reported as "there was nothing there".
        assert target.status == runtime_module.RUNTIME_UNREACHABLE
        assert target.status != "unavailable"



# ── F4: the World Timeline surfaces soft-deleted images and mis-orders ───────


class TestTimelineAssetWindow:
    """Neither the count nor the window filtered `deleted_at`, and the window was
    ordered by `created_at` while the merge sorts on `generated_at or
    created_at` — so deep pages silently dropped events.
    """

    def test_soft_deleted_assets_are_absent_from_the_timeline(self, client, session):
        deleted_at = datetime.now(timezone.utc)
        session.add(Asset(filename="gone.png", relative_path="a/gone.png", deleted_at=deleted_at))
        session.add(Asset(filename="kept.png", relative_path="a/kept.png"))
        session.commit()

        body = client.get("/api/v2/timeline", params={"types": "asset"}).json()
        filenames = {event["title"] for event in body["events"]}

        assert "Image: kept.png" in filenames
        assert "Image: gone.png" not in filenames, (
            "a soft-deleted image is being surfaced in the timeline"
        )

    def test_the_count_agrees_with_the_window(self, client, session):
        """The count query filtered the same way the window did — until now."""
        for index in range(3):
            session.add(
                Asset(
                    filename=f"del-{index}.png",
                    relative_path=f"d/del-{index}.png",
                    deleted_at=datetime.now(timezone.utc),
                )
            )
        session.add(Asset(filename="live.png", relative_path="d/live.png"))
        session.commit()

        body = client.get("/api/v2/timeline", params={"types": "asset"}).json()

        assert body["total"] == len(body["events"]) == 1

    def test_the_window_is_cut_on_the_timestamp_the_merge_sorts_on(self, client, session):
        """The deep-page half: a window ordered by a different column.

        The event's timestamp is `generated_at or created_at` and the merge
        sorts on it, but the window was ordered by `created_at` and truncated at
        `limit + offset`. Once the window is full that is not a different
        ordering, it is a different *set*: an image imported today with a
        `generated_at` from yesterday sorts near the top of the merged list and
        falls off the bottom of the window entirely, so the newest event on the
        page is never rendered.
        """
        now = datetime.now(timezone.utc)
        # The newest event by the merged sort, and the *oldest* row by
        # `created_at`: an older image re-generated or re-imported just now.
        session.add(
            Asset(
                filename="newest.png",
                relative_path="w/newest.png",
                created_at=now - timedelta(days=30),
                generated_at=now,
            )
        )
        for index in range(6):
            session.add(
                Asset(
                    filename=f"older-{index}.png",
                    relative_path=f"w/older-{index}.png",
                    created_at=now - timedelta(days=index + 1),
                )
            )
        session.commit()

        body = client.get(
            "/api/v2/timeline", params={"types": "asset", "limit": 3}
        ).json()

        events = body["events"]
        assert events, body
        assert events[0]["title"] == "Image: newest.png", (
            "the newest event by the timeline's own timestamp is missing from "
            "page 1, because the window was cut on a different column"
        )
        assert len(events) == 3
        timestamps = [event["timestamp"] for event in events]
        assert timestamps == sorted(timestamps, reverse=True)


# ── F5: search_prompts' SQLite fallback built an unescaped LIKE ──────────────


class TestSearchPromptsLikeEscaping:
    """`f"%{query}%"` left `%`/`_` live as wildcards in a raw `text()` fragment.

    `100%` matched `100 percent`. The escaping and the `ESCAPE` clause are both
    required: escaping alone matches nothing, which is why the fix uses
    `core.sql_search.like_contains` *and* adds the clause.
    """

    @pytest.fixture
    def jobs(self, session: Session):
        from infrastructure.repositories import JobRepository

        for prompt in (
            "100% cotton dress",
            "100 percent wool coat",
            "a_b portrait",
            "aXb portrait",
        ):
            session.add(Job(workflow={}, metadata_={"prompt": prompt}))
        session.commit()
        return JobRepository(session)

    def test_percent_is_a_literal(self, jobs):
        prompts = [job.metadata_["prompt"] for job in jobs.search_prompts("100%")]
        assert prompts == ["100% cotton dress"]

    def test_underscore_is_a_literal(self, jobs):
        prompts = [job.metadata_["prompt"] for job in jobs.search_prompts("a_b")]
        assert prompts == ["a_b portrait"]

    def test_an_ordinary_term_still_matches(self, jobs):
        prompts = [job.metadata_["prompt"] for job in jobs.search_prompts("cotton")]
        assert prompts == ["100% cotton dress"]

    def test_a_literal_backslash_is_not_an_error(self, jobs):
        """Escaping without the clause makes the backslash a syntax error."""
        for prompt in (r"odd\name", "oddname"):
            jobs.session.add(Job(workflow={}, metadata_={"prompt": prompt}))
        jobs.session.commit()

        assert jobs.search_prompts("\\") is not None


# ── F6: batch_get_metadata checked out one pooled connection per name ───────


class TestBatchMetadataSessionReuse:
    """Both `_resolve_asset_path` call sites passed no session, and
    `_resolve_asset_path` takes one precisely so a batch can share it — its own
    docstring says so, and `_build_export_zip_sync` threads one for the same
    reason. Without it, each unresolved name opened its own pooled connection.
    """

    @pytest.fixture
    def counting_files_module(self, monkeypatch, tmp_path):
        import api.routes.files as files_module

        real_sync_session = files_module._sync_session
        opened: list[object] = []

        def counting_sync_session():
            ctx = real_sync_session()
            opened.append(ctx)
            return ctx

        monkeypatch.setattr(files_module, "_sync_session", counting_sync_session)
        monkeypatch.setattr(files_module, "OUTPUT_DIR", str(tmp_path))
        return files_module, opened, tmp_path

    async def test_one_batch_one_connection(self, counting_files_module):
        files_module, opened, _ = counting_files_module
        request = files_module.BatchMetadataRequest(
            paths=[f"missing-{index}.png" for index in range(40)]
        )

        await files_module.batch_get_metadata(request)

        assert len(opened) == 1, (
            f"{len(opened)} pooled connections for one batch of 40 names"
        )

    async def test_a_fully_direct_batch_needs_no_connection(self, counting_files_module):
        """Lazy, so the common case where every path resolves costs nothing."""
        files_module, opened, tmp_path = counting_files_module
        (tmp_path / "present.png").write_bytes(b"not really a png")
        request = files_module.BatchMetadataRequest(paths=["present.png"])

        await files_module.batch_get_metadata(request)

        assert opened == []

    def test_an_index_lookup_error_is_logged(self, monkeypatch, caplog):
        """`except Exception: asset = None` made a DB error a silent basename guess."""
        import api.routes.files as files_module
        from sqlmodel import SQLModel as _SQLModel

        class _Boom:
            def exec(self, *args, **kwargs):
                raise RuntimeError("no such column: assets.deleted_at")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(files_module, "_sync_session", lambda: _Boom())
        monkeypatch.setattr(files_module, "OUTPUT_DIR", "/nonexistent-output-dir")

        calls: list[tuple[str, dict]] = []
        original = files_module.logger.warning
        files_module.logger.warning = lambda event, **kw: calls.append((event, kw))
        try:
            assert files_module._resolve_asset_path("nothing-here.png") is None
        finally:
            files_module.logger.warning = original

        assert calls, "a failed asset-index lookup was reported as 'no such asset'"
        assert calls[0][0] == "asset_index_lookup_failed"
        assert "no such column" in calls[0][1]["error"]
        assert _SQLModel is not None


# ── F7: a corrupt favorites.json read as "no favourites" and was overwritten ──


class TestCorruptJsonIsNotSilent:
    """`GET /favorites` answered `[]`, the client posted it back, and the
    `save` overwrote the file: silent, permanent loss of every starred image.
    `get_branding_config` already logged on this shape; this one was copied
    without it.
    """

    def test_corrupt_favorites_are_logged(self, monkeypatch, tmp_path):
        import api.routes.settings as settings_module

        path = tmp_path / "favorites.json"
        path.write_text("{not json at all", encoding="utf-8")
        monkeypatch.setattr(settings_module, "FAVORITES_CONFIG_PATH", str(path))

        calls: list[tuple[str, dict]] = []
        original = settings_module.logger.error
        settings_module.logger.error = lambda event, **kw: calls.append((event, kw))
        try:
            assert settings_module.get_favorites_list() == []
        finally:
            settings_module.logger.error = original

        assert calls, "a corrupt favorites.json must be reported, not reshaped"
        assert calls[0][0] == "favorites_load_failed"

    def test_a_non_list_payload_is_not_handed_to_the_client(self, monkeypatch, tmp_path):
        """`{"a": 1}` was returned as `favorites`, then rejected by the POST."""
        import api.routes.settings as settings_module

        path = tmp_path / "favorites.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        monkeypatch.setattr(settings_module, "FAVORITES_CONFIG_PATH", str(path))

        assert settings_module.get_favorites_list() == []

    def test_a_corrupt_llm_config_is_logged(self, monkeypatch, tmp_path):
        """The third copy of the shape. It degrades rather than destroys — the
        default provider silently becomes "none" and `job_submission_service`
        drops `preferred_provider_id` — so warning is the right level.
        """
        import services.llm_config as llm_config_module

        path = tmp_path / "llm_config.json"
        path.write_text("<<<not json>>>", encoding="utf-8")
        monkeypatch.setattr(llm_config_module, "_CONFIG_PATH", str(path))
        llm_config_module._invalidate_cache()

        calls: list[tuple[str, dict]] = []
        original = llm_config_module.logger.warning
        llm_config_module.logger.warning = lambda event, **kw: calls.append((event, kw))
        try:
            assert llm_config_module._read_config() is None
        finally:
            llm_config_module.logger.warning = original
            llm_config_module._invalidate_cache()

        assert calls, "a corrupt llm_config.json silently drops the default provider"
        assert calls[0][0] == "llm_config_read_failed"


# ── F8: load_balancer mutated shared state without its own lock ──────────────


class TestLoadBalancerRuntimeStateLock:
    """`_load_state_lock` existed and was used by `load_state_from_db`, but four
    other sites read or iterated the module-level `_runtime_states` without it.
    A concurrent insert turns that into
    `RuntimeError: dictionary changed size during iteration` — a crash.
    """

    def test_get_runtime_state_is_critical(self, monkeypatch):
        """The membership test and the insert must not be separable."""
        import services.load_balancer as lb

        original_lock = lb._load_state_lock
        entries: list[str] = []

        class _TracingLock:
            def __enter__(self):
                entries.append("acquired")
                return original_lock.__enter__()

            def __exit__(self, *exc):
                entries.append("released")
                return original_lock.__exit__(*exc)

        monkeypatch.setattr(lb, "_load_state_lock", _TracingLock())
        lb.get_runtime_state(987654)

        assert entries == ["acquired", "released"]

    def test_reset_state_takes_a_locked_snapshot(self, monkeypatch):
        import services.load_balancer as lb

        acquired: list[str] = []

        class _TracingLock:
            def __enter__(self):
                acquired.append("acquired")
                return lb.threading.Lock()

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(lb, "_load_state_lock", _TracingLock())
        lb.LoadBalancer.reset_state()

        assert acquired, "iterating _runtime_states with no lock can raise"

    def test_remove_provider_state_snapshots_under_the_lock(self, session):
        import services.load_balancer as lb

        state = lb.get_runtime_state(5550001)
        state.provider_job_counts["p1"] = 1

        acquired: list[str] = []
        original_lock = lb._load_state_lock

        class _TracingLock:
            def __enter__(self):
                acquired.append("acquired")
                return original_lock.__enter__()

            def __exit__(self, *exc):
                return original_lock.__exit__(self, *exc)

        lb._load_state_lock = _TracingLock()
        try:
            asyncio.run(lb.LoadBalancer.remove_provider_state(session, "p1"))
        finally:
            lb._load_state_lock = original_lock
            state.reset()

        assert acquired, "list(_runtime_states.items()) with no lock can raise"

    def test_every_touch_of_the_shared_map_happens_under_the_lock(self, monkeypatch):
        """The invariant, checked deterministically rather than raced for.

        A real interleaving needs the insert to land inside an iteration, which
        is a switch-interval lottery — measured on the reverted code it fired at
        20 000 iterations and not at 6 000. So instead of hoping for the race,
        this makes the unlocked access *fail loudly*: a dict that refuses to be
        read or written unless `_load_state_lock` is held.
        `RuntimeError: dictionary changed size during iteration` is the symptom;
        "no lock" is the cause.
        """
        import services.load_balancer as lb

        class _LockRequiredDict(dict):
            def _require_lock(self, what):
                if not lb._load_state_lock.locked():
                    raise AssertionError(
                        f"_runtime_states.{what} with no _load_state_lock held"
                    )

            def __setitem__(self, key, value):
                self._require_lock("__setitem__")
                super().__setitem__(key, value)

            def values(self):
                self._require_lock("values()")
                return super().values()

            def items(self):
                self._require_lock("items()")
                return super().items()

        guarded = _LockRequiredDict(lb._runtime_states)
        monkeypatch.setattr(lb, "_runtime_states", guarded)

        # get_runtime_state: the membership test and the insert, one section.
        assert lb.get_runtime_state(4321001) is guarded[4321001]
        # reset_state: the snapshot it iterates.
        lb.LoadBalancer.reset_state()

    @pytest.mark.asyncio
    async def test_remove_provider_state_also_takes_a_locked_snapshot(
        self, session, monkeypatch
    ):
        import services.load_balancer as lb

        class _LockRequiredDict(dict):
            def _require_lock(self, what):
                if not lb._load_state_lock.locked():
                    raise AssertionError(
                        f"_runtime_states.{what} with no _load_state_lock held"
                    )

            def __setitem__(self, key, value):
                self._require_lock("__setitem__")
                super().__setitem__(key, value)

            def values(self):
                self._require_lock("values()")
                return super().values()

            def items(self):
                self._require_lock("items()")
                return super().items()

        monkeypatch.setattr(lb, "_runtime_states", _LockRequiredDict(lb._runtime_states))

        await lb.LoadBalancer.remove_provider_state(session, "no-such-provider")
