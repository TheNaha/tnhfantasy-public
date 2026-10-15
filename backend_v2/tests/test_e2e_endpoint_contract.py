"""Every endpoint the e2e suite requests must exist in the backend.

`frontend_v2/e2e/fixtures.js` used to prefix `/api/v2` onto whatever path it was
handed. The API is not uniformly versioned — `/api/settings`, `/api/prompts` and
`/api/jobs` are not — so fourteen call sites across five specs requested routes
that do not exist:

    GET  /api/v2/settings          -> 404, the real route is /api/settings
    PUT  /api/v2/settings          -> 404
    GET  /api/v2/settings/branding -> 404   (x2, plus the POST)
    GET  /api/v2/settings/system-prompts -> 404 (x2, plus the PUT)
    GET  /api/v2/jobs/{id}         -> 404, the real route is /api/jobs/{job_id}
    POST /api/v2/prompts           -> 404, the real route is /api/prompts
    GET  /api/v2/timeline/timeline -> 404, a doubled-segment typo

Every helper in that file throws on `!res.ok()`, so those tests could not pass.
The reason this was invisible is the same reason it was cheap to introduce: the
e2e job is the one CI signal nobody reads, and it had been red (or not running)
long enough that nobody noticed which.

The fix was one resolver in `fixtures.js`, so the defect cannot recur at a call
site. This file is the other half: it reads the specs, resolves every endpoint
the way the harness now does, and asserts each one is in `app.openapi()`. It is
generated from the specs and the live route table rather than maintained by
hand, so adding a route and forgetting the spec is fine, and adding a typo is
not.

Method: an AST-free scan is not enough — the paths are built with template
literals (`` `/jobs/${jobId}` ``) and with variables. So each helper call is
located by its first string-literal-free argument, and the literal prefix is
recovered with a regex that stops at the first `${`. Where a call passes a
variable rather than a literal (`waitForJob` passes `` `/jobs/${jobId}` ``), the
template is resolved with a placeholder that is then replaced by the route
table's own parameter name, so `/jobs/{jobId}` matches `/api/jobs/{job_id}`.

Both halves of the API are covered: the *harness* (this file) and the *app*
(`test_frontend_backend_endpoint_contract.py`), because a route the app calls
wrongly is just as dead as a route the tests call wrongly.

**And the bodies are checked, not only the paths.** Checking paths was not enough,
which is the second half of why this job was red: `seedStoryChapter` posted
`{ title }` to a `ChapterCreate` that declares `content: str` as required and sets
`extra="forbid"`, so all seven chapter seeds were a 422. The path was correct, so
the path guard passed — and the e2e job went on failing with a symptom 50 tests
away from the cause. `_required_body_properties_below` therefore resolves each
`apiPost`/`apiPut`/`apiPatch` body literal, reads the operation's `requestBody`
schema out of `app.openapi()`, and requires every `required` property to be
present (or the literal to spread something in, which makes it indeterminate and
is accepted).
"""

import re
from pathlib import Path

import pytest

from api.main import app
from repo_paths import require_repo_root

E2E_DIR = require_repo_root("frontend_v2/e2e") / "frontend_v2" / "e2e"

# The harness helpers that take a path, and the HTTP method they issue. The
# method is not asserted — only that *some* operation exists at the path — but
# naming it keeps the failure message readable.
HELPERS = ("apiGet", "apiPost", "apiPut", "apiPatch", "apiDelete", "apiUpload")

# Helpers that send a request body, and the method each one issues. Only these can
# be checked against a `requestBody` schema.
BODY_HELPERS = {
    "apiPost": "post",
    "apiPut": "put",
    "apiPatch": "patch",
}

# `page.request.<verb>(...)` is the raw form, used by the cleanup registry.
RAW_VERBS = ("get", "post", "put", "patch", "delete")

# Paths the harness builds that are not backend routes at all: the websocket
# and static-asset endpoints the browser handles, and Playwright's own.
IGNORED_PREFIXES = ("ws://", "wss://", "http://", "https://", "/socket.io")


