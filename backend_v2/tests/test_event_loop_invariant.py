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
import re
from collections import deque
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
    "list_jobs": (
        "JobService.list_jobs is a decorative async def around one synchronous "
        "keyset query. The route hands it to deduplicated() as a coroutine, so "
        "it runs inside the shielded task - still on the loop. The resolver "
        "passes this route because deduplicated awaits asyncio.shield, which "
        "is unresolvable and therefore scored as a real suspension; the "
        "blocking query is behind that, not under it."
    ),
    "search_jobs": (
        "JobService.search_jobs, same shape: a synchronous tsvector/LIKE query "
        "passed into deduplicated() as a coroutine, behind the same "
        "asyncio.shield the resolver stops at."
    ),
    "list_failed_jobs": "awaits JobService.get_failed_jobs, which has no await of its own",
    "get_jobs_breakdown": "awaits JobService.get_metadata_key_counts, same shape",
    "acknowledge_job": "awaits JobService.acknowledge_jobs, same shape",
    "retry_job": (
        "JobService.get_job is a decorative async def around one synchronous "
        "repository read, run inline at the top of the handler. The rest of "
        "the chain (JobSubmissionService.create_and_enqueue_job) genuinely "
        "suspends, so the resolver passes the route and never sees the read."
    ),
    "cancel_job": (
        "JobService.cancel_job is a decorative async def around a synchronous "
        "status write. It is imported inside the handler body "
        "(from services.job_processing import cancel_job as "
        "cancel_job_processing), so the resolver looks the name up under its "
        "alias, does not find it, and scores the route as suspending."
    ),
    "get_job": "awaits JobService.get_job, which has no await of its own",
    "get_job_diagnostics": (
        "awaits JobService.get_job for the row it returns diagnostics for, "
        "same shape"
    ),
    "delete_job": "awaits JobService.delete_job, which has no await of its own",
    "recover_jobs": (
        "JobService.fail_stale_running_jobs is a decorative async def around a "
        "synchronous status write, and QueueManager.recover also calls "
        "job_service.get_pending_jobs()/get_running_jobs() (sync repository "
        "reads) inline. The enqueue and asyncio.to_thread awaits that make the "
        "resolver score this chain as suspending happen later in the same "
        "call, after the writes."
    ),
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
    # 2026-10-03 resolver fix. `ModelServiceV2.get_model` is now a plain `def`
    # (one repository read, no suspension), so `GET /api/v2/models/{id}` had
    # nothing left to await.
    ("crud.py", "get_model"),
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
PKG_DIR = SRC_DIR.parent
# Every package a route handler's await chain can walk through. `infrastructure`
# and `core` were missing here for the same reason `routes` was: `SRC_DIR` is
# `backend_v2/api`, so `SRC_DIR / "infrastructure"` is `backend_v2/api/
# infrastructure`, which does not exist. `_function_index` skips directories that
# do not exist, so the two misses were silent — `ModelRepositoryV2`,
# `ModelDownloader` and `EventBus` were invisible, their methods were
# unresolvable, and an unresolvable await is scored as "a genuine suspension".
# That single bad path entry made the resolver pass any route whose chain ended
# in a repository or a core helper.
SEARCH_DIRS = [
    SRC_DIR / "routes",
    PKG_DIR / "services",
    PKG_DIR / "infrastructure",
    PKG_DIR / "core",
]


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
                index.setdefault(f"{path.stem}.{node.name}", []).append(node)
            # `Class.method` as well, so a register entry can name the exact
            # method it is about. `get_model` alone is ambiguous across three
            # classes, which is what made the old stale-entry guard useless for
            # anything but renames of the route itself.
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        index.setdefault(f"{node.name}.{child.name}", []).append(child)
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


