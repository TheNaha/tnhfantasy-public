"""No route may take a SQLModel table class as its request body.

A `table=True` model used as a FastAPI request body has two defects at once,
and both were live in this codebase:

  1. Every column becomes a client-writable field, including the primary key.
     `POST /api/v2/characters {"name":"x","id":"CLIENT-CHOSE-THIS"}` persisted
     the caller's id, and `create_character` propagated it into the second row
     it creates, the character's `Collection`.
  2. The body is never validated, because SQLModel's table classes are not
     pydantic-validated on construction. A missing NOT NULL column reached
     `session.add()` and surfaced as a 500, so a malformed client request read
     as a server fault. Verified on the live stack before the fix:
     `POST /api/v2/characters {}` -> 500; after -> 422.

Seven routes were affected. The fix was seven `XxxCreate(BaseModel)` DTOs; this
test is what stops the eighth. A per-route allowlist would have needed a new
entry every time a create endpoint was added, which is the same reason the
event-loop invariant test only ever pinned the routes that existed when it was
written.

The rule is structural, not enumerated: a route parameter annotated with a
class whose bases include `SQLModel` is a table class by definition.
"""

import ast
from pathlib import Path

ROUTES_DIR = Path(__file__).resolve().parents[1] / "api" / "routes"


def _is_table_class(annotation: str, known_tables: set[str]) -> bool:
    """True when the annotation names a known SQLModel `table=True` class."""
    return annotation.split("[")[0].strip() in known_tables


def _collect_table_classes() -> set[str]:
    """Every persistent entity: a class with a `__tablename__`.

    Keyed on `__tablename__` rather than on `SQLModel` + `table=True`, because
    `sqlmodel.Session` is itself a `SQLModel` subclass and would otherwise be
    collected as a table — which put 272 `session: Session` parameters in the
    offender list on the first run.
    """
    entities = (ROUTES_DIR.parents[1] / "core" / "entities.py").read_text()
    tree = ast.parse(entities)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(
            isinstance(stmt, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "__tablename__"
                for t in stmt.targets
            )
            for stmt in node.body
        ):
            names.add(node.name)
    return names


def _route_bodies(tree: ast.Module) -> list[tuple[str, str, int, str, ast.AST | None]]:
    """(func_name, param_name, lineno, annotation, default) for every annotated
    parameter **of a route handler**, paired with its default so an injected
    dependency can be told apart from a request body.

    Only functions carrying an `@router.<verb>(...)` decorator are considered.
    Module-level helpers take `StoryChapter`/`Session` parameters legitimately —
    `_serialize_chapter(ch: StoryChapter)` is the ORM, not an API surface — and
    FastAPI never sees their signatures.
    """
    out = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _is_route_handler(func):
            continue
        args = func.args
        positional = [*args.posonlyargs, *args.args]
        first_defaulted = len(positional) - len(args.defaults)
        for idx, param in enumerate(positional):
            default = args.defaults[idx - first_defaulted] if idx >= first_defaulted else None
            if param.annotation is not None:
                out.append((func.name, param.arg, param.lineno, ast.unparse(param.annotation), default))
        for param, default in zip(args.kwonlyargs, args.kw_defaults):
            if param.annotation is not None:
                out.append((func.name, param.arg, param.lineno, ast.unparse(param.annotation), default))
    return out


# FastAPI verbs that carry a request body.
BODY_VERBS = {"post", "put", "patch"}


def _is_route_handler(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for dec in func.decorator_list:
        # @router.post(...) / @router.post / @some_router.post
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr in BODY_VERBS:
            return True
    return False


def test_entities_table_classes_were_found() -> None:
    """Guard: an empty table-class set would make the main test vacuous."""
    tables = _collect_table_classes()
    assert len(tables) > 30, f"only found {len(tables)} table classes; parser is broken"
    assert "Character" in tables
    assert "LorebookEntry" in tables


def test_no_route_takes_a_table_class_as_a_request_body() -> None:
    tables = _collect_table_classes()
    offenders: list[str] = []

    for path in sorted(ROUTES_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for func_name, param_name, lineno, annotation, default in _route_bodies(tree):
            if not _is_table_class(annotation, tables):
                continue
            # A path or query param is fine, and so is an injected dependency.
            # Only a parameter FastAPI resolves as the JSON body is a defect.
            if default is not None and "Depends" in ast.unparse(default):
                continue
            if param_name.endswith(("_id", "_ids")):
                continue
            offenders.append(
                f"{path.relative_to(ROUTES_DIR.parents[1])}:{lineno} "
                f"{func_name}({param_name}: {annotation})"
            )

    assert offenders == [], (
        "these routes take a SQLModel table class as their request body, which "
        "makes the primary key client-writable and turns a missing required "
        "field into a 500:\n  " + "\n  ".join(offenders)
    )
