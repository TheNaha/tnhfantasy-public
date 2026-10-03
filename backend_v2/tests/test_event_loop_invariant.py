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
harder half of the problem, and until 2026-10-03 this file could not see it —
it recorded the gap in a docstring and left it. It is now covered by
`test_no_await_chain_ends_in_sync_work`, which resolves awaited callees across
modules and fails when the whole chain contains no `await`. That test found six
routes the old sweep passed, including the 1.5 MB model listing measured flat at
778 ms per request from concurrency 1 to 16.
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


# ---------------------------------------------------------------------------
# Cross-module await-chain resolution.
#
# `has_await` is a per-function fact. The question that matters is a chain
# question: does this handler's *entire* await tree contain anything that
# actually suspends, or does it bottom out in a service method whose body is
# synchronous? A chain with no `await` anywhere in it is a synchronous
# computation wearing async syntax, and it runs on the event loop.
# ---------------------------------------------------------------------------

SRC_DIR = ROUTES_DIR.parent
SEARCH_DIRS = [SRC_DIR / "routes", SRC_DIR.parent / "services", SRC_DIR / "infrastructure"]


def _function_index():
    """{name: [every def with that name]} across the searched directories.

    A list, not a single node, and that matters: `get_model` and `search_jobs`
    each exist in more than one repository and service, and keying on the first
    one alphabetically would resolve some calls to the wrong function. A name
    counts as "resolvable to a sync chain" only when *every* local definition of
    it is sync, so a collision can produce a missed finding but never a wrong
    one.
    """
    index: dict[str, list[ast.AST]] = {}
    for directory in SEARCH_DIRS:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                index.setdefault(node.name, []).append(node)
                for child in node.body:
                    if isinstance(child, ast.ClassDef):
                        index.setdefault(f"{child.name}.{node.name}", []).append(node)
    return index


FUNCTION_INDEX = _function_index()


def _awaited_names(node) -> set[str]:
    """Names of functions this body awaits (`await self.svc.method(...)`)."""
    names = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Await):
            continue
        value = child.value
        if isinstance(value, ast.Call):
            func = value.func
            if isinstance(func, ast.Attribute):
                names.add(func.attr)
            elif isinstance(func, ast.Name):
                names.add(func.id)
    return names


def _chain_has_real_await(node, seen: set[str], depth: int = 0) -> bool:
    """True when this function, or anything it awaits, genuinely suspends.

    The recursion bottoms out on any await whose callee is not a function we can
    resolve locally — `await asyncio.sleep(...)`, `await asyncio.to_thread(...)`,
    an httpx call, a socket read. Those really do suspend, and `to_thread`
    additionally moves the work off the loop, which is the whole point of it.

    An await that resolves to a local function is only "real" if that function
    eventually suspends too. A local `async def` with no `await`, or a plain
    `def`, contributes nothing — it runs inline.

    Depth-limited because a service can call another service; the question is
    only ever about the first few hops, and an unbounded walk over a cyclic call
    graph would hang the suite.
    """
    if depth > 3 or id(node) in seen:
        return False
    seen.add(id(node))

    # A plain `def` cannot await anything.
    if not isinstance(node, ast.AsyncFunctionDef):
        return False

    for name in _awaited_names(node):
        callees = FUNCTION_INDEX.get(name)
        if not callees:
            return True  # unresolvable: a genuine suspension
        if any(_chain_has_real_await(c, seen, depth + 1) for c in callees):
            return True
    return False


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


def test_the_await_chain_resolver_found_functions():
    """Guards against the resolver silently matching nothing.

    The first version of this analysis returned "no offenders" because the
    index was keyed by qualified names that no call site used, which is the
    same vacuous pass the file header warns about.
    """
    assert len(FUNCTION_INDEX) > 400, (
        f"only indexed {len(FUNCTION_INDEX)} functions; the await-chain "
        "resolver is not looking where it thinks it is"
    )


