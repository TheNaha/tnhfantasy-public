"""The event-loop-blocking invariant, as an invariant rather than a list.

`test_event_loop_blocking.py` pins a handful of *named* handlers, which meant it
went green while 19 more routes did the same thing. The failure mode is a list:
any route added later is unconstrained, and any route fixed at one site leaves
its siblings alone.

So this asserts the rule itself, over the whole `api/routes` package:

    A route handler that is `async def` and never awaits anything is a bug,
    because it gets none of the event loop's concurrency and gives up the
    worker thread its work needs.

`async def` earns its place only by actually awaiting. A handler with no
`await` should be a plain `def`, which FastAPI runs in a threadpool
(AnyIO's worker thread) — this is the same idiom `/api/ready` in
`api/routes/health.py` documents in place, so the fix is established
convention here, not a new one.

A handler that *does* await can still block the loop: awaiting an `async def`
service that itself never awaits runs that service's body inline. That is the
remaining, harder half of the problem and this test cannot see it — it is
called out in the allowlist below so the gap is recorded rather than forgotten.
"""

import ast
from pathlib import Path

import pytest

ROUTES_DIR = Path(__file__).resolve().parents[1] / "api" / "routes"

# Route handlers that are `async def` and contain no `await`, but which are
# knowingly left alone. Every entry needs a reason: this file is a register of
# known debt, not a place to hide exceptions.
#
# Each of these awaits an `async def` service whose body contains no `await`, so
# the service's synchronous SQLModel work runs inline on the loop. Fixing them
# means making the service method synchronous and hoisting the call into
# `asyncio.to_thread`, which is a paid-path change with exactly one production
# caller each — deliberately not done as a drive-by in an audit pass.
AWAIT_CHAINED_TO_SYNC_SERVICE = {
    "list_jobs": "awaits JobService.list_jobs, which has no await of its own",
    "search_jobs": "awaits JobService.search_jobs, same shape",
    "list_failed_jobs": "awaits JobService.get_failed_jobs, same shape",
    "get_jobs_breakdown": "awaits JobService.get_metadata_key_counts, same shape",
    "acknowledge_job": "awaits JobService.acknowledge_jobs, same shape",
    "retry_job": "awaits JobService.retry_job, same shape",
    "cancel_job": "awaits JobService.cancel_job, same shape",
    "get_job": "awaits JobService.get_job, same shape",
    "get_job_diagnostics": "awaits JobService.get_job_diagnostics, same shape",
    "delete_job": "awaits JobService.delete_job, same shape",
    "recover_jobs": "awaits JobService.recover_jobs, same shape",
    "create_job": "must await queue_manager.enqueue, which is loop-affine",
}

# Routes with no await at all. Anything listed here has been converted to a
# plain `def`; the test asserts they stay converted.
CONVERTED = {
    ("health.py", "health"),
    ("autopopulate.py", "get_autopopulate_pending"),
    ("autopopulate.py", "get_autopopulate_status"),
    ("lifecycle.py", "get_provider_logs"),
    ("settings.py", "get_settings"),
    ("settings.py", "get_settings_schema"),
    ("settings.py", "get_system_prompts"),
    ("settings.py", "get_session_status"),
    ("settings.py", "start_session"),
    ("worker_ws.py", "list_connected_workers"),
    ("jobs.py", "validate_workflow"),
}


def _route_handlers(path: Path):
    """Yield (name, lineno, has_await) for every decorated route handler."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        decorated = False
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                if target.value.id in {"router", "app"}:
                    decorated = True
        if not decorated:
            continue
        has_await = any(
            isinstance(n, (ast.Await, ast.AsyncFor, ast.AsyncWith))
            for n in ast.walk(node)
        )
        yield node.name, node.lineno, has_await, isinstance(node, ast.AsyncFunctionDef)


ALL_HANDLERS = [
    (path, name, lineno, has_await, is_async)
    for path in sorted(ROUTES_DIR.rglob("*.py"))
    if "__pycache__" not in path.parts
    for name, lineno, has_await, is_async in _route_handlers(path)
]


def test_the_route_tree_was_actually_parsed():
    """Guards against the sweep silently matching nothing.

    A file-layout change that moved the routes out of `api/routes` would make
    every test below pass vacuously, which is the same class of bug as the one
    this file exists to prevent.
    """
    assert len(ALL_HANDLERS) > 200, (
        f"only {len(ALL_HANDLERS)} route handlers found under {ROUTES_DIR}; "
        "the sweep is not looking where it thinks it is"
    )


def test_no_async_handler_is_pointlessly_async():
    """The invariant: an `async def` route must await something."""
    offenders = [
        f"{path.relative_to(ROUTES_DIR.parent.parent)}:{lineno} {name}"
        for path, name, lineno, has_await, is_async in ALL_HANDLERS
        if is_async and not has_await
    ]
    assert not offenders, (
        "these route handlers are `async def` but never await, so they run on "
        "the event loop while getting none of its concurrency. Make them a "
        "plain `def` (FastAPI runs those in a worker thread):\n  "
        + "\n  ".join(offenders)
    )


def test_the_converted_handlers_stay_converted():
    """The 11 conversions are load-bearing, not a one-off edit."""
    still_async = []
    for path, name, lineno, has_await, is_async in ALL_HANDLERS:
        if (path.name, name) in CONVERTED and is_async:
            still_async.append(f"{path.name}:{lineno} {name}")
    assert not still_async, "these were converted to `def` and reverted:\n  " + "\n  ".join(
        still_async
    )


def test_the_allowlisted_names_are_still_real_routes():
    """Each allowlist entry must still exist, or it is hiding a rename.

    An allowlist naming a route that no longer exists silently stops allowing
    anything, which would make the next `async def` route a surprise instead of
    a known quantity.
    """
    present = {name for _, name, _, _, _ in ALL_HANDLERS}
    missing = sorted(set(AWAIT_CHAINED_TO_SYNC_SERVICE) - present)
    assert not missing, (
        "these allowlisted handlers no longer exist; delete them from the "
        f"allowlist or the next offender hides behind a stale name: {missing}"
    )


@pytest.mark.parametrize(
    "name,reason",
    sorted((n, r) for n, r in AWAIT_CHAINED_TO_SYNC_SERVICE.items()),
)
def test_allowlisted_route_still_awaits(name, reason):
    """A no-longer-awaiting route must leave the allowlist and become `def`."""
    matches = [(p, l) for p, n, l, _, _ in ALL_HANDLERS if n == name]
    assert matches, f"{name} is allowlisted but not a route handler any more"
    for path, lineno in matches:
        has_await = next(
            h for p, n, l, h, _ in ALL_HANDLERS if p == path and n == name
        )
        assert has_await, (
            f"{name} ({path.name}:{lineno}) is in the allowlist but no longer "
            f"awaits — {reason}. It should now be a plain `def`; remove it from "
            "AWAIT_CHAINED_TO_SYNC_SERVICE and let the invariant test hold it."
        )