def _chain_has_real_await(node, seen: set[int] | None = None) -> bool:
    """True when this function, or anything it awaits, genuinely suspends.

    The traversal bottoms out on any await whose callee is not a function we can
    resolve locally — `await asyncio.sleep(...)`, `await asyncio.to_thread(...)`,
    an httpx call, a socket read. Those really do suspend, and `to_thread`
    additionally moves the work off the loop, which is the whole point of it.

    An await that resolves to a local function is only "real" if that function
    eventually suspends too. A local `async def` with no `await`, or a plain
    `def`, contributes nothing — it runs inline.

    Walks breadth-first over everything reachable, with a visited set rather than
    a depth limit. The depth limit was a lie about how deep the service facades
    go: `ModelServiceV2` delegates to `ModelCivitaiSyncService`, which delegates
    to `ModelDownloader`, which does the actual synchronous SQLModel writes — so
    `depth > 3` reported "nothing real to see here" for exactly the chains that
    matter. The visited set is what terminates the walk on a cyclic call graph,
    which is a property the depth limit never had to provide.
    """
    visited: set[int] = set() if seen is None else seen
    queue: deque = deque([node])
    while queue:
        current = queue.popleft()
        if id(current) in visited:
            continue
        visited.add(id(current))

        # A plain `def` cannot await anything.
        if not isinstance(current, ast.AsyncFunctionDef):
            continue

        for name in _awaited_names(current):
            callees = FUNCTION_INDEX.get(name)
            if not callees:
                return True  # unresolvable: a genuine suspension
            queue.extend(callees)
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


def test_every_searched_directory_exists_and_is_indexed():
    """A `SEARCH_DIRS` entry that does not exist is a silent hole.

    `_function_index` skips directories that are not there rather than failing,
    which is what let `SRC_DIR / "infrastructure"` — which resolves to
    `backend_v2/api/infrastructure`, a path that has never existed — sit in the
    list silently. Every function in an unindexed package is unresolvable, and
    unresolvable is scored as "a genuine suspension", so a typo'd path here does
    not fail this file: it *passes* routes that block the event loop.

    Asserting the path exists also catches the other direction: a package that
    gets renamed or moved and leaves this list pointing at nothing.
    """
    missing = [str(d) for d in SEARCH_DIRS if not d.is_dir()]
    assert not missing, (
        "SEARCH_DIRS points at directories that do not exist, so their "
        "functions are invisible to the resolver and every route whose await "
        f"chain runs through them is wrongly passed: {missing}"
    )

    # Existence is necessary but not sufficient: the directory must actually
    # contribute something, or it is indexed-but-empty and equally blind.
    empty = [
        str(d) for d in SEARCH_DIRS if d.is_dir() and not any(d.rglob("*.py"))
    ]
    assert not empty, f"these SEARCH_DIRS directories contain no Python: {empty}"


