"""Search terms are data, not LIKE patterns.

`LIKE` reads `%` as "any run of characters" and `_` as "any single character".
Every one of these call sites used to build its pattern by f-string
interpolation — `f"%{search}%"` — so a user typing `100%` or `a_b` got a match
set they never asked for and had no way to see it had happened. The value was
always bound as a parameter, so this was never an injection hole; it is a
correctness hole, and it is silent.

Two things are asserted here, and both are needed:

* the rule, end to end — a search for a literal `100%` returns only rows that
  contain a literal `100%`, at the routes a user actually types into;
* the *clause*, not just the escaping — `core.sql_search.escape_like` on its own
  does nothing, because an escaped pattern with no `ESCAPE` clause is matched
  literally (backslash, percent, underscore) and matches almost nothing. The
  common half-fix, which passes these tests' first half and silently breaks
  every search in the app, is therefore worth pinning explicitly.
"""
import ast
from pathlib import Path

import pytest
from sqlmodel import Session, select

from core.entities import (
    Asset,
    AssetTag,
    Chat,
    Character,
    CharacterMemory,
    Location,
    Prompt,
)
from core.sql_search import (
    LIKE_ESCAPE_CHAR,
    escape_like,
    like_contains,
    like_startswith,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── The helper ─────────────────────────────────────────────────────────────


def test_escape_like_neutralises_all_three_metacharacters():
    assert escape_like("100%") == r"100\%"
    assert escape_like("a_b") == r"a\_b"
    assert escape_like(r"back\slash") == r"back\\slash"


def test_escape_like_escapes_the_escape_character_first():
    """Order matters: escaping `%` first would re-escape the escape char."""
    assert escape_like(r"\%") == r"\\\%"


def test_escape_like_leaves_ordinary_text_alone():
    assert escape_like("portrait of a knight") == "portrait of a knight"


def test_pattern_builders_keep_their_wildcards_outside_the_escaping():
    assert like_contains("100%") == r"%100\%%"
    assert like_startswith("a_b") == r"a\_b%"


def test_pattern_builders_still_match_substrings_and_prefixes():
    """Escaping must not turn a substring search into an equality search."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.connect() as conn:
        conn.execute(text("CREATE TABLE t (v TEXT)"))
        for value in ("100% cotton", "a_b", "aXb", "cotton 100"):
            conn.execute(text("INSERT INTO t VALUES (:v)"), {"v": value})

        contained = conn.execute(
            text("SELECT v FROM t WHERE v LIKE :p ESCAPE '" + LIKE_ESCAPE_CHAR + "'"),
            {"p": like_contains("100%")},
        ).scalars().all()
        prefixed = conn.execute(
            text("SELECT v FROM t WHERE v LIKE :p ESCAPE '" + LIKE_ESCAPE_CHAR + "'"),
            {"p": like_startswith("a_b")},
        ).scalars().all()

    assert contained == ["100% cotton"]
    assert prefixed == ["a_b"]


# ── The rule, end to end ────────────────────────────────────────────────────


@pytest.fixture
def character(session: Session):
    char = Character(name="Aria")
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


@pytest.fixture
def searchable_assets(session: Session):
    rows = [
        Asset(filename="100% real.png", relative_path="a/100% real.png"),
        Asset(filename="cocoa_100.png", relative_path="b/cocoa_100.png"),
        Asset(filename="nothing_special.png", relative_path="c/nothing_special.png"),
    ]
    for row in rows:
        session.add(row)
    session.commit()
    return rows


def test_gallery_search_for_100_percent_returns_only_literal_matches(
    client, session, searchable_assets
):
    """"100%" must not degrade into "anything containing 100".

    Without escaping, `%100%%` matches `cocoa_100.png` too — a result the user
    cannot distinguish from a correct one, and which silently grows as the
    library grows.
    """
    hits = client.get("/api/files", params={"directory": "output", "search": "100%", "limit": 50}).json()

    names = {f["name"] for f in hits["files"]}
    assert "100% real.png" in names
    assert "cocoa_100.png" not in names, (
        "searching for the literal '100%' returned a row that does not contain it"
    )


def test_gallery_search_still_finds_the_ordinary_term(client, session, searchable_assets):
    """Escaping must not regress the case it is layered on top of."""
    hits = client.get("/api/files", params={"directory": "output", "search": "cocoa", "limit": 50}).json()
    assert {f["name"] for f in hits["files"]} == {"cocoa_100.png"}


def test_gallery_search_for_an_underscore_is_a_literal_underscore(client, session):
    session.add(Asset(filename="a_b.png", relative_path="d/a_b.png"))
    session.add(Asset(filename="aXb.png", relative_path="e/aXb.png"))
    session.commit()

    hits = client.get("/api/files", params={"directory": "output", "search": "a_b", "limit": 50}).json()

    names = {f["name"] for f in hits["files"]}
    assert "a_b.png" in names
    assert "aXb.png" not in names, "'_' matched as a single-character wildcard"


def test_gallery_search_is_not_a_hard_failure_for_any_term(client, session, searchable_assets):
    """Regression guard for `cast(str)` vs `cast(String)`.

    `Column.cast()` takes a TypeEngine. The Python builtin raised `TypeError`,
    which the caller's `except` turned into 503 "File listing is unavailable" —
    so on the live site *every* gallery search, for *every* term, was a hard
    failure, and the no-search path was unaffected, which is why it survived.
    """
    for term in ("test", "100%", "a_b", "\\", "%", "_", ""):
        response = client.get("/api/files", params={"directory": "output", "search": term, "limit": 5})
        assert response.status_code == 200, f"search for {term!r} -> {response.status_code}"


def test_a_literal_backslash_in_the_search_term_is_not_an_error(session):
    """`%\\\\%` must reach the engine as a pattern with an ESCAPE clause.

    Without one, the backslash is compared literally and the query either
    matches nothing or is rejected outright.
    """
    session.add(Asset(filename=r"odd\name.png", relative_path="f/odd.png"))
    session.add(Asset(filename="oddname.png", relative_path="g/oddname.png"))
    session.commit()

    from sqlalchemy import String

    hits = session.exec(
        select(Asset).where(
            Asset.filename.ilike(like_contains("\\"), escape=LIKE_ESCAPE_CHAR)
            | Asset.metadata_.cast(String).ilike(like_contains("\\"), escape=LIKE_ESCAPE_CHAR)
        )
    ).all()
    assert isinstance(hits, list)  # the query executed; no "no such escape" error


def test_location_search_treats_underscore_literally(client, session):
    session.add(Location(name="a_b", description="underscored"))
    session.add(Location(name="aXb", description="not underscored"))
    session.commit()

    found = client.get("/api/v2/locations/search", params={"q": "a_b"}).json()

    assert [loc["name"] for loc in found] == ["a_b"]


def test_chat_search_treats_percent_literally(client, session, character):
    session.add(Chat(name="100% done", chat_type="roleplay", character_id=character.id))
    session.add(Chat(name="100 done", chat_type="roleplay", character_id=character.id))
    session.commit()

    found = client.get("/api/v2/chats", params={"q": "100%"}).json()

    assert [c["name"] for c in found] == ["100% done"]


def test_prompt_search_treats_underscore_literally(client, session):
    session.add(Prompt(name="a_b", text="body"))
    session.add(Prompt(name="aXb", text="body"))
    session.commit()

    found = client.get("/api/prompts", params={"q": "a_b"}).json()

    assert [p["name"] for p in found["prompts"]] == ["a_b"]


def test_character_repository_search_treats_percent_literically(session, character):
    """`func.lower(col).like(pattern)` — a different call shape, same rule."""
    from infrastructure.repositories.character_repo import CharacterRepository

    session.add(Character(name="Aria 100% sure", description="d"))
    session.add(Character(name="Aria 100 sure", description="d"))
    session.commit()

    found = CharacterRepository(session).search("100%")

    assert [c.name for c in found] == ["Aria 100% sure"]


def test_keyword_fallback_of_semantic_memory_search_is_escaped(session, character):
    """`services/rag_pipeline.search_memories` keyword branch, no vector needed."""
    from services.rag_pipeline import search_memories

    session.add(CharacterMemory(character_id=character.id, content="she was 100% certain"))
    session.add(CharacterMemory(character_id=character.id, content="she was 100 certain"))
    session.commit()

    found = search_memories(session, character.id, "100%")

    assert [m.content for m in found] == ["she was 100% certain"]


@pytest.fixture
def tagged_assets(session: Session):
    """`list_tag_vocabulary` joins to a live asset, so the tags need one."""
    asset = Asset(filename="tagged.png", relative_path="t/tagged.png")
    session.add(asset)
    session.commit()
    for tag in ("a_b", "aXb", "100% real", "100 real"):
        session.add(AssetTag(asset_id=asset.id, tag=tag))
    session.commit()
    return asset


def test_tag_vocabulary_prefix_treats_underscore_literally(session, tagged_assets):
    """The anchored prefix is the autocomplete path, so a wildcard here is very visible."""
    from services.tag_service import list_tag_vocabulary

    found = list_tag_vocabulary(session, prefix="a_b")
    assert {t["tag"] for t in found} == {"a_b"}


def test_tag_vocabulary_contains_treats_percent_literally(session, tagged_assets):
    from services.tag_service import list_tag_vocabulary

    found = list_tag_vocabulary(session, query="100%")
    assert {t["tag"] for t in found} == {"100% real"}


def test_tag_vocabulary_escaping_does_not_destroy_normal_prefix_search(session, tagged_assets):
    """Escaping must not break the ordinary case it is layered onto."""
    from services.tag_service import list_tag_vocabulary

    assert {t["tag"] for t in list_tag_vocabulary(session, prefix="a")} == {"a_b", "aXb"}


# ── Structural guard ───────────────────────────────────────────────────────
#
# A behavioural test only covers the sites somebody remembered to write one for.
# The 17 call sites this defect lived at were found by grepping, so the durable
# test is grep-shaped too: any LIKE in application code whose pattern is built by
# interpolating something other than a literal must be gone.


# Attribute names, not call spellings: `".like(".lstrip(".")` is `"like("`, which
# no `ast.Attribute.attr` ever equals, so the sweep below used to collect zero
# calls and its test passed vacuously against every unescaped pattern in the
# tree.
_LIKE_ATTRS = {"like", "ilike", "not_like", "not_ilike"}


def _like_pattern_arguments(path: Path) -> list[tuple[int, str, bool]]:
    """`(lineno, pattern_source, is_plain_literal)` for every LIKE call in `path`.

    Resolves one level of indirection. The guard used to read only the literal
    argument text, so `pattern = f"%{entity_id}%"` assigned two lines above the
    call was invisible to it — which is exactly how `reference_cleanup` shipped
    an unescaped pattern next to this file. A `Name` argument is therefore
    looked up in the enclosing function's simple assignments.

    `is_plain_literal` separates the two things the rule must not conflate: a
    literal `"%Auto-discovered%"` interpolates nothing and is fine, while an
    f-string, a concatenation or a `.format()` call splices data into the
    pattern and is not.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str, bool]] = []

    def _is_interpolated(node: ast.expr) -> bool:
        if isinstance(node, ast.Constant):
            return False
        if isinstance(node, ast.JoinedStr):
            return True
        if isinstance(node, ast.BinOp):
            return True
        if isinstance(node, ast.Call):
            return True
        return True

    class Scope:
        """One scope's simple `name = expression` assignments."""

        def __init__(self, body: list[ast.stmt]):
            self.sources: dict[str, ast.expr] = {}
            for stmt in body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            self.sources[target.id] = stmt.value

        def resolve(self, node: ast.expr) -> ast.expr:
            if isinstance(node, ast.Name) and node.id in self.sources:
                return self.sources[node.id]
            return node

    def _collect(scope: Scope, node: ast.AST, found: list):
        for inner in ast.walk(node):
            if not (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr in _LIKE_ATTRS
                and inner.args
            ):
                continue
            pattern = scope.resolve(inner.args[0])
            found.append(
                (inner.lineno, ast.unparse(pattern), not _is_interpolated(pattern))
            )

    module_scope = Scope(tree.body)
    _collect(module_scope, tree, found)
    # Function bodies: a nested scope's assignments shadow the module's, so the
    # nested scope also gets its own pass over its own body.
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _collect(Scope(node.body), node, found)

    return found


