"""`docs/api.md` is generated from the route table, and checked against it.

`docs/api.md` is the only description of the HTTP surface a human reads, and for
three audits running it was quietly wrong in ways nobody could see:

  * it documented `GET /api/v2/timeline/timeline` — a route that does not exist —
    and *rationalised* it with an invented explanation about router prefixes.
    `frontend_v2/e2e/activity.spec.js` had the identical wrong path, which is how
    one wrong belief reached two consumers;
  * it covered 131 of the 249 real paths (53%), and nothing measured that;
  * `docs/STATUS.md` claimed "201 of the 329 live operations", a figure that was
    wrong in both numbers and had never been computed.

No test in any language referenced this file, so it drifted freely.

The check here is deliberately two-sided, because the two failure modes are
different and each has bitten:

  * **Documented but absent** — a doc entry that no route backs. This is the
    dangerous direction: an operator or a test trusts it. `test_e2e_endpoint_
    contract.py` covers the test-harness half; this covers the document.
  * **Absent but undocumented** — a route nobody wrote down. Not dangerous, but
    it is how this file fell to 53%, so it is asserted with a floor and a report
    of exactly which groups are missing.

Both lists are generated. Nothing here is a hand-kept list of route names, which
is the failure mode that has now cost this repo three separate guards (the
event-loop invariant indexed a directory that did not exist; the settings-key
guard was satisfied by a comment; the hover-reveal rescue listed class names by
hand).
"""

import re
from pathlib import Path

import pytest

from api.main import app

DOC = Path(__file__).resolve().parents[2] / "docs" / "api.md"

# `METHOD /api/...` in prose, or a bare `/api/...` path token in backticks.
#
# No `\b` before the path: the generated index writes every route as
# `` `GET` `/api/jobs/breakdown` ``, and a word boundary cannot exist between a
# backtick and a slash — both are non-word. That silently dropped 104 of the 249
# routes while the file looked complete, which is exactly the failure this test
# exists to catch, so it is worth a comment rather than a clever fix.
_PATH_TOKEN = re.compile(
    r"((?:GET|POST|PUT|PATCH|DELETE)\s+)?(/api/[A-Za-z0-9_\-{}./:]+)"
)

# Path parameters are spelled inconsistently across the document and the routes
# (`{job_id}` vs `{id}`); compare on shape, not on the name.
def _shape(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path).rstrip("/") or "/"