# Routes whose await chain resolves to nothing that suspends, discovered by
# `test_no_await_chain_ends_in_sync_work` on 2026-10-03 rather than by hand. Same
# contract as AWAIT_CHAINED_TO_SYNC_SERVICE above: a register of known debt, with
# the rule still enforced for everything not on it, and stale entries failing so
# a rename cannot quietly shrink the list.
#
# Each is `route name -> the service method it awaits, and why`. The fix is the
# same for all of them and is the one already established in this repo: make the
# service method synchronous and make the route a plain `def`, which FastAPI
# runs in a worker thread. Four were converted in the 2026-10-03 pass —
# `list_models`, `get_generation_info`, `acknowledge_all_failed_jobs` and
# `delete_all_jobs` — of which `list_models` was the measured one. Four more
# were converted when the resolver was fixed (see `CONVERTED` and the
# `asyncio.to_thread` call sites in `provider_sync.py` / `maintenance.py` /
# `reconciliation.py`); those four are no longer entries here because they are
# no longer offenders.
#
# Every reason must name a resolvable `Owner.method`, and
# `test_every_register_reason_names_a_method_that_still_exists` holds them to
# it. Several entries below previously named a method that does not exist
# (`ModelServiceV2.get_provider_statuses`, `ModelServiceV2.
# update_batch_sync_progress`, `ProviderService.get_modal_stats`,
# `ModelCivitaiSyncService.search_candidates`, ...), which is the same
# vacuous-entry failure the two route-name guards exist for, one level down.
SYNC_CHAINED = {
    "list_all_models": "ModelServiceV2.list_models — one bulk query, no await of its own",
    "list_models_by_directory": (
        "ModelServiceV2.list_models_by_directory — one bulk query, no await of its own"
    ),
    "search_models": "ModelServiceV2.search_models — same shape",
    "search_by_tag": "ModelServiceV2.search_by_tag — same shape",
    "delete_model": (
        "ModelServiceV2.delete_model — runs self.repo.get_model / "
        "get_files_for_model / add_tombstone (each a synchronous write) inline "
        "before it awaits ModelDownloader.trigger_delete_from_providers, and "
        "self.repo.delete_model inline after. The provider HTTP call in the "
        "middle is what makes the resolver score this chain as suspending; the "
        "surrounding DB work is not covered by it."
    ),
    "get_versions": "ModelServiceV2.get_versions — same shape",
    "set_default_version_modern": "ModelServiceV2.set_default_version — same shape",
    "toggle_version_enabled": "ModelServiceV2.toggle_version_enabled — same shape",
    "get_provider_statuses": (
        "ModelServiceV2.get_model_provider_statuses — delegates to "
        "ModelDownloader.get_model_provider_statuses, a bare repository read "
        "behind two decorative async defs"
    ),
    "register_discovered_models": (
        "ModelServiceV2.register_discovered_files — "
        "ModelReconciliationService.register_discovered_files does its session "
        "writes inline"
    ),
    "search_autopopulate_candidates": (
        "ExternalModelService.search_civitai — outbound provider HTTP the "
        "resolver cannot see. The synchronous repo.get_model() model-existence "
        "check runs inline before that await, so this is listed as needing a "
        "real await rather than pretending the sweep proved either way."
    ),
    "get_load_balancing_config": (
        "ProviderService.get_load_balancer_stats — the sibling "
        "ProviderService.get_load_balancing_config is already a plain `def`, so "
        "this route's only await is the stats query"
    ),
    "update_load_balancing_config": "ProviderService.update_load_balancing_config — same shape",
    "get_load_balancer_stats": "ProviderService.get_load_balancer_stats — same shape",
    "get_load_balancing_alias": (
        "ProviderService.get_load_balancer_stats — reaches it through the "
        "get_load_balancing_config route handler"
    ),
    "update_load_balancing_alias": (
        "ProviderService.update_load_balancing_config — reaches it through the "
        "update_load_balancing_config route handler"
    ),
    "mint_provider_worker_token": "ProviderService.mint_worker_token — same shape",
    "revoke_provider_worker_token": "ProviderService.revoke_worker_token — same shape",
    "get_provider_modal_stats": (
        "ProviderStatusService.get_provider_storage_stats — "
        "ProviderService.get_provider alongside it is a decorative async def "
        "around one repository read"
    ),
    "get_provider_sync_status": "ProviderStatusService.get_provider_sync_status — same shape",
    "get_provider_models": (
        "ProviderStatusService.get_provider_sync_status — the route awaits the "
        "get_provider_sync_status handler and then groups the result in Python"
    ),
    "setup_provider": (
        "ProviderLifecycleService.setup_provider — worker CLI setup that still "
        "opens its session synchronously inline"
    ),
    "deploy_provider_app": "ProviderService.deploy_provider_app — same shape",
    "get_reconciliation_status": (
        "ProviderLifecycleService.get_reconciliation_status — same shape"
    ),
    "get_object_info": (
        "ProviderService.get_provider — a proxy for the provider HTTP fetch, "
        "which the resolver cannot see through infrastructure.http_client.get"
    ),
    "handle_provider_discovery": (
        "ProviderService.upsert_provider_from_discovery — same shape"
    ),
    "reconcile_chat_replies": (
        "world_integration_service.reconcile_unpersisted_chat_replies — a "
        "module-level function, not a JobService method; same shape"
    ),
    "parse_model_url": (
        "ExternalModelService.parse_model_url — provider HTTP, needs a real await"
    ),
    "get_civitai_enums": (
        "ExternalModelService.get_civitai_enums — provider HTTP, needs a real await"
    ),
    "get_civitai_tags": (
        "ExternalModelService.get_civitai_tags — provider HTTP, needs a real await"
    ),
    "search_civitai": (
        "ExternalModelService.search_civitai — provider HTTP, needs a real await"
    ),
    "search_huggingface": (
        "ExternalModelService.search_huggingface — provider HTTP, needs a real await"
    ),
    # Known false positive, deliberately kept. Pure in-memory event
    # construction plus event_bus.publish, which bottoms out at an
    # uncontended asyncio.Lock (core/events.py:308) — no DB, no file, no HTTP.
    "receive_sync_progress": (
        "EventBus.publish — no real suspension, and none needed: builds an Event "
        "from the request and publishes it. Nothing here touches the database "
        "or the filesystem, so there is nothing to move off the loop."
    ),
    # Not a defect either. One dict lookup under an uncontended
    # asyncio.Lock in infrastructure/worker_registry._get_live_worker.
    "get_worker_status": (
        "worker_registry._get_live_worker — one dict lookup plus an "
        "asyncio.Lock acquire that does not yield on an uncontended lock. "
        "Allowlisted rather than converted because there is no work to move."
    ),
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


# `Owner.method` / `module.function`, as written in a register reason.
_QUALIFIED_SUBJECT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)")