def _spec_files() -> list[Path]:
    if not E2E_DIR.is_dir():
        pytest.skip(f"e2e directory not present at {E2E_DIR}")
    return sorted(E2E_DIR.glob("*.js"))


def _routes() -> set[str]:
    return set(app.openapi()["paths"])


def _path_matches(route: str, candidate: str) -> bool:
    """Compare a resolved e2e path against a route template.

    `{job_id}` in a route matches one non-empty, slash-free segment in the
    candidate, whatever the candidate happens to call it. That is what lets
    `/api/jobs/abc123` satisfy `/api/jobs/{job_id}`.
    """
    route_parts = route.strip("/").split("/")
    cand_parts = candidate.strip("/").split("/")
    if len(route_parts) != len(cand_parts):
        return False
    for r, c in zip(route_parts, cand_parts):
        if r.startswith("{") and r.endswith("}"):
            if not c:
                return False
            continue
        if r != c:
            return False
    return True


def _resolve(path_literal: str) -> str:
    """Reproduce `resolveApiPath` from `e2e/fixtures.js`."""
    path = path_literal.strip()
    if path.endswith("/") and len(path) > 1:
        # A collection route may be written with or without its trailing slash;
        # FastAPI answers `/api/v2/providers/` and redirects `/api/v2/providers`.
        path = path[:-1]
    if path == "/api" or path.startswith("/api/"):
        return path
    return "/api/v2" + path


def _endpoints_in(text: str) -> list[tuple[int, str, str]]:
    """Every `(line, helper, raw_path)` the harness is asked to request."""
    found: list[tuple[int, str, str]] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines, 1):
        for helper in HELPERS:
            # `apiGet(page, '/settings')` and `apiGet(page, `/jobs/${id}`)`.
            for m in re.finditer(
                rf"\b{helper}\s*\(\s*page\s*,\s*(['\"`])((?:\\.|(?!\1).)*)\1",
                line,
            ):
                found.append((idx, helper, m.group(2)))
        # `page.request.get(API_BASE + path)` — the resolved form is inside the
        # helper now, so raw calls only matter where they hardcode a path.
        for verb in RAW_VERBS:
            for m in re.finditer(
                rf"page\.request\.{verb}\s*\(\s*(['\"])((?:\\.|(?!\1).)*)\1",
                line,
            ):
                found.append((idx, f"request.{verb}", m.group(2)))
    return found


def _collect() -> list[tuple[str, int, str, str, str]]:
    """`(file, line, helper, raw_path, resolved_path)` for every call site."""
    rows = []
    for spec in _spec_files():
        text = spec.read_text(encoding="utf-8")
        for line, helper, raw in _endpoints_in(text):
            if raw.startswith(IGNORED_PREFIXES) or raw in {"", "/"}:
                continue
            rows.append((spec.name, line, helper, raw, _resolve(raw)))
    return rows


CALL_SITES = _collect()
ROUTES = _routes()


def test_the_scan_found_the_call_sites_it_is_meant_to_check():
    """A silently-empty scan would make every test below pass.

    This is the guard the repo has now needed three times: the event-loop
    invariant indexed a directory that did not exist, the settings-key guard was
    defeated by a comment, and the hover-reveal rescue listed class names by
    hand. Each time the fix was to generate the list from the thing it
    constrains, and each time it needed this assertion.
    """
    assert len(CALL_SITES) > 40, (
        f"only {len(CALL_SITES)} e2e call sites were found; the walk is broken"
    )
    files = {row[0] for row in CALL_SITES}
    assert len(files) >= 8, f"expected call sites across many specs, found {files}"
    # Spot-check the two prefixes the resolver has to get right, so a future
    # edit to `resolveApiPath` cannot quietly invert it.
    resolved = {row[4] for row in CALL_SITES}
    assert any(p.startswith("/api/v2/") for p in resolved)
    assert any(p.startswith("/api/settings") for p in resolved), (
        "no unversioned /api/... path was resolved, so the resolver's escape "
        "hatch is untested by the corpus"
    )