def test_no_application_like_call_builds_its_pattern_by_interpolation():
    """Patterns must come from `core.sql_search`, never from an f-string.

    A literal `"%Auto-discovered%"` is fine — nothing is interpolated, so there
    is no user input to be confused by. What cannot be fine is any pattern that
    splices a value into the string: a `%` or `_` in that value then acts as a
    wildcard, silently widening the match set.
    """
    offenders: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[0] in {"tests", ".venv"} or "__pycache__" in rel.parts:
            continue
        for lineno, pattern, is_plain_literal in _like_pattern_arguments(path):
            if "%" not in pattern:
                continue
            if is_plain_literal:
                continue
            offenders.append(f"{rel}:{lineno} {pattern}")

    assert not offenders, (
        "LIKE pattern built by string interpolation, so '%'/'_' in the search "
        "term act as wildcards:\n  " + "\n  ".join(offenders)
    )


def test_every_escaped_like_call_passes_the_escape_clause():
    """Escaping without `ESCAPE '\\'` matches nothing; the clause is half the fix.

    A pattern built by `core.sql_search` has to reach the database with the same
    escape character, or the backslashes are compared literally.
    """
    offenders: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[0] in {"tests", ".venv"} or "__pycache__" in rel.parts:
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))

        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"like", "ilike"}
            ):
                continue
            if not node.args:
                continue
            first = ast.unparse(node.args[0])
            if "like_contains" not in first and "like_startswith" not in first:
                continue
            escape_kw = [kw for kw in node.keywords if kw.arg == "escape"]
            if not escape_kw or ast.unparse(escape_kw[0].value) != "LIKE_ESCAPE_CHAR":
                offenders.append(f"{rel}:{node.lineno} {first}")

    assert not offenders, (
        "escaped pattern with no ESCAPE clause — every such search silently "
        "returns nothing:\n  " + "\n  ".join(offenders)
    )