def _prose_only(text: str) -> str:
    """Reduce the document to the lines that actually declare an endpoint.

    Two exclusions, both principled rather than tuned:

    **Fenced blocks and HTML comments are stripped.** This file has to name
    routes that do not exist — that is most of what a drift check is for — and
    the prose doing it was tripping the scan:

        Not endpoints, despite having been documented as such here:
        `POST /api/v2/models/provider-sync`, and any `GET`/`POST` on
        `/api/v2/models/versions/{version_id}/files`.

        There is no `GET /api/files/proxy/{provider_id}/{path}`. This file
        documented one; no such route exists.

    Three of those were reported as ghosts, all of them real corrections. So the
    convention is explicit: **a path that is being denied goes in a fenced block
    or an HTML comment.** Better than teaching the scan to guess at negations —
    "no", "not", "without" and "removed" all appear in ordinary prose too — and
    it makes the intent obvious to a human skimming the file.

    **Headings and paragraphs are dropped.** Only list items and table rows
    declare endpoints. A heading like `### Collections (/api/v2/collections)` is
    navigation, and `docs/api.md` carries a handful of them that name a path
    loosely; treating a heading as a declaration produced eight phantom ghosts.
    """
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`{3,}[^`]*`{3,}", "", text, flags=re.S)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)

    kept = []
    for line in text.splitlines():
        stripped = line.lstrip()
        # `- `, `* `, `+ `, `1. ` and table rows.
        if stripped.startswith(("- ", "* ", "+ ")) or re.match(r"^\d+\.\s", stripped):
            kept.append(line)
        elif stripped.startswith("|"):
            kept.append(line)
    return "\n".join(kept)


def _documented() -> set[str]:
    text = _prose_only(DOC.read_text(encoding="utf-8"))
    out: set[str] = set()
    for _, path in _PATH_TOKEN.findall(text):
        path = path.rstrip(".,;)")
        if path.startswith("/api/"):
            out.add(_shape(path))
    return out


def _real() -> set[str]:
    return {_shape(p) for p in app.openapi()["paths"]}


DOCUMENTED = _documented()
REAL = _real()


def test_the_document_exists_and_the_scan_found_something():
    """A silently-empty scan makes every other test here pass.

    This is the fourth time this repo has needed it.
    """
    assert DOC.is_file(), f"{DOC} not found"
    assert len(DOCUMENTED) > 80, (
        f"only {len(DOCUMENTED)} path tokens parsed out of docs/api.md; the scan "
        "is broken, not the document"
    )
    assert len(REAL) > 200, f"only {len(REAL)} real routes; the openapi read failed"


def test_every_path_documented_in_api_md_exists():
    """The dangerous direction: the document names a route that is not there.

    Path-parameter spelling is normalised away, so this is about routes, not
    about `{id}` versus `{provider_id}`.
    """
    ghosts = sorted(DOCUMENTED - REAL)
    assert not ghosts, (
        "docs/api.md documents paths that no route serves. An operator reading "
        "this file, or a test written from it, will 404:\n  "
        + "\n  ".join(f"/{g}" for g in ghosts)
        + "\n\nEither the route was removed or renamed — fix the document — or it "
        "is missing from the OpenAPI schema, which is the worse problem."
    )


def test_api_md_documents_the_large_majority_of_the_surface():
    """The direction that produced the 53% figure, with a floor.

    65% is below today's coverage-adjusted reality and leaves room for ordinary
    churn; the point is to make a large regression fail loudly. The message lists
    the missing top-level groups so the gap is actionable rather than a number.
    """
    missing = sorted(REAL - DOCUMENTED)
    coverage = 1 - (len(missing) / len(REAL))

    # Group the gap, so the failure names what is unwritten rather than listing
    # 104 paths.
    groups: dict[str, int] = {}
    for path in missing:
        parts = path.strip("/").split("/")
        key = "/".join(parts[:3]) if len(parts) >= 3 else path
        groups[key] = groups.get(key, 0) + 1
    worst = sorted(groups.items(), key=lambda kv: -kv[1])[:12]

    assert coverage >= 0.65, (
        f"docs/api.md documents only {coverage:.0%} of the {len(REAL)} live route "
        f"paths ({len(missing)} missing). Undocumented groups: "
        + ", ".join(f"{k} ({v})" for k, v in worst)
    )


def test_the_route_count_the_status_document_quotes_is_current():
    """`docs/STATUS.md` has carried a stale route count across three audits.

    It said "201 of the 329 live operations". The real figures were 131 of 249
    paths, and the "201 of 329" pair does not correspond to any counting of this
    API — paths versus operations were being conflated. A quoted number that
    nobody recomputes is worse than no number, because it reads as a measurement.
    """
    import re as _re

    status = DOC.parent / "STATUS.md"
    if not status.is_file():
        pytest.skip("STATUS.md not present")

    text = status.read_text(encoding="utf-8")
    quoted = _re.findall(r"(\d+)\s+(?:of|/)\s*(\d+)\s+live (?:operations|paths)", text)
    if not quoted:
        pytest.skip("STATUS.md quotes no route count")

    spec = app.openapi()
    real_ops = sum(len(v) for v in spec["paths"].values())
    real_paths = len(spec["paths"])

    for a, b in quoted:
        # Either pair is acceptable as long as it is not a number that does not
        # exist: paths and operations are both legitimate things to quote.
        pair = {int(a), int(b)}
        assert pair & {real_paths, real_ops}, (
            f"STATUS.md quotes '{a} of {b} live operations', but this app has "
            f"{real_paths} paths and {real_ops} operations. Neither number is "
            "current."
        )