def _resolve_schema(schema: dict | None, spec: dict, depth: int = 0) -> dict:
    """Follow `$ref` into `components.schemas`, with a depth cap.

    The cap matters because a self-referential model (`ChapterCreate` holding a
    list of `ChapterRevision`, say) would otherwise recurse until the test run
    died rather than until it reported something.
    """
    if not isinstance(schema, dict) or depth > 6:
        return {}
    ref = schema.get("$ref")
    if not ref:
        return schema
    if not ref.startswith("#/components/schemas/"):
        return {}
    return _resolve_schema(spec["components"]["schemas"].get(ref.rsplit("/", 1)[-1], {}), spec, depth + 1)


def _skip_trivia(text: str, i: int) -> int:
    """Advance past a string or comment starting at `i`, else return `i`.

    Both the paren matcher and the body scanner need this. Without comment
    awareness an apostrophe in prose — `the chapter's content` — opens a
    "string" that runs to the next apostrophe somewhere later in the file,
    swallowing every brace in between. That is how the check written for
    `seedStoryChapter` first reported nothing at all for it.
    """
    if text.startswith("//", i):
        newline = text.find("\n", i)
        return len(text) if newline == -1 else newline
    if text.startswith("/*", i):
        end = text.find("*/", i + 2)
        return len(text) if end == -1 else end + 2
    if i < len(text) and text[i] in "\"'`":
        quote = text[i]
        i += 1
        while i < len(text) and text[i] != quote:
            i += 2 if text[i] == "\\" else 1
        return min(i + 1, len(text))
    return i


_CLOSERS = {"(": ")", "{": "}", "[": "]"}


def _matching_paren(text: str, start: int) -> int:
    """Index of the `)` closing the call whose arguments start at `start`.

    Depth-counts all three bracket kinds so a `)` inside a nested object or array
    does not end the call early.
    """
    i = start
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text) or text[i] not in _CLOSERS:
        return -1
    stack = [_CLOSERS[text[i]]]
    i += 1
    while i < len(text) and stack:
        skipped = _skip_trivia(text, i)
        if skipped != i:
            i = skipped
            continue
        char = text[i]
        if char in _CLOSERS:
            stack.append(_CLOSERS[char])
        elif char in ")]}":
            if char != stack[-1]:
                return -1
            stack.pop()
        i += 1
    return -1 if stack else i - 1


def _object_literal_after(text: str, start: int, limit: int) -> tuple[set[str], bool] | None:
    """The top-level keys of the object literal between `start` and `limit`.

    Returns `(keys, spreads)`. `spreads` is True when the literal contains a
    `...` spread.

    The scan is a small balance machine rather than a regex because these bodies
    nest (`{ type: mimeType }`, `{ override: overrides.content || '' }`) and span
    lines, and a regex either truncates at the first `}` or matches the wrong
    nesting level.

    `limit` is the call's own closing paren. Without it the search for `{` runs
    past the end of the call and picks up an unrelated literal later in the file:
    three helpers that build their body in a local variable
    (`seedPrompt`, `seedCollection`, and the branding round-trip in
    `settings.spec.js`) were each reported as omitting a required field they
    actually send.
    """
    open_at = text.find("{", start, limit)
    if open_at == -1:
        return None
    depth = 0
    keys: set[str] = set()
    spreads = False
    i = open_at
    expecting_key = True
    while i < len(text):
        skipped = _skip_trivia(text, i)
        if skipped != i:
            i = skipped
            continue
        char = text[i]
        if char == "{":
            depth += 1
            if depth == 1:
                expecting_key = True
        elif char == "}":
            depth -= 1
            if depth == 0:
                return keys, spreads
        elif depth == 1:
            # A comma ends the current entry, so the next one starts with a key
            # again. Without this reset only the first key of every literal was
            # ever recorded — and a `...spread` was never recognised as one, so
            # `spreads` was always False.
            if char == ",":
                expecting_key = True
            elif expecting_key and char == ".":
                spreads = True
                expecting_key = False
            elif expecting_key and (char.isalpha() or char in "_$"):
                match = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", text[i:])
                if match:
                    keys.add(match.group(0))
                    expecting_key = False
        i += 1
    return None