def test_raw_sql_like_fragments_carry_an_escape_clause():
    """The `.like()` guard cannot see a `text()` fallback — this closes that hole.

    `JobRepository.search_prompts` builds its SQLite pattern with `text()` and a
    bound parameter, so the two guards above both walked straight past it: a
    search for `100%` matched `100 percent` and no test noticed. Only string
    literals handed to `text()` are inspected, so a docstring that merely
    mentions LIKE cannot trip this.
    """
    offenders: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        if rel.parts[0] in {"tests", ".venv"} or "__pycache__" in rel.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "text"
            ):
                continue
            for argument in node.args:
                if not isinstance(argument, ast.Constant) or not isinstance(
                    argument.value, str
                ):
                    continue
                fragment = argument.value
                if "LIKE" not in fragment.upper():
                    continue
                if "ESCAPE" not in fragment.upper():
                    offenders.append(f"{rel}:{node.lineno}")
                    continue
                # A raw LIKE fragment cannot interpolate its pattern without
                # giving up the ESCAPE clause's escape character, so reject it
                # here rather than at a call site nobody wrote a test for.
                if "like_contains" in fragment or "like_startswith" in fragment:
                    offenders.append(f"{rel}:{node.lineno} pattern built by interpolation")

    assert not offenders, (
        "raw SQL LIKE with no ESCAPE clause, or a pattern spliced into "
        "SQL:\n  " + "\n  ".join(offenders)
    )


def test_the_helper_module_is_reachable_without_a_database():
    """`core.sql_search` must stay dependency-free so `infrastructure` can use it."""
    import core.sql_search as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    imports = {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(m.split(".")[0] in {"sqlalchemy", "sqlmodel", "api", "services"} for m in imports)
