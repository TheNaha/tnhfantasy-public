"""Boot smoke test: actually enter and exit ``api.main:app``'s lifespan.

Two defects in this repo shipped green because every test built the arguments
the application uses instead of the arguments the application passes. The
provider workers crash-looped for a whole afternoon while 596 provider tests
passed, and ``SessionPanel`` imported a default export that does not exist
while 1080 frontend tests passed — its own test mocked the wrong module, so the
mock stood in for the defect.

This file is the backend half of that lesson. It does not check that
``startup_application`` does its job when a caller supplies sensible arguments;
it calls the lifespan exactly as Starlette does at process start, with the real
``process_job`` and the real ``ws_manager``, and asserts on the wiring that
actually executes. Only the *effects* the lifespan cannot perform in a unit
test — Docker, the asset tree on disk, an outbound HTTP client, the network
prefetch — are stubbed. Every function the lifespan calls is replaced at the
module it is looked up in, so a wrong keyword argument or a missing ``await``
still raises here.

The ``startup_init`` phase markers in ``api/lifecycle.py`` are the seams: they
are the declared contract of what runs, in what order, and intercepting them
turns a boolean "did boot" into a statement about which phases were reached and
in which order.
"""

import asyncio
import importlib
import inspect
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import infrastructure.background_tasks as background_tasks
import infrastructure.deps as infra_deps
from api.main import app, lifespan
from core.events import EventType, event_bus
from infrastructure.scheduler import get_scheduler
from services.job_queue import queue_manager
from services.model_preview_service import PREVIEW_PREFETCH_INTERVAL_SECONDS

# One event loop for the whole module. `queue_manager`, the scheduler global and
# `ws_manager` are process-wide singletons that the lifespan wires up and tears
# down, and asyncio binds a `Queue` to the loop that first awaits it — so a
# per-test loop would make the second test fail on "bound to a different event
# loop" for a reason that has nothing to do with the lifespan. Sharing the loop
# matches the process the lifespan is actually written for.
pytestmark = pytest.mark.asyncio(loop_scope="module")

# The lifespan's phases, in the order `api/lifecycle.py:startup_application`
# declares them. Asserting the exact sequence (not just membership) is the
# point: a phase silently skipped, or two swapped so a resource is published
# after its first reader, is a boot-time defect no per-function test sees.
EXPECTED_STARTUP_PHASES = [
    "database",
    "provider_state_cleanup",
    "job_processor",
    "asset_migration",
    "worker_pool",
    "provider_hosts",
    "job_queue",
    "provider_monitor",
    "job_recovery",
    "scheduler",
    "data_cleanup",
    "civitai_resync",
    "in_process_reconcile",
    "websocket",
    "world_integration",
]

# Shutdown is the other half of the leak class: whatever startup started has to
# be awaited or cancelled here, or a `--reload` cycle accumulates tasks.
EXPECTED_SHUTDOWN_PHASES = [
    "websocket",
    "provider_monitor",
    "background_tasks",
    "scheduler",
    "job_queue",
    "job_requeue",
    "http_client",
]

# The job ids and intervals `startup_application` registers. `idle_simulation` is
# deliberately absent: it is only added when COMFY_IDLE_SIM_ENABLED or
# config ai.idleSimEnabled is set, and neither is set under test, so its absence
# is the assertion that the opt-in branch was not taken by accident.
from api.lifecycle import PROVIDER_HOST_REFRESH_SECONDS
from services.in_process_reconciliation import IN_PROCESS_RECONCILE_INTERVAL_SECONDS

EXPECTED_SCHEDULED_JOBS = {
    "database_vacuum": 86400,
    "preview_prefetch": PREVIEW_PREFETCH_INTERVAL_SECONDS,
    "cleanup": 3600,
    "civitai_resync_job": 86400,
    "in_process_reconcile": IN_PROCESS_RECONCILE_INTERVAL_SECONDS,
    # Keeps the published provider-host set current. It belongs here rather than
    # on the request path: the address dialled can be a Docker container id that
    # changes on every recreate, and a boot-time snapshot plus a CRUD-triggered
    # refresh left a window where a dispatched job went out without the shared
    # worker token and came back 401 — reported as "the provider rejected or
    # crashed on this job", with nothing pointing at auth.
    "provider_host_refresh": PROVIDER_HOST_REFRESH_SECONDS,
}