def _reason_subject(reason: str) -> str | None:
    """The `Owner.method` a register reason is about, if it names one."""
    match = _QUALIFIED_SUBJECT.search(reason)
    return f"{match.group(1)}.{match.group(2)}" if match else None


@pytest.mark.parametrize(
    "name,reason",
    [
        *sorted((n, r) for n, r in SYNC_CHAINED.items()),
        *sorted((n, r) for n, r in AWAIT_CHAINED_TO_SYNC_SERVICE.items()),
    ],
)
def test_every_register_reason_names_a_method_that_still_exists(name, reason):
    """The register's *subject* must still resolve, not just the route name.

    The two guards above only ask "does a route with this name still exist?",
    which passes for a reason that has rotted underneath it. Both registers are
    read as claims about a specific callee, and a claim about a callee that has
    been renamed, moved or deleted is worse than no claim at all: it reads as
    current and hides the route from the invariant. Seven reasons here were
    already wrong that way when this check was added — `create_job` said it had
    to await `queue_manager.enqueue`, which stopped being the whole story when
    `JobService.create_job` started awaiting `asyncio.to_thread`, and
    `ModelServiceV2.get_provider_statuses`, `ModelServiceV2.
    update_batch_sync_progress`, `ModelServiceV2.register_discovered_models`,
    `ProviderService.get_modal_stats`, `ProviderService.get_sync_status`,
    `ProviderService.get_provider_models`, `ProviderService.deploy_app` and
    `ProviderService.get_reconciliation_status` all named methods that do not
    exist under those names.

    The subject must also still be an `async def`: an entry about a callee that
    has since been made synchronous describes a chain that can no longer exist,
    and the route belongs in `CONVERTED` instead.
    """
    subject = _reason_subject(reason)
    assert subject, (
        f"the allowlist entry for `{name}` does not name a resolvable "
        "`Owner.method`, so nothing can check whether the reason is still true"
    )

    callees = FUNCTION_INDEX.get(subject)
    assert callees, (
        f"the allowlist entry for `{name}` is about `{subject}`, which is not a "
        "function in any searched package. The reason no longer describes the "
        "route: re-derive it, or delete the entry."
    )
    assert any(isinstance(c, ast.AsyncFunctionDef) for c in callees), (
        f"the allowlist entry for `{name}` is about `{subject}`, which is no "
        "longer `async def`. If it was made synchronous, the route it chains "
        "to should now be a plain `def`: convert it and move the entry to "
        "CONVERTED."
    )
