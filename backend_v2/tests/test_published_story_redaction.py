"""The published-story EXPORT must be no wider than the published-story READ.

`GET /published/{token}` builds a deliberately narrowed projection — no internal
ids, no chapter `beats`, no lorebooks. `GET /published/{token}/export` resolved
the same token and called the owner-shaped `export_story(...)` unfiltered, so the
unauthenticated export returned all three plus every primary key. The docstring on
both routes says "public, read-only", which is what made it read as a mistake
rather than a decision.

The assertion below is the RULE, not a transcription: no key anywhere in the
export body may be absent from the read body. A transcribed list would have to be
edited every time a field is added, and would pass just as happily if someone
added `beats` back to both. This fails when the two projections are made to
diverge again, which is the only thing that matters.
"""

import pytest

from core.entities import Character, Location, Lorebook, Story, StoryChapter


def _keys(node):
    """Every mapping key reachable in `node`, as dotted paths.

    Walks nested lists and dicts so a key smuggled in at any depth is caught, not
    just the top-level ones.
    """
    found = set()
    stack = [("", node)]
    while stack:
        prefix, value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                path = f"{prefix}.{key}" if prefix else key
                found.add(path)
                stack.append((path, child))
        elif isinstance(value, list):
            # Collapse list indices: the rule is about shape, not row count.
            for child in value:
                stack.append((f"{prefix}[]", child))
    return found


def _dotted_prefixes(paths):
    """`a.b` also matches `a.b[]` and `a.b[].c`, so shapes compare across depths."""
    out = set()
    for path in paths:
        parts = path.split(".")
        for i in range(1, len(parts) + 1):
            out.add(".".join(parts[:i]))
    return out


@pytest.fixture
def published_story_with_everything(session):
    """A published story carrying every category the export used to leak."""
    character = Character(name="Ash", description="wanderer", personality="wry")
    location = Location(name="Duskmoor", description="a wet town", atmosphere="rain")
    lorebook = Lorebook(name="Ash lore", description="private canon")
    session.add_all([character, location, lorebook])
    session.commit()
    session.refresh(character)
    session.refresh(location)
    session.refresh(lorebook)

    story = Story(
        title="The Salt Road",
        description="a road that remembers",
        genre="fantasy",
        memory="author note",
        character_ids=[character.id],
        location_ids=[location.id],
        lorebook_ids=[lorebook.id],
    )
    session.add(story)
    session.commit()
    session.refresh(story)

    chapter = StoryChapter(
        story_id=story.id,
        chapter_number=1,
        title="Departure",
        content="She left before dawn.",
        beats=["salt road", "the ferryman's price", "a lighthouse"],
        image_paths=[],
    )
    session.add(chapter)
    session.commit()

    token = story.publish().published_token if hasattr(story, "publish") else None
    if token is None:
        # `publish` is a route, not a model method in this codebase; go through it.
        from api.deps import get_session_sync

        with get_session_sync() as s:
            row = s.get(Story, story.id)
            row.is_published = True
            row.published_token = "test-token-redaction"
            s.add(row)
            s.commit()
        token = "test-token-redaction"
    return story, token


def test_published_export_is_no_wider_than_published_read(
    client, session, published_story_with_everything
):
    story, token = published_story_with_everything

    read = client.get(f"/api/v2/stories/published/{token}")
    export = client.get(f"/api/v2/stories/published/{token}/export?format=json")
    assert read.status_code == 200, read.text
    assert export.status_code == 200, export.text

    read_body = read.json()
    export_body = export.json()

    read_keys = _dotted_prefixes(_keys(read_body))
    export_keys = _dotted_prefixes(_keys(export_body))
    leaked = sorted(export_keys - read_keys)
    assert not leaked, (
        "the published export carries keys the published read does not, so it is "
        f"wider than the redaction it is supposed to share: {leaked}"
    )

    # And the concrete categories, stated once so the failure message names the
    # leak rather than a set of paths. `beats` and the lorebooks are the author's
    # private material; the ids are what make the payload addressable.
    assert "chapters[].beats" not in export_keys
    assert not any(key.startswith("lorebooks") for key in export_keys)
    assert "story.id" in read_keys, "guard: the read really does expose a story id"


def test_owner_export_still_carries_the_private_fields(
    client, session, published_story_with_everything
):
    """The gating is on the public route only — the owner's export is unchanged.

    Without this, "make the published export narrower" could be satisfied by
    deleting the data from both, which fixes the leak and breaks the feature.
    """
    story, _token = published_story_with_everything

    owner = client.get(f"/api/v2/stories/{story.id}/export?format=json")
    assert owner.status_code == 200, owner.text
    body = owner.json()
    assert body["chapters"][0]["beats"], "owner export lost the beats list"
    assert body["lorebooks"], "owner export lost the lorebooks"
    assert body["characters"][0]["id"], "owner export lost the character id"


def test_published_markdown_export_leaks_nothing_private(
    client, session, published_story_with_everything
):
    """The non-JSON published formats must not become the next leak.

    They render from `story`/`chapters` directly and never carried `beats`,
    lorebooks or ids, so they need no gating — but they are reachable through the
    same public route and a future format branch would not be covered by the JSON
    test above.
    """
    _story, token = published_story_with_everything

    for fmt in ("md", "markdown"):
        resp = client.get(f"/api/v2/stories/published/{token}/export?format={fmt}")
        assert resp.status_code == 200, resp.text
        content = resp.json()["content"]
        for secret in ("salt road", "the ferryman's price", "Ash lore", "private canon"):
            assert secret not in content, f"{fmt} export leaked {secret!r}"