# Topics the broadcast listener and the provider monitor subscribe to.
#
# Derived from `EventType` rather than listed by hand, because the room a
# websocket client joins is the prefix of an event value, so this list *is* the
# set of rooms that can receive anything. It listed `"download"`, which had no
# `EventType` behind it since the family was removed on 2026-10-03 — so the
# assertion below could never be satisfied by a correct lifespan, and
# `test_lifespan_runs_every_declared_startup_phase` was red on every run.
#
# It was reported for a long while as a load-related flake ("a boot test that
# starts real threads, and 20 s is tight after 2550 other tests"). It was not
# load: it failed identically in 24 s alongside 67 other tests, and
# `assert 0 > 0` for `download` is deterministic. `docs/STATUS.md` carried the
# flake label; this is the cause.
EVENT_BUS_TOPICS = tuple(sorted({e.value.split(".")[0] for e in EventType}))

# The lifespan does blocking I/O (a thread-backed provider-host read, a DB
# migration) and starts real tasks, so it is not instant. 20s is roughly an
# order of magnitude above a healthy boot; a boot test that can hang the suite
# is worse than no boot test, so the whole context is wrapped in this.
BOOT_TIMEOUT_SECONDS = 20.0


class _LogRecorder:
    """Stand-in for the structlog logger in ``api.lifecycle``.

    The phase markers are only useful as an ordering record if they are read off
    the call, not off a rendered handler — reading them from a real handler would
    couple this test to the structlog processor chain and to log level. The
    ``logger.info("startup_init", phase=...)`` calls themselves stay under test.
    """

    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []

    def _record(self, level, event, *args, **kwargs):
        self.events.append((level, str(event), kwargs))

    def debug(self, event, *args, **kwargs):
        self._record("debug", event, *args, **kwargs)

    def info(self, event, *args, **kwargs):
        self._record("info", event, *args, **kwargs)

    def warning(self, event, *args, **kwargs):
        self._record("warning", event, *args, **kwargs)

    def error(self, event, *args, **kwargs):
        self._record("error", event, *args, **kwargs)

    def events_named(self, name: str) -> list[dict]:
        return [kwargs for _level, event, kwargs in self.events if event == name]

    def phases(self, name: str) -> list[str]:
        return [kwargs["phase"] for kwargs in self.events_named(name) if "phase" in kwargs]

    def clear(self) -> None:
        self.events.clear()


