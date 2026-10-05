"""Rules for the batch endpoints in `api/routes`, not a list of their fixes.

Three things went wrong in the model provider-sync batch endpoints, and none of
them is visible from the endpoint's happy path:

* an unbounded `list` body. `BatchUpdateRequest.updates` and
  `BatchSyncProgressRequest.models` both took any length the client sent. The
  codebase already has the guard for this — `require_batch_size` in
  `core/upload_validation.py`, used by `api/routes/generation.py` and twice in
  `api/routes/files.py` — and these two were the batch endpoints that omitted
  it.

* a per-item loop that ran inline on the event loop. Both handlers looped over
  the body calling `service.update_provider_file_status`, which is a
  synchronous upsert plus commit. `provider_core/reconciliation.py` sends 500-row
  chunks concurrently, so at the cap this was thousands of blocking commits
  serialised against every other request.

* a `get_file_ids_by_storage_paths([])` with the comment "we can pass empty list
  to get all of them". `_iter_file_model_paths` only adds a `WHERE` clause when
  the list is non-empty, so every batch sync-progress request materialised the
  entire model library through a two-join `select(ModelFile, ModelVersion,
  ModelV2).all()` and then split every path in it on `/`.

The bounds tests here are static and sweep `api/routes` for the *shape* of the
defect rather than naming the two endpoints, so the next unbounded batch body
fails too. `BATCH_BODY_FIELDS` is the vocabulary; a field that means "a list of
things to process" belongs in it.
"""

import ast
import inspect
import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from api.routes.models import provider_sync as provider_sync_module
from infrastructure.repositories import model_repo_v2 as model_repo_module

ROUTES_DIR = Path(__file__).resolve().parents[1] / "api" / "routes"

# Body field names that mean "a batch the handler processes item by item".
# Anything added to this set is required to carry `max_length` in its model and
# to be bounded in the handler that consumes it. Deliberately excludes `items`
# and other vague plurals: those are how response models name their lists, and
# this sweep only knows about request bodies.
BATCH_BODY_FIELDS = {"updates", "files", "paths", "workflows", "models"}

# Batch list fields that predate this sweep and are left as they are. Each needs
# a reason: this is a register of known debt, not a place to hide exceptions.
PRE_EXISTING_BATCH_FIELDS = {
    "generation.py:GenerateBatchRequest.workflows": (
        "the 400-with-BATCH_TOO_LARGE shape is the contract: "
        "`test_event_loop_blocking.py::TestGenerateBatchCap` pins it, and a "
        "model-level `max_length` would answer 422 from Pydantic during "
        "validation instead, before the handler runs. So this one is bounded in "
        "the handler only, deliberately — the model-level cap the rule asks for "
        "is not always the right layer."
    ),
    "files.py:BatchDeleteRequest.files": (
        "bounded, but in the handler only: batch_delete_endpoint calls "
        "require_batch_size(req.files, MAX_BATCH_ITEMS, field=\"files\"). The "
        "list is still parsed and validated before that runs, so a 1e6-entry "
        "body reaches the endpoint."
    ),
    "files.py:BatchMetadataRequest.paths": (
        "bounded, but in the handler only: batch_get_metadata calls "
        "require_batch_size(request.paths, MAX_BATCH_ITEMS, field=\"paths\"), "
        "same shape as above."
    ),
    "files.py:BatchDownloadRequest.files": (
        "bounded, but in the handler only: batch_download checks "
        "`len(req.files) > MAX_EXPORT_FILES` inline and raises the same "
        "UploadValidationError by hand."
    ),
    "provider_sync.py:RegisterDiscoveredRequest.files": (
        "unbounded at both layers: no model cap and no handler guard, so a "
        "worker can name an arbitrary number of discovered files and get four "
        "DB rows written for each. Pre-existing and deliberately left alone in "
        "this pass — nothing asserts the caller's batch size, so imposing "
        "MAX_BATCH_ITEMS here could reject a legitimate first-run "
        "reconciliation of a large provider. Fix it with the worker in the "
        "loop, not from this side."
    ),
}