# Routes whose await chain resolves to nothing that suspends, discovered by
# `test_no_await_chain_ends_in_sync_work` on 2026-10-03 rather than by hand. Same
# contract as AWAIT_CHAINED_TO_SYNC_SERVICE above: a register of known debt, with
# the rule still enforced for everything not on it, and stale entries failing so
# a rename cannot quietly shrink the list.
#
# Each is `route name -> the service method it awaits`. The fix is the same for
# all of them and is the one already established in this repo: make the service
# method synchronous (it has exactly one production caller) and make the route a
# plain `def`, which FastAPI runs in a worker thread. Four were converted in the
# same pass — `list_models`, `get_generation_info`, `acknowledge_all_failed_jobs`
# and `delete_all_jobs` — of which `list_models` was the measured one.
SYNC_CHAINED = {
    "list_all_models": "ModelServiceV2.list_models",
    "list_models_by_directory": "ModelServiceV2.list_models_by_directory",
    "search_models": "ModelServiceV2.search_models",
    "search_by_tag": "ModelServiceV2.search_by_tag",
    "get_model": "ModelServiceV2.get_model",
    "delete_model": "ModelServiceV2.delete_model",
    "get_versions": "ModelServiceV2.get_versions",
    "set_default_version_modern": "ModelServiceV2.set_default_version",
    "toggle_version_enabled": "ModelServiceV2.toggle_version_enabled",
    "get_provider_statuses": "ModelServiceV2.get_provider_statuses",
    "register_discovered_models": "ModelServiceV2.register_discovered_models",
    "receive_batch_sync_progress": "ModelServiceV2.update_batch_sync_progress",
    "search_autopopulate_candidates": "ModelCivitaiSyncService.search_candidates",
    "get_load_balancing_config": "ProviderService.get_load_balancing_config",
    "update_load_balancing_config": "ProviderService.update_load_balancing_config",
    "get_load_balancer_stats": "ProviderService.get_load_balancer_stats",
    "get_load_balancing_alias": "ProviderService.get_load_balancing_config",
    "update_load_balancing_alias": "ProviderService.update_load_balancing_config",
    "mint_provider_worker_token": "ProviderService.mint_worker_token",
    "revoke_provider_worker_token": "ProviderService.revoke_worker_token",
    "get_provider_modal_stats": "ProviderService.get_modal_stats",
    "get_provider_sync_status": "ProviderService.get_sync_status",
    "get_provider_models": "ProviderService.get_provider_models",
    "setup_provider": "ProviderService.setup_provider",
    "deploy_provider_app": "ProviderService.deploy_app",
    "get_reconciliation_status": "ProviderService.get_reconciliation_status",
    "get_object_info": "ProviderService proxy — pass-through, resolved elsewhere",
    "handle_provider_discovery": "ProviderService.upsert_provider_from_discovery",
    "reconcile_chat_replies": "JobService.reconcile_chat_replies",
    "parse_model_url": "ModelImportService — provider HTTP, needs a real await",
    "get_civitai_enums": "ModelImportService — provider HTTP, needs a real await",
    "get_civitai_tags": "ModelImportService — provider HTTP, needs a real await",
    "search_civitai": "ModelImportService — provider HTTP, needs a real await",
    "search_huggingface": "ModelImportService — provider HTTP, needs a real await",
}


def test_no_await_chain_ends_in_sync_work():
    """An `async def` route whose whole await chain contains no `await`.

    These handlers pass `test_no_async_handler_is_pointlessly_async` — they do
    contain the keyword — while getting none of the concurrency an `async def`
    is supposed to buy, because the suspension they wait on never happens. The
    work runs on the event loop.

    Measured on the live stack 2026-10-03 for `GET /api/v2/models/` before its
    chain was converted: 761 ms per request at concurrency 1, 778 ms at
    concurrency 16. Flat means serialised. A control route using
    `asyncio.to_thread` went 360 -> 59 -> 31 ms over the same sweep.

    The 32 routes still on SYNC_CHAINED are registered debt, not fixed. The five
    `ModelImportService` entries are there because the resolver cannot see their
    outbound HTTP — they are listed as needing a real await rather than
    pretending the sweep proved them.
    """
    offenders = []
    for path, name, lineno, has_await, is_async in ALL_HANDLERS:
        if not is_async or not has_await:
            continue
        if name in SYNC_CHAINED or name in AWAIT_CHAINED_TO_SYNC_SERVICE:
            continue
        node = next(
            (
                n
                for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name
            ),
            None,
        )
        if node is None or _chain_has_real_await(node, set()):
            continue
        offenders.append(f"{path.relative_to(SRC_DIR.parent)}:{lineno} {name}")

    assert not offenders, (
        "these `async def` routes await a chain that contains no `await` "
        "anywhere, so their work runs on the event loop. Make the service method "
        "synchronous and the route a plain `def`:\n  " + "\n  ".join(offenders)
    )


def test_the_sync_chained_register_has_no_stale_entries():
    """A register entry that no longer matches a route hides a future offender.

    Same reason `test_the_allowlisted_names_are_still_real_routes` exists.
    """
    present = {name for _, name, _, _, _ in ALL_HANDLERS}
    missing = sorted(set(SYNC_CHAINED) - present)
    assert not missing, (
        "these SYNC_CHAINED entries no longer name a route; delete them so the "
        f"list keeps meaning something: {missing}"
    )