async def _await_until(predicate, timeout: float = 5.0) -> bool:
    """Poll ``predicate`` for up to ``timeout`` seconds on the running loop.

    The asset migration is dispatched to a worker thread, so "the task started"
    is only observable once the thread has been scheduled and run. Sleeping a
    fixed amount would be either flaky or slow; a bounded poll is honest about
    what it knows.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.01)
    return True


def _spy(monkeypatch, target: str, sink: list, *, is_async: bool = False):
    """Replace ``target`` with a recorder that still binds its real signature.

    ``Signature.bind`` is what makes this a wiring test rather than a "was it
    called" test. A recorder with ``**kwargs`` swallows a wrong or missing
    keyword argument, which is precisely the shape of the provider-worker crash
    loop: 596 tests passed while ``build_lifespan`` raised ``TypeError:
    unexpected keyword argument 'storage_dir'`` on every container start. Binding
    against the real signature makes that same mistake raise here, at boot.

    Patched at the module the lifespan *looks the name up in*, which is not
    always where the name is defined: ``load_known_provider_hosts`` is imported
    inside ``startup_application`` and so is late-bound, while
    ``create_db_and_tables`` is bound at import. Patching the defining module
    would silently miss the late-bound ones — the same lookup mistake.
    """
    module_path, _, attribute = target.rpartition(".")
    signature = inspect.signature(getattr(importlib.import_module(module_path), attribute))

    def _bind(args, kwargs):
        signature.bind(*args, **kwargs)
        sink.append((args, kwargs))

    if is_async:
        async def _record(*args, **kwargs):
            _bind(args, kwargs)
    else:
        def _record(*args, **kwargs):
            _bind(args, kwargs)

    monkeypatch.setattr(target, _record)
    return _record


@pytest.fixture(name="boot")
def boot_fixture(monkeypatch):
    """Yield a helper that runs the real lifespan with its effects stubbed.

    Stubs exactly the effects a unit test cannot perform, and nothing else:
      * Docker  — ``ContainerManager()`` opens a socket to a daemon that does not
        exist in CI and may block.
      * disk   — the asset migration walks the real output tree.
      * network— the preview prefetch fetches remote images, and the CivitAI
        resync hits the CivitAI API.
      * DB     — schema creation and migrations, so the boot cannot race the
        ``engine`` fixture the autouse session redirect installs.

    Everything else runs for real: the worker pool, the provider monitor and
    the event-bus broadcast listener, job recovery, the scheduler and its
    registrations, the shutdown requeue, and the HTTP client teardown.
    """
    calls: dict[str, list] = {}
    recorder = _LogRecorder()

    def sink(name: str) -> list:
        return calls.setdefault(name, [])

    # The lifespan publishes a ContainerManager into two process-wide slots that
    # nothing else rewrites. monkeypatch only undoes the constructor patch, so
    # without this the sentinel would still be installed when the next test
    # file runs and every `get_container_manager()` caller would get it.
    had_state = hasattr(app.state, "container_manager")
    previous_state = getattr(app.state, "container_manager", None)
    previous_global = infra_deps._global_container_manager

    # `api.main.lifespan` imports ContainerManager inside the function body, so
    # the late-bound name is what needs replacing. A sentinel (rather than an
    # exception) keeps the happy path under test: app.state and the module
    # global must both end up holding the instance the lifespan built.
    container_manager = object()

    def _container_manager(*args, **kwargs):
        sink("container_manager").append((args, kwargs))
        return container_manager

    monkeypatch.setattr("services.container_manager.ContainerManager", _container_manager)

    # `startup_application` binds these at import time, so `api.lifecycle` is
    # where they are looked up.
    _spy(monkeypatch, "api.lifecycle.create_db_and_tables", sink("create_db_and_tables"))
    _spy(monkeypatch, "api.lifecycle.cleanup_provider_state_artifacts", sink("cleanup_provider_state_artifacts"))
    _spy(monkeypatch, "api.lifecycle.configure_worker_pool", sink("configure_worker_pool"))
    # Runs on a worker thread as a tracked background task; a recorder proves
    # the task really started rather than just being registered.
    _spy(monkeypatch, "api.lifecycle._run_asset_migration", sink("asset_migration"))

    # Late-bound imports inside `startup_application`.
    _spy(monkeypatch, "infrastructure.http_client.load_known_provider_hosts", sink("load_known_provider_hosts"))
    _spy(
        monkeypatch,
        "services.model_preview_service.prefetch_stale_model_previews",
        sink("prefetch_stale_model_previews"),
        is_async=True,
    )
    _spy(
        monkeypatch,
        "api.routes.models.maintenance.run_background_resync",
        sink("run_background_resync"),
        is_async=True,
    )

    # Scheduled work. These are registered with `start_immediately=False` and a
    # 24h/1h interval, so a healthy boot must not run any of them; the recorder
    # is what proves that rather than assuming it from the code.
    _spy(monkeypatch, "api.lifecycle.vacuum_database", sink("vacuum_database"), is_async=True)
    _spy(monkeypatch, "api.lifecycle.run_data_cleanup", sink("run_data_cleanup"), is_async=True)

    monkeypatch.setattr("api.lifecycle.logger", recorder)

    async def _boot(body=None):
        """Enter the lifespan, await ``body()`` while the app is up, then exit."""

        async def _run():
            async with lifespan(app):
                # Background tasks are created, not run: give the loop a few
                # turns so the workers, the monitor and the broadcast listener
                # have actually reached their first await before anything
                # inspects them.
                for _ in range(5):
                    await asyncio.sleep(0)
                if body is not None:
                    return await body()

        return await asyncio.wait_for(_run(), timeout=BOOT_TIMEOUT_SECONDS)

    yield _boot, calls, recorder, container_manager

    if had_state:
        app.state.container_manager = previous_state
    else:
        del app.state.container_manager
    infra_deps.set_global_container_manager(previous_global)


def _scheduler_jobs() -> dict:
    return {job.id: job for job in get_scheduler().get_jobs()}


async def _event_bus_baseline() -> dict[str, int]:
    return {topic: event_bus.subscriber_count(topic) for topic in EVENT_BUS_TOPICS}


async def test_lifespan_runs_every_declared_startup_phase(boot, session):
    """Entering the lifespan reaches every phase the code declares, in order."""
    _run_boot, calls, recorder, container_manager = boot

    baseline = await _event_bus_baseline()

    async def _inside():
        # Subscriptions are created by the consumer coroutines, which are
        # scheduled rather than run to completion by `start_background_task`, so
        # they are polled for here instead of being assumed to have happened.
        #
        # The poll's result is ASSERTED. It used to be discarded, so a timeout
        # fell through to the assertions below and surfaced as a confusing
        # failure about subscriber counts or worker pools, pointing at the
        # lifespan rather than at "the task never started within the window".
        # That misattribution is what made this look like a real regression when
        # the full suite ran: it starts real threads, and 5 s is tight when 2550
        # other tests have just been hammering the same event loop.
        assert await _await_until(
            lambda: event_bus.subscriber_count("provider") > baseline["provider"],
            timeout=20.0,
        ), "the provider consumer never subscribed within 20s of startup"
        return {
            "image_workers": len(queue_manager.image._workers),
            "llm_workers": len(queue_manager.llm._workers),
            "subscribers": await _event_bus_baseline(),
        }

    observed = await _run_boot(_inside)

    assert recorder.phases("startup_init") == EXPECTED_STARTUP_PHASES
    assert recorder.events_named("startup_complete"), "startup never reported completion"

    # The ContainerManager the lifespan built has to reach both the app state
    # and the module-level fallback that background tasks read, or provider
    # status routes silently see "no container manager".
    assert calls["container_manager"], "lifespan never constructed a ContainerManager"
    assert app.state.container_manager is container_manager
    assert infra_deps.get_container_manager() is container_manager

    # Each stubbed effect was reached with the arguments the lifespan intends.
    # `skip_orphan_cleanup=True` is the one that matters: on first boot the
    # provider statuses have not been re-registered yet, and clearing them
    # deletes live provider rows.
    assert calls["create_db_and_tables"], "schema init phase did no work"
    _args, kwargs = calls["cleanup_provider_state_artifacts"][0]
    assert kwargs == {"skip_orphan_cleanup": True}
    assert calls["configure_worker_pool"], "worker pool was never configured"
    # 20s, not the default 5s, and for the same reason the provider-consumer
    # assertion below uses it: the phase is dispatched to a worker thread, so
    # "started" is only observable once the OS has scheduled it. Under a full
    # suite run — 2550 other tests having just hammered the same event loop —
    # 5s is tight enough to fail intermittently, and the failure message
    # ("task never started") misattributes a scheduling delay to a missing
    # startup phase. Measured: one failure in a 995s full-suite run, 3/3 passes
    # in isolation at ~2.5s each.
    assert await _await_until(lambda: bool(calls["asset_migration"]), timeout=20.0), (
        "asset migration task never started within 20s of startup"
    )
    _args, kwargs = calls["load_known_provider_hosts"][0]
    assert kwargs == {"force": True}, "provider-host cache was primed from a stale read"

    # The worker pool is real: processors registered, workers spawned.
    assert queue_manager.image._processor is not None
    assert queue_manager.llm._processor is queue_manager.image._processor
    assert observed["image_workers"] >= 1
    assert observed["llm_workers"] >= 1

    # The provider monitor and the broadcast listener are real event-bus
    # consumers that must be startable with no live backend and no Docker
    # socket, and they must be subscribed while the app is up — a monitor that
    # never subscribes means the pool is never resized when a provider dies.
    for topic in EVENT_BUS_TOPICS:
        assert observed["subscribers"][topic] > baseline[topic], (
            f"no startup task subscribed to event-bus topic {topic!r}"
        )


async def test_shutdown_stops_everything_startup_started(boot):
    """Exiting the lifespan cancels what it started and stops the bus."""
    _run_boot, calls, recorder, _cm = boot

    baseline = await _event_bus_baseline()
    await _run_boot()

    assert recorder.phases("shutdown") == EXPECTED_SHUTDOWN_PHASES
    assert recorder.events_named("shutdown_complete"), "shutdown never reported completion"

    # Nothing outlives the lifespan. An untracked task is the failure mode that
    # makes `--reload` and repeated TestClient use leak silently.
    assert background_tasks._background_tasks == set()
    assert queue_manager.image._workers == []
    assert queue_manager.llm._workers == []

    from api.routes.websocket import ws_manager

    assert ws_manager._running is False
    assert ws_manager._broadcast_task is None or ws_manager._broadcast_task.cancelled()

    # `stop_scheduler` drops the global, so the next boot builds a fresh one
    # rather than reusing a shut-down instance.
    import infrastructure.scheduler as scheduler_module

    assert scheduler_module._scheduler is None
    assert not get_scheduler().running

    # Consumer tasks are cancelled, not awaited to completion, so the async
    # generators that hold the subscriptions are finalized by the loop rather
    # than by the shutdown path. Settle the loop before measuring.
    for _ in range(20):
        await asyncio.sleep(0)

    for topic in EVENT_BUS_TOPICS:
        assert event_bus.subscriber_count(topic) == baseline[topic], (
            f"topic {topic!r} kept a subscriber after shutdown"
        )


async def test_scheduler_registers_jobs_without_running_the_slow_ones(boot):
    """Jobs land with the intended intervals; the daily/hourly ones stay idle."""
    _run_boot, calls, recorder, _cm = boot

    # The scheduler is inspected *inside* the boot window: `shutdown_application`
    # calls `stop_scheduler()`, which drops the module global, so reading it
    # afterwards would look at a fresh empty scheduler and pass vacuously.
    async def _snapshot():
        return {
            job_id: (job.trigger.interval.total_seconds(), job.next_run_time)
            for job_id, job in _scheduler_jobs().items()
        }

    jobs = await _run_boot(_snapshot)

    assert set(jobs) == set(EXPECTED_SCHEDULED_JOBS), (
        f"unexpected scheduler contents: {sorted(jobs)}"
    )
    for job_id, interval in EXPECTED_SCHEDULED_JOBS.items():
        assert jobs[job_id][0] == interval

    # The daily/hourly jobs were registered with `start_immediately=False`, so
    # their first fire is a full interval out. Asserting the schedule is not
    # enough on its own: the call recorders prove none of them actually ran.
    for job_id in ("database_vacuum", "civitai_resync_job", "cleanup"):
        next_run = jobs[job_id][1]
        assert next_run is not None
        delta = (next_run - datetime.now(next_run.tzinfo)).total_seconds()
        assert delta > 3000, f"{job_id} is scheduled to fire within the test window"

    assert calls["vacuum_database"] == []
    assert calls["run_data_cleanup"] == []
    assert calls["run_background_resync"] == []


async def test_app_serves_requests_after_boot(client, boot):
    """Routes are mounted and the readiness probe answers through a TestClient."""
    _run_boot, _calls, _recorder, _cm = boot

    await _run_boot()

    spec = app.openapi()
    # 249 unique paths / 329 operations, counted from the code rather than
    # guessed — regenerate with:
    #   python -c "from api.main import app; s=app.openapi(); \
    #     print(len(s['paths']), sum(len(v) for v in s['paths'].values()))"
    # 15 routers mounted by `configure_app`, plus its two inline routes (`/`
    # and `/metrics`). The `/socket.io` mount is deliberately absent: it is a
    # raw ASGI sub-app, so FastAPI does not put it in the OpenAPI document.
    # An exact count, so a route that stops being registered is caught. It has to
    # be bumped when routes are ADDED on purpose — the two voice endpoints
    # (`/api/v2/voices/design` and `/api/v2/voices/speak`) took it from 247.
    assert len(spec["paths"]) == 249, (
        "route count changed; if routes were added deliberately, bump this"
    )
    # Bumped by 2 for the voice design and speak endpoints. An exact count so a
    # route that stops being registered is caught; it has to be nudged when
    # routes are added on purpose, which is why the two numbers are adjacent.
    assert sum(len(ops) for ops in spec["paths"].values()) == 329
    assert "/api/ready" in spec["paths"]
    assert not any(path.startswith("/socket.io") for path in spec["paths"])

    # TestClient without `with`: entering the context manager would run a
    # second lifespan, and the boot under test already ran this one.
    response = TestClient(app).get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "version": "2.0.0"}


async def test_two_boots_in_sequence(boot):
    """Boot, shut down, boot again — the shape of a supervisor restart.

    The singletons the lifespan hands out (`queue_manager`, the scheduler
    module global, the event bus) are exactly what a second pass would find in
    a dirty state, so this is a regression test for the teardown above as much
    as for startup.
    """
    _run_boot, _calls, recorder, _cm = boot

    baseline = await _event_bus_baseline()

    for _ in range(2):
        recorder.clear()
        await _run_boot()
        assert recorder.phases("startup_init") == EXPECTED_STARTUP_PHASES
        assert recorder.phases("shutdown") == EXPECTED_SHUTDOWN_PHASES
        assert recorder.events_named("startup_complete")
        assert recorder.events_named("shutdown_complete")

    # A restarted process must not inherit the previous one's live tasks.
    assert background_tasks._background_tasks == set()
    assert queue_manager.image._workers == []
    assert queue_manager.llm._workers == []
    for _ in range(20):
        await asyncio.sleep(0)
    for topic in EVENT_BUS_TOPICS:
        assert event_bus.subscriber_count(topic) == baseline[topic]