def _request_models():
    """Yield (path, class node) for every pydantic model under api/routes."""
    for path in sorted(ROUTES_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(ast.unparse(base) == "BaseModel" for base in node.bases):
                continue
            yield path, node


def _list_fields(class_node):
    """Yield (field name, annotation source, whole-statement source)."""
    for stmt in class_node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            yield stmt.target.id, ast.unparse(stmt.annotation), ast.unparse(stmt)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    # `x = Field(list[...])` — the annotation lives in the call.
                    annotation = ast.unparse(stmt.value) if stmt.value else ""
                    yield target.id, annotation, ast.unparse(stmt)


def _handlers_using_models():
    """Yield (path, handler node, set of request model names in its signature)."""
    for path in sorted(ROUTES_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            params = {
                ast.unparse(a.annotation)
                for a in node.args.args
                if a.annotation is not None
            }
            yield path, node, params


def _batch_fields(class_node, path):
    """The batch-named list fields on one request model, minus known debt."""
    found = set()
    for name, annotation, _source in _list_fields(class_node):
        if name not in BATCH_BODY_FIELDS:
            continue
        if "list[" not in annotation and "List[" not in annotation:
            continue
        if f"{path.name}:{class_node.name}.{name}" in PRE_EXISTING_BATCH_FIELDS:
            continue
        found.add(name)
    return found


def _handler_bounds(node):
    """Batch field names this handler bounds, by either accepted mechanism.

    Two shapes count as bounded:

    * `require_batch_size(items, LIMIT, field="items")` — the shared guard, used
      by `api/routes/files.py` and `api/routes/generation.py`;
    * an inline `len(...items) > LIMIT` comparison — what `batch_download` does
      against `MAX_EXPORT_FILES`, raising the same `UploadValidationError` by
      hand.
    """
    bounded = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        if ast.unparse(call.func).endswith("require_batch_size"):
            bounded |= {
                kw.value.value
                for kw in call.keywords
                if kw.arg == "field" and isinstance(kw.value, ast.Constant)
            }
    for compare in ast.walk(node):
        if not isinstance(compare, ast.Compare):
            continue
        if not any(isinstance(op, ast.Gt) for op in compare.ops):
            continue
        rendered = ast.unparse(compare)
        if "len(" not in rendered:
            continue
        bounded |= {
            name
            for name in BATCH_BODY_FIELDS
            if f".{name}" in rendered or f"({name})" in rendered or f"[{name}]" in rendered
        }
    return bounded


def test_batch_list_bodies_are_bounded():
    """A batch body must declare its own ceiling in the model.

    `require_batch_size` in the handler is the guard that runs before any
    per-item work, but it only sees a body Pydantic has already parsed and
    validated. A 1e6-entry `list` was materialised — and every element
    validated — before the handler could refuse it. The model-level
    `max_length` is what makes the refusal cheap.

    Not universal, and `PRE_EXISTING_BATCH_FIELDS` is where that is said out
    loud: where the 400-with-`BATCH_TOO_LARGE` shape is itself the contract a
    caller branches on, a model cap would answer 422 instead and change the API.
    """
    unbounded = []
    for path, class_node in _request_models():
        for name in _batch_fields(class_node, path):
            source = next(s for n, _a, s in _list_fields(class_node) if n == name)
            if "max_length" not in source:
                unbounded.append(
                    f"{path.relative_to(ROUTES_DIR.parent.parent)}:{class_node.lineno} "
                    f"{class_node.name}.{name}"
                )

    assert not unbounded, (
        "these request models take a batch list with no ceiling in the model. "
        "Add `Field(max_length=...)` — the handler-level guard runs too late to "
        "stop the body being parsed:\n  " + "\n  ".join(unbounded)
    )


def test_batch_bodies_are_guarded_before_any_per_item_work():
    """A bounded model is not enough; the handler must also refuse oversize.

    Two different limits with two different failure modes: the model's is a 422
    from Pydantic during validation, the handler's is the shared
    `BATCH_TOO_LARGE` 400 that every other batch endpoint returns. Callers
    (`provider_core/reconciliation.py` above all) branch on the status code, so
    the shared shape is the one that has to be there.
    """
    handlers = list(_handlers_using_models())

    missing = []
    for path, class_node in _request_models():
        batch_fields = _batch_fields(class_node, path)
        if not batch_fields:
            continue
        for hpath, hnode, params in handlers:
            if hpath != path:
                continue
            if not any(class_node.name in p for p in params):
                continue
            for field in batch_fields - _handler_bounds(hnode):
                missing.append(
                    f"{hpath.relative_to(ROUTES_DIR.parent.parent)}:{hnode.lineno} "
                    f"{hnode.name} does not bound {class_node.name}.{field} "
                    f"(no `require_batch_size(..., field=\"{field}\")` and no "
                    "`len(...) > LIMIT` comparison)"
                )

    assert not missing, (
        "these handlers take a batch body with no bound of their own, so there "
        "is nothing to stop the per-item loop:\n  " + "\n  ".join(sorted(missing))
    )


def test_the_registered_pre_existing_batch_fields_still_exist():
    """A debt register entry that no longer matches anything stops registering.

    Same shape as the guards in `test_event_loop_invariant.py`: if the field is
    renamed or the endpoint is fixed, this entry must go with it, because a
    stale entry silently stops describing a real gap.
    """
    seen = {
        f"{path.name}:{class_node.name}.{name}"
        for path, class_node in _request_models()
        for name, _annotation, _source in _list_fields(class_node)
        if name in BATCH_BODY_FIELDS
    }
    missing = sorted(set(PRE_EXISTING_BATCH_FIELDS) - seen)
    assert not missing, (
        "these PRE_EXISTING_BATCH_FIELDS entries no longer name a batch list "
        f"field; delete them so the register keeps meaning something: {missing}"
    )


def _assert_no_await(obj, label):
    """Fail if `obj`'s body contains an `await` or a nested thread hop.

    AST rather than source text: a docstring explaining that the body *must not*
    await would otherwise satisfy a substring search forever, which is the
    regression these checks exist to catch.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
    awaits = [ast.unparse(n.value) for n in ast.walk(tree) if isinstance(n, ast.Await)]
    assert not awaits, f"{label} runs on a worker thread but awaits: {awaits}"
    hops = [
        ast.unparse(n.func)
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("to_thread")
    ]
    assert not hops, f"{label} is already the worker body; it must not hop again: {hops}"


class TestBatchStatusUpdateContract:
    """`POST /api/v2/models/providers/batch-status-update`."""

    ENDPOINT = "/api/v2/models/providers/batch-status-update"

    def test_rejects_an_oversized_batch(self, client, monkeypatch):
        """The shared BATCH_TOO_LARGE shape, with `updates` as the field."""
        monkeypatch.setattr(provider_sync_module, "MAX_BATCH_ITEMS", 2)

        response = client.post(
            self.ENDPOINT,
            json={
                "provider_id": "modal-primary",
                "updates": [
                    {"file_id": "1", "status": "ready"},
                    {"file_id": "2", "status": "ready"},
                    {"file_id": "3", "status": "ready"},
                ],
            },
        )

        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "BATCH_TOO_LARGE"
        assert body["field"] == "updates"

    def test_declares_a_partial_failure_instead_of_answering_a_bare_200(
        self, client, monkeypatch
    ):
        """A batch that partly failed must say so.

        Not a bare `{"updated": 2, "failed": 1}`: a caller cannot tell that
        apart from a clean run of two. Not a 4xx/5xx either — its one production
        caller, `provider_core.reconciliation.batch_update_file_status_v2`,
        counts *any* non-200 as a whole-chunk loss (`return 0, len(batch)`) and
        does not retry, so raising would discard the record of the rows that did
        land. The `source`/`degraded` convention from `api/routes/files.py` is
        the precedent: 200, and declare the degradation in the body.
        """
        monkeypatch.setattr(
            provider_sync_module,
            "_apply_batch_status_updates",
            lambda session, provider_key, updates: (2, 1, {"ready": 2}),
        )

        response = client.post(
            self.ENDPOINT,
            json={
                "provider_id": "modal-primary",
                "updates": [{"file_id": "1", "status": "ready"}],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["updated"] == 2
        assert body["failed"] == 1
        assert body["status"] != "ok"
        assert body["degraded"] is True

    def test_a_clean_batch_is_not_marked_degraded(self, client, monkeypatch):
        monkeypatch.setattr(
            provider_sync_module,
            "_apply_batch_status_updates",
            lambda session, provider_key, updates: (2, 0, {"ready": 2}),
        )

        response = client.post(
            self.ENDPOINT,
            json={
                "provider_id": "modal-primary",
                "updates": [{"file_id": "1", "status": "ready"}],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["updated"] == 2
        assert "degraded" not in body

    def test_the_worker_body_never_re_enters_the_event_loop(self):
        """The blocking body cannot `await`.

        A leftover `asyncio.to_thread` or `await` inside it would mean the work
        was never actually moved off the loop — the handler's `await
        asyncio.to_thread(...)` would then only be offloading something that
        yields again.
        """
        _assert_no_await(
            provider_sync_module._apply_batch_status_updates,
            "api.routes.models.provider_sync._apply_batch_status_updates",
        )


class TestBatchSyncProgressContract:
    """`POST /api/v2/models/sync-progress/batch`."""

    ENDPOINT = "/api/v2/models/sync-progress/batch"

    @pytest.fixture
    def spy(self, monkeypatch):
        calls: list[list[str]] = []
        real = model_repo_module.ModelRepositoryV2.get_file_ids_by_storage_paths

        def recording(self, storage_paths):
            calls.append(list(storage_paths))
            return real(self, storage_paths)

        monkeypatch.setattr(
            model_repo_module.ModelRepositoryV2,
            "get_file_ids_by_storage_paths",
            recording,
        )
        return calls

    def test_looks_up_only_the_paths_the_request_asked_for(self, client, spy):
        """The empty-list call was a full-library scan.

        `_iter_file_model_paths` adds its `WHERE ... IN (...)` only when the
        list is non-empty, so `get_file_ids_by_storage_paths([])` returned
        *every* ModelFile joined to its version and model — once per request.
        """
        response = client.post(
            self.ENDPOINT,
            json={
                "provider_id": "modal-primary",
                "models": [
                    {
                        "model_name": "does-not-exist.safetensors",
                        "directory": "checkpoints",
                        "status": "completed",
                    }
                ],
            },
        )

        assert response.status_code == 200
        assert spy, "the endpoint never resolved storage paths at all"
        for paths in spy:
            assert paths, (
                "an empty path list is passed to "
                "get_file_ids_by_storage_paths, which drops the WHERE clause and "
                "materialises the entire model library"
            )
            assert paths == ["models/checkpoints/does-not-exist.safetensors"]

    def test_rejects_an_oversized_batch(self, client, monkeypatch):
        monkeypatch.setattr(provider_sync_module, "MAX_BATCH_ITEMS", 1)

        response = client.post(
            self.ENDPOINT,
            json={
                "provider_id": "modal-primary",
                "models": [
                    {"model_name": "a.safetensors", "directory": "checkpoints", "status": "completed"},
                    {"model_name": "b.safetensors", "directory": "checkpoints", "status": "completed"},
                ],
            },
        )

        assert response.status_code == 400
        body = response.json()
        assert body["code"] == "BATCH_TOO_LARGE"
        assert body["field"] == "models"

    def test_the_worker_body_never_re_enters_the_event_loop(self):
        _assert_no_await(
            provider_sync_module._apply_batch_sync_progress,
            "api.routes.models.provider_sync._apply_batch_sync_progress",
        )

    def test_completed_reports_the_size_and_pending_does_not(self, client, monkeypatch):
        """The status mapping keeps the pre-thread argument set exactly.

        `completed` reported a `size_bytes`; `failed` and `pending` did not. The
        dict lookup that replaced the if/elif chain has to preserve that, or the
        batch starts writing sizes the worker never reported.
        """
        recorded: list[dict] = []
        monkeypatch.setattr(
            model_repo_module.ModelRepositoryV2,
            "get_file_ids_by_storage_paths",
            lambda self, paths: {
                "models/checkpoints/a.safetensors": 1,
                "models/checkpoints/b.safetensors": 2,
                "models/checkpoints/c.safetensors": 3,
            },
        )
        monkeypatch.setattr(
            provider_sync_module,
            "get_model_service_v2",
            MagicMock(
                return_value=MagicMock(
                    update_provider_file_status=lambda **kw: recorded.append(kw)
                )
            ),
            raising=False,
        )

        response = client.post(
            self.ENDPOINT,
            json={
                "provider_id": "modal-primary",
                "models": [
                    {"model_name": "a.safetensors", "directory": "checkpoints", "status": "completed", "size_bytes": 5},
                    {"model_name": "b.safetensors", "directory": "checkpoints", "status": "pending", "size_bytes": 7},
                    {"model_name": "c.safetensors", "directory": "checkpoints", "status": "failed", "size_bytes": 9},
                ],
            },
        )

        assert response.status_code == 200
        assert response.json()["updated"] == 3
        by_name = {kw["storage_path"]: kw for kw in recorded}
        assert by_name["models/checkpoints/a.safetensors"]["size_bytes"] == 5
        assert by_name["models/checkpoints/b.safetensors"]["size_bytes"] is None
        assert by_name["models/checkpoints/c.safetensors"]["size_bytes"] is None
        assert by_name["models/checkpoints/a.safetensors"]["status"] == "ready"
        assert by_name["models/checkpoints/b.safetensors"]["status"] == "pending"
        assert by_name["models/checkpoints/c.safetensors"]["status"] == "failed"