def _body_sites(text: str, spec_name: str) -> list[tuple[int, str, str, set[str], bool]]:
    """`(line, helper, resolved_path, keys, spreads)` for every body-carrying call."""
    rows = []
    for helper, method in BODY_HELPERS.items():
        for match in re.finditer(
            rf"\b{helper}\s*\(\s*page\s*,\s*(['\"`])((?:\\.|(?!\1).)*)\1",
            text,
        ):
            raw = match.group(2)
            if raw.startswith(IGNORED_PREFIXES) or raw in {"", "/"}:
                continue
            # The body is the third argument. Bound the search to the call's own
            # parentheses: a body held in a local variable is not statically
            # determinable, and reaching past the call for a `{` finds an
            # unrelated literal.
            open_paren = text.find("(", match.start(), match.end() + 1)
            if open_paren == -1:
                continue
            limit = _matching_paren(text, open_paren)
            if limit == -1:
                continue
            comma = text.find(",", match.end(), limit)
            if comma == -1:
                continue
            parsed = _object_literal_after(text, comma, limit)
            if parsed is None:
                continue
            keys, spreads = parsed
            rows.append(
                (
                    text.count("\n", 0, match.start()) + 1,
                    helper,
                    _resolve(raw),
                    keys,
                    spreads,
                )
            )
    return rows


BODY_CALL_SITES: list[tuple[str, int, str, str, set[str], bool]] = []
for _spec in _spec_files():
    _text = _spec.read_text(encoding="utf-8")
    for _line, _helper, _resolved, _keys, _spreads in _body_sites(_text, _spec.name):
        BODY_CALL_SITES.append(
            (_spec.name, _line, _helper, _resolved, _keys, _spreads)
        )

_OPENAPI = app.openapi()


def test_every_e2e_endpoint_exists_in_the_backend():
    """The contract. One failure message naming every dead path."""
    dead = []
    for name, line, helper, raw, resolved in CALL_SITES:
        if any(_path_matches(route, resolved) for route in ROUTES):
            continue
        dead.append(f"e2e/{name}:{line}  {helper}({raw!r}) -> GET {resolved}")

    assert not dead, (
        "these e2e call sites request backend routes that do not exist. Each "
        "helper in e2e/fixtures.js throws when the response is not ok, so the "
        "test cannot pass and the e2e CI job cannot be green:\n  "
        + "\n  ".join(dead)
        + "\n\nEither the path is wrong (check whether the endpoint is under "
        "/api/v2 or unversioned), or the route was removed."
    )


def test_the_body_scan_found_the_call_sites_it_is_meant_to_check():
    """The body check is worthless if the scan is empty.

    A scan that silently matches nothing reads exactly like a suite that sends
    every required field. This is the same guard as
    `test_the_scan_found_the_call_sites_it_is_meant_to_check`, one layer in.
    """
    assert len(BODY_CALL_SITES) > 8, (
        f"only {len(BODY_CALL_SITES)} e2e request bodies were found; the body "
        "scan is broken and the test below would pass vacuously"
    )
    chapter = [
        row for row in BODY_CALL_SITES if row[3].endswith("/chapters")
    ]
    assert chapter, (
        "no chapter seed was scanned — `seedStoryChapter` is the call site this "
        "check was written for, so a change to its shape should be a deliberate "
        "decision rather than a silent loss of coverage"
    )


def _required_body_properties(operation: dict, spec: dict) -> list[str]:
    """The `required` property names of an operation's JSON request body.

    The unwrapping is three steps and getting it wrong is silent: `content` is
    keyed by media type, so the first version of this returned the *media-type
    map* as if it were the schema. That object is truthy and has no `required`
    key, so the check read "nothing is required" and passed every call site —
    including the one it was written for.
    """
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return []
    content = body.get("content") or {}
    if not isinstance(content, dict):
        return []
    json_media = content.get("application/json") or content.get("multipart/form-data")
    if not isinstance(json_media, dict):
        # Any media type will do if the two conventional ones are absent.
        json_media = next(iter(content.values()), None)
    if not isinstance(json_media, dict):
        return []
    schema = _resolve_schema(json_media.get("schema", {}), spec)
    required = schema.get("required")
    return list(required) if isinstance(required, list) else []


def test_every_e2e_request_body_satisfies_its_required_fields():
    """A correct path with an incomplete body is still a dead call site.

    `seedStoryChapter` posted `{ title }` at the right URL for a
    `ChapterCreate` that requires `content` and forbids extras, so it was a 422
    on every run while the path contract passed — and the e2e job failed 50
    tests later than the cause.

    A body that spreads (`...overrides`) is **not** skipped. Skipping it was the
    first version of this check and it silently excluded `seedStoryChapter` — the
    one call site the check was written for — because that helper takes an
    `overrides` parameter. The reasoning that replaced it: a required field
    assigned before the spread is present in the final object whether or not the
    spread carries its own value for it, so the spread cannot excuse its absence.
    Only a body whose *sole* source of a required field is the spread would be
    genuinely indeterminate, and none exists.
    """
    incomplete = []
    for name, line, helper, resolved, keys, spreads in BODY_CALL_SITES:
        operation = None
        for route, methods in _OPENAPI["paths"].items():
            if not _path_matches(route, resolved):
                continue
            for verb in ("post", "put", "patch"):
                if verb in methods:
                    operation = methods[verb]
                    break
            if operation:
                break
        if operation is None:
            continue  # Path shape not matched here; the path test reports it.
        required = _required_body_properties(operation, _OPENAPI)
        absent = [prop for prop in required if prop not in keys]
        if absent:
            incomplete.append(
                f"e2e/{name}:{line}  {helper}({resolved!r}) omits required "
                f"{', '.join(sorted(absent))} — the model requires "
                f"{', '.join(sorted(required))}"
            )

    assert not incomplete, (
        "these e2e request bodies omit a field the backend model declares "
        "required, so each is a 422 (or a silently-dropped field on a model "
        "without `extra=\"forbid\"`):\n  " + "\n  ".join(incomplete)
    )


def test_the_resolver_matches_the_one_in_the_fixtures():
    """`resolveApiPath` is duplicated here on purpose; keep the two in step.

    The suite cannot import the ESM helper, so the rule is restated. If the two
    ever disagree this file stops describing what the harness actually requests,
    and the test above starts passing vacuously.
    """
    fixtures = (E2E_DIR / "fixtures.js").read_text(encoding="utf-8")
    assert "export function resolveApiPath(path)" in fixtures, (
        "e2e/fixtures.js no longer exports resolveApiPath; this file's copy of "
        "the rule has nothing to mirror"
    )
    assert "API_BASE + path" in fixtures, (
        "resolveApiPath should build unversioned-relative paths from API_BASE"
    )
    for helper in HELPERS:
        # `[\s\S]` rather than `[^:]`: the body of `apiUpload` contains object
        # literals (`{ type: mimeType }`), so any character class excluding `:`
        # cannot span them.
        pattern = rf"async function {helper}\([\s\S]{{0,200}}?\)[\s\S]{{0,600}}?resolveApiPath\("
        assert re.search(pattern, fixtures, flags=re.S), (
            f"{helper} does not route its path through resolveApiPath, so it is "
            "still blind-prefixing /api/v2 and can 404 on an unversioned route"
        )
    # The blind concatenation must be gone from every request helper.
    assert not re.search(r"request\.\w+\(\s*API_BASE\s*\+", fixtures), (
        "a helper still concatenates API_BASE directly, which is the defect "
        "this contract exists to prevent"
    )