# Tests for image tags (`asset_tags`) and the facet query they feed.
#
# Two things are being defended here, and they are the same thing: a tag whose
# origin is not recorded is a tag some later writer destroys. The auto-tagger
# replaces its own rows wholesale, so without `source` it would also replace the
# human's corrections, and without a real bounded/resumable batch contract it
# would be a 16k-row stall inside an HTTP request.

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from core.entities import Asset, AssetLora, AssetTag
from core.entities import Session as GenerationSession
from core.entities import SessionAsset
from core.exceptions import NotFoundError, ValidationError
from services import tag_service
from services.asset_metadata_index import (
    AUTO_CONFIDENCE_CIVITAI_TAG,
    AUTO_CONFIDENCE_TRAINED_WORD,
    extract_tag_evidence,
    extract_tag_vocabulary,
)

# The real nested LoRA shape (the ONLY shape in the library) — a CivitAI payload
# with the id at `metadata.id` and the trained words one level down in
# `modelVersions[0].trainedWords`, comma-joined.
NESTED_LORA = {
    "name": "Zeta_loRA.safetensors",
    "strength": 0.8,
    "metadata": {
        "id": 1189691,
        "name": "Zeta/ゼータ (The Eminence in Shadow) SDXL LoRA",
        "tags": ["concept", "character", "z3t4", "illustrious"],
        "type": "LORA",
        "modelVersions": [
            {
                "baseModel": "Illustrious",
                "trainedWords": ["z3t4, blonde hair, cat ears, low ponytail"],
            }
        ],
    },
}

AUTO_TAGS = {
    # CivitAI catalogue labels
    "concept": AUTO_CONFIDENCE_CIVITAI_TAG,
    "character": AUTO_CONFIDENCE_CIVITAI_TAG,
    "z3t4": AUTO_CONFIDENCE_TRAINED_WORD,
    "illustrious": AUTO_CONFIDENCE_CIVITAI_TAG,
    # Trained words, split out of the comma-joined string
    "blonde hair": AUTO_CONFIDENCE_TRAINED_WORD,
    "cat ears": AUTO_CONFIDENCE_TRAINED_WORD,
    "low ponytail": AUTO_CONFIDENCE_TRAINED_WORD,
}

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_asset(session, name: str, *, day: int = 1, **kwargs) -> Asset:
    created = EPOCH + timedelta(days=day)
    asset = Asset(
        filename=f"{name}.png",
        relative_path=f"default_user/main/2026/01/{day:02d}/{name}.png",
        created_at=created,
        generated_at=kwargs.pop("generated_at", created),
        **kwargs,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def tags_of(session, asset_id) -> dict:
    return {
        t.tag: t.source
        for t in session.exec(select(AssetTag).where(AssetTag.asset_id == asset_id)).all()
    }


@pytest.fixture(name="asset")
def asset_fixture(session):
    return make_asset(session, "img1", metadata_={"loras": [NESTED_LORA]})


# ── the evidence function ────────────────────────────────────────────────────

def test_evidence_scores_trained_words_above_civitai_tags():
    """An auto tag is a propagation from the LoRA, and the two sources of it are
    not equally strong evidence that the tag describes THIS image."""
    evidence = extract_tag_evidence({"loras": [NESTED_LORA]})
    assert evidence["z3t4"] == AUTO_CONFIDENCE_TRAINED_WORD
    assert evidence["concept"] == AUTO_CONFIDENCE_CIVITAI_TAG


def test_evidence_keeps_the_strongest_signal_for_a_shared_tag():
    """`z3t4` is both a CivitAI tag and a trained word; it must not land twice
    or be downgraded to the weaker reading."""
    evidence = extract_tag_evidence({"loras": [NESTED_LORA]})
    assert evidence["z3t4"] == AUTO_CONFIDENCE_TRAINED_WORD
    assert len(evidence) == len(extract_tag_vocabulary({"loras": [NESTED_LORA]}))


def test_evidence_is_empty_for_no_metadata():
    assert extract_tag_evidence(None) == {}
    assert extract_tag_evidence({}) == {}
    assert extract_tag_evidence({"loras": []}) == {}


# ── the user writer path ─────────────────────────────────────────────────────

def test_add_user_tag_is_user_sourced(session, asset):
    assert tag_service.add_user_tag(session, asset.id, "pose: kneeling") == {
        "tag": "pose: kneeling",
        "source": tag_service.ASSET_TAG_SOURCE_USER,
        "created": True,
    }
    assert tags_of(session, asset.id) == {"pose: kneeling": "user"}


def test_add_user_tag_is_idempotent_and_collapses_whitespace(session, asset):
    tag_service.add_user_tag(session, asset.id, "pose: kneeling")
    second = tag_service.add_user_tag(session, asset.id, "  pose:   kneeling  ")
    assert second["created"] is False
    assert tags_of(session, asset.id) == {"pose: kneeling": "user"}


def test_add_user_tag_rejects_empty_and_overlong(session, asset):
    with pytest.raises(ValidationError):
        tag_service.add_user_tag(session, asset.id, "   ")
    with pytest.raises(ValidationError):
        tag_service.add_user_tag(session, asset.id, "x" * (tag_service.MAX_TAG_LENGTH + 1))


def test_add_user_tag_404s_on_an_unknown_or_deleted_asset(session, asset):
    with pytest.raises(NotFoundError):
        tag_service.add_user_tag(session, "no-such-asset", "x")
    asset.deleted_at = datetime.now(timezone.utc)
    session.commit()
    with pytest.raises(NotFoundError):
        tag_service.add_user_tag(session, asset.id, "x")


def test_a_user_tag_the_tagger_also_derives_is_stored_once(session, asset):
    """`uq_asset_tag` is on (asset_id, tag): a shared tag is one row, owned by
    whoever got there first, and the tagger skips it rather than failing on the
    constraint."""
    tag_service.add_user_tag(session, asset.id, "z3t4")
    session.commit()

    seen, written, skipped = tag_service.auto_tag_asset(session, asset)
    session.commit()

    assert seen == len(AUTO_TAGS)
    assert skipped == 1
    assert written == len(AUTO_TAGS) - 1
    assert tags_of(session, asset.id)["z3t4"] == "user"


def test_remove_user_tag_deletes_only_user_rows(session, asset):
    tag_service.add_user_tag(session, asset.id, "mine")
    session.commit()
    tag_service.auto_tag_asset(session, asset)
    session.commit()

    assert tag_service.remove_user_tag(session, asset.id, "mine") is True
    remaining = tags_of(session, asset.id)
    assert "mine" not in remaining
    # An auto tag is not the user's to delete, and the next pass would put it
    # straight back anyway.
    assert tag_service.remove_user_tag(session, asset.id, "concept") is False
    assert "concept" in remaining


def test_remove_user_tag_reports_a_miss(session, asset):
    assert tag_service.remove_user_tag(session, asset.id, "never-added") is False


def test_list_asset_tags_reports_provenance_and_confidence(session, asset):
    tag_service.add_user_tag(session, asset.id, "mine")
    tag_service.auto_tag_asset(session, asset)
    session.commit()

    listed = {t["tag"]: t for t in tag_service.list_asset_tags(session, asset.id)}
    assert listed["concept"]["source"] == "auto"
    assert listed["concept"]["confidence"] == AUTO_CONFIDENCE_CIVITAI_TAG
    assert listed["blonde hair"]["confidence"] == AUTO_CONFIDENCE_TRAINED_WORD
    assert listed["mine"]["source"] == "user"
    assert listed["mine"]["confidence"] is None


# ── the auto-tagger ──────────────────────────────────────────────────────────

def test_auto_tag_derives_the_loras_booru_vocabulary(session, asset):
    seen, written, skipped = tag_service.auto_tag_asset(session, asset)
    session.commit()
    assert seen == len(AUTO_TAGS)
    assert written == len(AUTO_TAGS)
    assert skipped == 0
    assert tags_of(session, asset.id) == {tag: "auto" for tag in AUTO_TAGS}


def test_auto_tag_converges_when_the_evidence_changes(session, asset):
    """Delete-then-insert, so a LoRA whose upstream tags changed does not leave
    a stale tag behind forever."""
    tag_service.auto_tag_asset(session, asset)
    session.commit()
    assert "concept" in tags_of(session, asset.id)

    asset.metadata_ = {
        "loras": [
            {
                "name": "other.safetensors",
                "metadata": {"id": 7, "tags": ["pose"]},
            }
        ]
    }
    session.commit()
    tag_service.auto_tag_asset(session, asset)
    session.commit()

    assert tags_of(session, asset.id) == {"pose": "auto"}


def test_auto_tag_clears_when_the_vocabulary_disappears(session, asset):
    tag_service.auto_tag_asset(session, asset)
    session.commit()
    asset.metadata_ = {"loras": []}
    session.commit()
    assert tag_service.auto_tag_asset(session, asset) == (0, 0, 0)
    session.commit()
    assert tags_of(session, asset.id) == {}


def test_auto_tag_caps_the_tags_stored_per_image(session):
    """An unbounded vocabulary times 16.4k assets is millions of rows of mostly
    nothing; the cap takes the strongest evidence first, deterministically."""
    session.add(
        Asset(
            filename="many.png",
            relative_path="default_user/main/2026/01/01/many.png",
            metadata_={
                "loras": [
                    {
                        "name": f"lora{i}.safetensors",
                        "metadata": {
                            "id": i,
                            "tags": [f"tag{i:03d}"],
                            "modelVersions": [
                                {"trainedWords": [f"word{i:03d}"]},
                            ],
                        },
                    }
                    for i in range(40)
                ]
            },
        )
    )
    session.commit()
    asset = session.exec(
        select(Asset).where(Asset.filename == "many.png")
    ).one()

    _, written, _ = tag_service.auto_tag_asset(session, asset)
    session.commit()

    assert written == tag_service.MAX_AUTO_TAGS_PER_ASSET
    stored = tags_of(session, asset.id)
    # Every trained word outranks every catalogue tag, so the survivors are the
    # words — the tag cap is a ranking, not an arbitrary truncation.
    assert all(tag.startswith("word") for tag in stored)
    assert "tag000" not in stored


def test_auto_tag_is_idempotent(session, asset):
    tag_service.auto_tag_asset(session, asset)
    session.commit()
    first = dict(
        (t.tag, t.id)
        for t in session.exec(select(AssetTag).where(AssetTag.asset_id == asset.id)).all()
    )
    tag_service.auto_tag_asset(session, asset)
    session.commit()
    second = dict(
        (t.tag, t.id)
        for t in session.exec(select(AssetTag).where(AssetTag.asset_id == asset.id)).all()
    )
    assert set(first) == set(second)
    assert len(first) == len(AUTO_TAGS)


# ── the batch contract ───────────────────────────────────────────────────────

def test_a_limited_run_does_only_the_limit(session):
    for i in range(5):
        make_asset(session, f"b{i}", day=i + 1, metadata_={"loras": [NESTED_LORA]})

    summary = tag_service.reindex_asset_tags(session, batch_size=10, limit=2)

    assert summary["processed"] == 2
    assert summary["truncated"] is True
    assert summary["tags_written"] == 2 * len(AUTO_TAGS)
    tagged = session.exec(select(AssetTag)).all()
    assert len({t.asset_id for t in tagged}) == 2


def test_a_limited_run_is_resumable_from_last_asset_id(session):
    for i in range(4):
        make_asset(session, f"r{i}", day=i + 1, metadata_={"loras": [NESTED_LORA]})

    first = tag_service.reindex_asset_tags(session, batch_size=2, limit=2)
    second = tag_service.reindex_asset_tags(
        session, batch_size=2, after_id=first["last_asset_id"]
    )

    assert first["processed"] == 2
    assert second["processed"] == 2
    assert second["last_asset_id"] > first["last_asset_id"]
    assert len({t.asset_id for t in session.exec(select(AssetTag)).all()}) == 4


def test_a_dry_run_writes_nothing(session, asset):
    summary = tag_service.reindex_asset_tags(session, dry_run=True, limit=10)

    assert summary["dry_run"] is True
    assert summary["processed"] == 1
    assert summary["tags_written"] == len(AUTO_TAGS)
    assert session.exec(select(AssetTag)).all() == []


def test_a_dry_run_does_not_delete_an_existing_tag_set(session, asset):
    tag_service.reindex_asset_tags(session, limit=10)
    assert tags_of(session, asset.id) == {tag: "auto" for tag in AUTO_TAGS}

    tag_service.reindex_asset_tags(session, dry_run=True, limit=10)
    assert tags_of(session, asset.id) == {tag: "auto" for tag in AUTO_TAGS}


def test_a_full_pass_survives_user_tags(session):
    """The point of `source`: a batch re-derivation must not touch what a human
    asserted, and must not try to insert a duplicate of it either."""
    for i in range(3):
        asset = make_asset(session, f"u{i}", day=i + 1, metadata_={"loras": [NESTED_LORA]})
        # "mine" is a tag no LoRA knows about; "z3t4" is one they both derive.
        tag_service.add_user_tag(session, asset.id, "mine")
        tag_service.add_user_tag(session, asset.id, "z3t4")
    make_asset(session, "no-metadata", day=9, metadata_=None)

    summary = tag_service.reindex_asset_tags(session, batch_size=2)

    assert summary["skipped_user"] == 3
    assert summary["skipped_no_metadata"] == 1
    for i in range(3):
        asset_id = session.exec(
            select(Asset.id).where(Asset.filename == f"u{i}.png")
        ).one()
        stored = tags_of(session, asset_id)
        assert stored["mine"] == "user"
        # The collision resolves to the user's row, not a second auto row.
        assert stored["z3t4"] == "user"
        assert stored["concept"] == "auto"
        assert len(stored) == len(AUTO_TAGS) + 1


def test_a_batch_skips_deleted_assets(session):
    asset = make_asset(session, "gone", day=1, metadata_={"loras": [NESTED_LORA]})
    asset.deleted_at = datetime.now(timezone.utc)
    session.commit()

    summary = tag_service.reindex_asset_tags(session, limit=10)
    assert summary["processed"] == 0
    assert session.exec(select(AssetTag)).all() == []


# ── the vocabulary ───────────────────────────────────────────────────────────

def test_vocabulary_orders_by_use_count(session):
    for i in range(3):
        tag_service.add_user_tag(session, make_asset(session, f"v1_{i}").id, "popular")
    tag_service.add_user_tag(session, make_asset(session, "v2").id, "rare")
    session.commit()

    rows = {row["tag"]: row for row in tag_service.list_tag_vocabulary(session)}
    assert rows["popular"]["count"] == 3
    assert rows["rare"]["count"] == 1
    assert [r["tag"] for r in tag_service.list_tag_vocabulary(session)] == ["popular", "rare"]


def test_vocabulary_breaks_count_ties_on_the_tag_text(session):
    for name in ("a", "b"):
        asset_id = make_asset(session, name).id
        tag_service.add_user_tag(session, asset_id, "zebra")
        tag_service.add_user_tag(session, asset_id, "apple")
    session.commit()
    assert [r["tag"] for r in tag_service.list_tag_vocabulary(session)] == ["apple", "zebra"]


def test_vocabulary_filters_by_prefix_and_by_substring(session):
    for name, tag in (("blonde", "blonde hair"), ("black", "black hair")):
        tag_service.add_user_tag(session, make_asset(session, name).id, tag)
    session.commit()

    # A prefix is ANCHORED, not a substring: "bl" is a literal prefix of both
    # "blonde hair" and "black hair", which is the point of the autocomplete
    # mode — narrowing the prefix narrows the result.
    assert [r["tag"] for r in tag_service.list_tag_vocabulary(session, prefix="bl")] == [
        "black hair",
        "blonde hair",
    ]
    assert [r["tag"] for r in tag_service.list_tag_vocabulary(session, prefix="blon")] == [
        "blonde hair"
    ]
    assert sorted(r["tag"] for r in tag_service.list_tag_vocabulary(session, query="hair")) == [
        "black hair",
        "blonde hair",
    ]


def test_vocabulary_reports_how_many_are_user_asserted(session):
    asset = make_asset(session, "vu")
    tag_service.add_user_tag(session, asset.id, "mine")
    tag_service.add_user_tag(session, asset.id, "also mine")
    session.commit()
    rows = {r["tag"]: r for r in tag_service.list_tag_vocabulary(session)}
    assert rows["mine"]["count"] == 1
    assert rows["mine"]["user_count"] == 1
    assert rows["also mine"]["user_count"] == 1


def test_vocabulary_excludes_tombstoned_assets(session, asset):
    tag_service.add_user_tag(session, asset.id, "mine")
    session.commit()
    assert len(tag_service.list_tag_vocabulary(session)) == 1

    asset.deleted_at = datetime.now(timezone.utc)
    session.commit()
    assert tag_service.list_tag_vocabulary(session) == []


def test_vocabulary_caps_and_flags_truncation(session):
    for i in range(5):
        tag_service.add_user_tag(session, make_asset(session, f"c{i}").id, f"tag{i}")
    session.commit()
    # Exactly `limit`, never limit + 1: the extra row the service fetches is
    # a truncation probe the caller reads through `truncated`, and returning
    # it made `?limit=50` answer with 51 tags.
    page = tag_service.list_tag_vocabulary(session, limit=2)
    assert len(page) == 2
    assert page.truncated is True
    page = tag_service.list_tag_vocabulary(session, limit=50)
    assert len(page) == 5
    assert page.truncated is False


def test_vocabulary_rejects_a_prefix_longer_than_a_tag_can_be(session):
    with pytest.raises(ValidationError):
        tag_service.list_tag_vocabulary(session, prefix="x" * (tag_service.MAX_TAG_LENGTH + 1))


# ── the facet query ──────────────────────────────────────────────────────────

@pytest.fixture(name="faceted")
def faceted_fixture(session):
    """Four images: two used a LoRA, two did not; two share a tag."""
    a = make_asset(session, "f1", day=1, checkpoint_name="Illustrious", character_id="c1",
                   metadata_={"loras": [NESTED_LORA]})
    b = make_asset(session, "f2", day=2, checkpoint_name="Illustrious", character_id="c2",
                   metadata_={"loras": [NESTED_LORA]})
    c = make_asset(session, "f3", day=3, checkpoint_name="Flux", character_id="c1",
                   metadata_={"prompt": "a lighthouse"})
    d = make_asset(session, "f4", day=4, checkpoint_name="Flux", character_id="c3")
    session.add(AssetLora(asset_id=a.id, civitai_model_id=1189691, strength=0.8))
    session.add(AssetLora(asset_id=b.id, civitai_model_id=1189691, strength=0.5))
    session.add(AssetLora(asset_id=c.id, civitai_model_id=999))
    session.add(AssetTag(asset_id=a.id, tag="blonde hair", source="auto", confidence=0.9))
    session.add(AssetTag(asset_id=b.id, tag="blonde hair", source="auto", confidence=0.9))
    session.add(AssetTag(asset_id=c.id, tag="cat ears", source="auto", confidence=0.9))
    session.add(AssetTag(asset_id=d.id, tag="pose: kneeling", source="user"))
    session.commit()
    return {"a": a, "b": b, "c": c, "d": d}


def facet(client, **params) -> dict:
    # Drop the unset ones explicitly: httpx renders a None param as the string
    # "None", which would filter on the literal text "None".
    query = {k: v for k, v in params.items() if v is not None}
    response = client.get("/api/v2/assets/facet", params=query)
    assert response.status_code == 200, response.text
    return response.json()


def filenames(payload) -> set:
    return {item["filename"] for item in payload["items"]}


def test_facet_filters_by_lora(client, faceted):
    payload = facet(client, lora="1189691", include_sessions=False)
    assert filenames(payload) == {"f1.png", "f2.png"}
    assert payload["total_matched"] == 2
    assert payload["has_more"] is False
    assert payload["next_cursor"] is None


def test_facet_filters_by_lora_model_id(client, faceted, session):
    """`asset_loras.model_id` is the installed-model identity, as opposed to
    `civitai_model_id` which is the upstream one. Both are facet keys."""
    from core.entities import ModelV2

    installed = ModelV2(name="Zeta", type="LORA", directory="loras")
    session.add(installed)
    session.commit()
    session.add(
        AssetLora(asset_id=faceted["b"].id, model_id=installed.id, civitai_model_id=777)
    )
    session.commit()

    assert filenames(facet(client, lora_model=installed.id)) == {"f2.png"}
    # And the two keys are independent: the same row is reachable by both.
    assert filenames(facet(client, lora_model=installed.id, lora="777")) == {"f2.png"}


def test_facet_ors_within_a_dimension_and_ands_across(client, faceted):
    both = facet(client, lora="1189691,999")
    assert filenames(both) == {"f1.png", "f2.png", "f3.png"}

    narrowed = facet(client, lora="1189691", tag="blonde hair")
    assert filenames(narrowed) == {"f1.png", "f2.png"}

    # A tag the LoRA images do not have.
    assert filenames(facet(client, lora="1189691", tag="cat ears")) == set()


def test_facet_filters_by_tag_checkpoint_and_character(client, faceted):
    assert filenames(facet(client, tag="cat ears")) == {"f3.png"}
    assert filenames(facet(client, checkpoint="Flux")) == {"f3.png", "f4.png"}
    assert filenames(facet(client, character_id="c1")) == {"f1.png", "f3.png"}


def test_facet_mirrors_the_gallery_filter_vocabulary(client, faceted, session):
    assert filenames(facet(client, search="lighthouse")) == {"f3.png"}
    assert filenames(facet(client, search="f4")) == {"f4.png"}
    assert filenames(facet(client, workspace="main")) == {"f1.png", "f2.png", "f3.png", "f4.png"}

    faceted["a"].workspace = "chat"
    faceted["b"].workspace = "chat"
    session.commit()
    assert filenames(facet(client, workspace="chat")) == {"f1.png", "f2.png"}
    assert filenames(facet(client, workspace="story")) == set()


def test_facet_filters_by_session(client, faceted, session):
    first = GenerationSession(name="batch one", workspace="main", image_count=2)
    session.add(first)
    session.commit()
    session.add(SessionAsset(session_id=first.id, asset_id=faceted["a"].id))
    session.add(SessionAsset(session_id=first.id, asset_id=faceted["c"].id))
    session.commit()

    assert filenames(facet(client, session_id=first.id)) == {"f1.png", "f3.png"}


def test_facet_sorts_date_desc_and_paginates_without_overlap(client, faceted):
    page1 = facet(client, sort="date_desc", limit=2)
    assert filenames(page1) == {"f4.png", "f3.png"}
    assert page1["has_more"] is True

    page2 = facet(client, sort="date_desc", limit=2, cursor=page1["next_cursor"])
    assert filenames(page2) == {"f2.png", "f1.png"}
    assert page2["has_more"] is False
    assert page2["next_cursor"] is None
    # total_matched counts the whole filtered set, not the page.
    assert page1["total_matched"] == 4


def test_facet_sorts_date_asc_with_the_same_cursor_encoding(client, faceted):
    page1 = facet(client, sort="date_asc", limit=3)
    assert filenames(page1) == {"f1.png", "f2.png", "f3.png"}
    page2 = facet(client, sort="date_asc", limit=3, cursor=page1["next_cursor"])
    assert filenames(page2) == {"f4.png"}


def test_facet_name_sorts_are_ordered_in_sql(client, faceted):
    """files.py's keyset path ignores the name sorts and silently returns
    date_desc; here they actually order, and the composite cursor does not
    overlap or skip a filename tie."""
    ascending = facet(client, sort="name_asc", limit=2)
    assert [item["filename"] for item in ascending["items"]] == ["f1.png", "f2.png"]
    rest = facet(client, sort="name_asc", limit=2, cursor=ascending["next_cursor"])
    assert [item["filename"] for item in rest["items"]] == ["f3.png", "f4.png"]
    assert rest["has_more"] is False

    descending = facet(client, sort="name_desc", limit=1)
    assert [item["filename"] for item in descending["items"]] == ["f4.png"]


def test_facet_random_sort_is_stable_for_a_seed(client, faceted):
    first = facet(client, sort="random:abc", limit=2)
    again = facet(client, sort="random:abc", limit=2)
    assert [i["id"] for i in first["items"]] == [i["id"] for i in again["items"]]
    if first["has_more"]:
        page2 = facet(client, sort="random:abc", limit=2, cursor=first["next_cursor"])
        assert not {i["id"] for i in first["items"]} & {i["id"] for i in page2["items"]}


def test_facet_items_carry_the_gallery_shape(client, faceted):
    item = facet(client, limit=1, sort="date_asc")["items"][0]
    for key in (
        "id",
        "name",
        "filename",
        "relative_path",
        "thumbnail",
        "file_url",
        "thumb_url",
        "workspace",
        "character_id",
        "story_id",
        "width",
        "height",
        "created_at",
        "metadata",
        "preview",
    ):
        assert key in item, key


def test_facet_counts_each_dimension_without_its_own_filter(client, faceted):
    """Counting a dimension with its own filter still applied reports 1 for every
    row, which is what makes a filter panel useless."""
    # Three at a time: `MAX_FACET_DIMENSIONS` is a deliberate ceiling (see
    # `test_facet_rejects_bad_input`), and the exclusion is a per-dimension
    # property, so the fourth dimension is checked in its own call.
    payload = facet(client, lora="1189691", group_by="lora,tag,checkpoint")
    # `lora` IS the filtered dimension, and its counts still show 999 — that is
    # the exclusion under test. The other two dimensions are NOT excluded, so
    # they are counted over the LoRA-filtered set (f1, f2), not over everything:
    # a filter panel shows "what else could I pick", not "what exists".
    assert payload["facets"]["lora"] == [
        # count desc, then the value ascending — a tie has to break the same way
        # on every call or the panel reshuffles between renders.
        {"value": "1189691", "count": 2, "label": None},
        {"value": "999", "count": 1, "label": None},
    ]
    assert {c["value"]: c["count"] for c in payload["facets"]["tag"]} == {
        "blonde hair": 2,
    }
    assert {c["value"]: c["count"] for c in payload["facets"]["checkpoint"]} == {
        "Illustrious": 2,
    }
    assert facet(client, group_by="session")["facets"]["session"] == []


def test_facet_counts_include_the_model_name_when_it_is_installed(client, faceted, session):
    from core.entities import ModelV2

    session.add(ModelV2(name="Zeta/ゼータ", type="LORA", directory="loras", civitai_model_id=1189691))
    session.commit()
    payload = facet(client, group_by="lora")
    counts = {c["value"]: c for c in payload["facets"]["lora"]}
    assert counts["1189691"]["label"] == "Zeta/ゼータ"
    assert counts["1189691"]["count"] == 2
    # An applied-but-not-installed LoRA still has a row; the label is just None.
    assert counts["999"]["label"] is None


def test_facet_counts_ignore_the_cursor(client, faceted):
    payload = facet(client, limit=1, group_by="checkpoint", sort="date_desc")
    assert {c["value"]: c["count"] for c in payload["facets"]["checkpoint"]} == {
        "Illustrious": 2,
        "Flux": 2,
    }


def test_facet_returns_the_sessions_a_facet_appears_in(client, faceted, session):
    """The direction a facet on `assets` cannot reach on its own: the LoRA is in
    `asset_loras`, the membership in `session_assets`."""
    first = GenerationSession(name="batch one", workspace="main", image_count=9)
    second = GenerationSession(name="batch two", workspace="main", image_count=9)
    session.add(first)
    session.add(second)
    session.commit()
    session.add(SessionAsset(session_id=first.id, asset_id=faceted["a"].id))
    session.add(SessionAsset(session_id=first.id, asset_id=faceted["d"].id))
    session.add(SessionAsset(session_id=second.id, asset_id=faceted["c"].id))
    session.commit()

    payload = facet(client, lora="1189691", include_sessions=True)
    assert [(s["name"], s["matching_images"]) for s in payload["sessions"]] == [("batch one", 1)]
    assert payload["sessions"][0]["image_count"] == 9
    assert facet(client, lora="1189691", include_sessions=False)["sessions"] == []


def test_facet_honours_a_date_range(client, faceted):
    # `faceted` builds day N as EPOCH + N days, and EPOCH is already 2026-01-01,
    # so f1..f4 are Jan 2..Jan 5 — both bounds inclusive.
    payload = facet(
        client, date_from="2026-01-02T00:00:00Z", date_to="2026-01-03T23:59:59Z"
    )
    assert filenames(payload) == {"f1.png", "f2.png"}
    assert filenames(facet(client, date_from="2026-01-01", date_column="job_completed_at")) == set()


def test_facet_rejects_bad_input(client):
    assert client.get("/api/v2/assets/facet", params={"sort": "colour"}).status_code == 400
    assert client.get("/api/v2/assets/facet", params={"lora": "not-a-number"}).status_code == 400
    assert client.get("/api/v2/assets/facet", params={"date_from": "yesterday"}).status_code == 400
    assert client.get(
        "/api/v2/assets/facet",
        params={"date_from": "2026-02-01", "date_to": "2026-01-01"},
    ).status_code == 400
    assert client.get(
        "/api/v2/assets/facet", params={"group_by": "nonsense"}
    ).status_code == 400
    assert client.get(
        "/api/v2/assets/facet", params={"group_by": "lora,tag,checkpoint,character"}
    ).status_code == 400
    assert client.get("/api/v2/assets/facet", params={"limit": 100000}).status_code == 422
    assert client.get(
        "/api/v2/assets/facet", params={"date_column": "created_at"}
    ).status_code == 400


# ── the endpoints ────────────────────────────────────────────────────────────

def test_tag_endpoints_round_trip(client, asset):
    created = client.post(f"/api/v2/asset/{asset.id}/tags", json={"tag": "pose: kneeling"})
    assert created.status_code == 201
    assert created.json() == {
        "status": "success",
        "asset_id": asset.id,
        "tag": "pose: kneeling",
        "source": "user",
        "created": True,
    }

    listed = client.get(f"/api/v2/asset/{asset.id}/tags")
    assert listed.status_code == 200
    assert listed.json()["tags"] == [
        {
            "tag": "pose: kneeling",
            "source": "user",
            "confidence": None,
            "created_at": listed.json()["tags"][0]["created_at"],
        }
    ]

    removed = client.delete(f"/api/v2/asset/{asset.id}/tags/pose%3A%20kneeling")
    assert removed.status_code == 200
    assert client.get(f"/api/v2/asset/{asset.id}/tags").json()["tags"] == []


def test_tag_endpoint_404s_on_an_unknown_asset(client):
    assert client.get("/api/v2/asset/nope/tags").status_code == 404
    assert client.post("/api/v2/asset/nope/tags", json={"tag": "x"}).status_code == 404
    assert client.delete("/api/v2/asset/nope/tags/x").status_code == 404


def test_tag_endpoint_refuses_to_delete_an_auto_tag(client, asset):
    client.post("/api/v2/assets/auto-tag", json={"limit": 5})
    listed = client.get(f"/api/v2/asset/{asset.id}/tags").json()["tags"]
    auto = next(t for t in listed if t["source"] == "auto")
    # "concept" would come straight back on the next pass.
    assert client.delete(f"/api/v2/asset/{asset.id}/tags/{auto['tag']}").status_code == 404


def test_tag_endpoint_handles_a_tag_containing_a_slash(client, asset):
    """A CivitAI trained word like `Zeta/ゼータ` is a real tag, and the path
    converter is what keeps it addressable."""
    created = client.post(f"/api/v2/asset/{asset.id}/tags", json={"tag": "Zeta/ゼータ"})
    assert created.status_code == 201
    removed = client.delete(f"/api/v2/asset/{asset.id}/tags/{created.json()['tag']}")
    assert removed.status_code == 200


def test_tag_endpoint_rejects_an_empty_tag(client, asset):
    assert client.post(f"/api/v2/asset/{asset.id}/tags", json={"tag": "   "}).status_code == 400


def test_vocabulary_endpoint(client, faceted):
    payload = client.get("/api/v2/tags", params={"limit": 10}).json()
    assert payload["limit"] == 10
    assert payload["truncated"] is False
    assert {row["tag"] for row in payload["tags"]} == {
        "blonde hair",
        "cat ears",
        "pose: kneeling",
    }
    prefixed = client.get("/api/v2/tags", params={"prefix": "cat"}).json()
    assert [row["tag"] for row in prefixed["tags"]] == ["cat ears"]
    assert client.get("/api/v2/tags", params={"limit": 10000}).status_code == 422


def test_auto_tag_endpoint_is_a_bounded_batch(client, session):
    for i in range(3):
        make_asset(session, f"e{i}", day=i + 1, metadata_={"loras": [NESTED_LORA]})

    preview = client.post("/api/v2/assets/auto-tag", json={"dry_run": True})
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert preview.json()["processed"] == 3
    assert session.exec(select(AssetTag)).all() == []

    done = client.post("/api/v2/assets/auto-tag", json={"limit": 2}).json()
    assert done["processed"] == 2
    assert done["truncated"] is True
    assert len({t.asset_id for t in session.exec(select(AssetTag)).all()}) == 2

    resumed = client.post(
        "/api/v2/assets/auto-tag", json={"after_id": done["last_asset_id"]}
    ).json()
    assert resumed["processed"] == 1
    assert len({t.asset_id for t in session.exec(select(AssetTag)).all()}) == 3


def test_auto_tag_endpoint_bounds_are_enforced(client):
    assert client.post("/api/v2/assets/auto-tag", json={"limit": 0}).status_code == 422
    assert client.post(
        "/api/v2/assets/auto-tag", json={"limit": tag_service.MAX_AUTO_TAG_LIMIT + 1}
    ).status_code == 422
    assert client.post(
        "/api/v2/assets/auto-tag", json={"batch_size": tag_service.MAX_AUTO_TAG_BATCH_SIZE + 1}
    ).status_code == 422


# ── the migration ────────────────────────────────────────────────────────────

def test_migration_073_creates_the_table_on_a_bare_database(tmp_path):
    from sqlalchemy import create_engine, inspect

    from infrastructure.migrations.steps import _migration_073_create_asset_tags

    engine = create_engine(f"sqlite:///{tmp_path / 'asset_tags.db'}")
    with engine.begin() as conn:
        # `run_migrations` does `if applied: _record_migration(...)`, so a step
        # that returned False would re-run on every boot forever. It must
        # report True even when create_all already made the table.
        assert _migration_073_create_asset_tags(conn) is True
        tables = set(inspect(conn).get_table_names())
        indexes = {i["name"] for i in inspect(conn).get_indexes("asset_tags")}

    assert "asset_tags" in tables
    assert "uq_asset_tag" in indexes
    # The pattern-ops index is Postgres-only and must be skipped, not failed, on
    # SQLite.
    assert "idx_asset_tag_prefix" not in indexes


def test_migration_073_is_idempotent_and_registered_last():
    from sqlalchemy import create_engine, text

    from infrastructure.migrations.steps import (
        _get_schema_migration_steps,
        _migration_073_create_asset_tags,
    )

    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        assert _migration_073_create_asset_tags(conn) is True
        conn.execute(
            text(
                "INSERT INTO asset_tags (id, asset_id, tag, source, created_at) "
                "VALUES ('t1', 'a1', 'blonde hair', 'auto', '2026-01-01 00:00:00')"
            )
        )
        # A second run must not fail on the existing table or its indexes.
        assert _migration_073_create_asset_tags(conn) is True
        rows = conn.execute(text("SELECT tag, source FROM asset_tags")).all()

    assert rows == [("blonde hair", "auto")]
    # Not "is last" — `073` is the last migration that *creates a table*, and
    # later steps have been appended as indexes and columns. What actually
    # matters is that 073 is registered, and that the version list stays
    # strictly increasing so the runner applies each step exactly once.
    versions = [s.version for s in _get_schema_migration_steps()]
    assert "073_create_asset_tags" in versions
    assert versions == sorted(versions), "migration versions must stay ordered"


def test_asset_tag_confidence_defaults_to_null(session, asset):
    """A user tag has no confidence: "the human said so" is not a number on a
    scale, and defaulting it to 1.0 would invite a UI to rank a hand-typed tag
    above a trained-word tag."""
    session.add(AssetTag(asset_id=asset.id, tag="implicit"))
    session.commit()
    row = session.exec(
        select(AssetTag).where(AssetTag.asset_id == asset.id, AssetTag.tag == "implicit")
    ).one()
    assert row.source == "auto"
    assert row.confidence is None


class TestFacetCursorIsCompatibleWithTheGalleryCursor:
    """`_apply_keyset`'s docstring claims `date_*` and `random` cursors are
    byte-compatible with `GET /api/v2/assets`.

    It asserted that while using a different separator (`\\x1f` vs `|`) and
    `_parse_instant`, which runs `fromisoformat` over the whole composite string
    — so a real gallery cursor raised `ValidationError: cursor must be an
    ISO-8601 timestamp`. A comment that invites a caller to rely on a contract
    is worse than no comment, so the claim is now enforced rather than asserted.
    """

    def test_a_gallery_cursor_is_accepted_by_the_facet_endpoint(self, client, faceted):
        first = facet(client, sort="date_desc", limit=2)
        assert first["has_more"] is True
        cursor = first["next_cursor"]
        assert cursor, "expected a next_cursor from a keyset page"

        # Same cursor, one endpoint over.
        second = facet(client, sort="date_desc", limit=2, cursor=cursor)
        assert second["items"], "the cursor resumed nothing"

    def test_a_bare_gallery_timestamp_still_works(self, client, faceted):
        """The pre-composite cursor shape: one timestamp, ties deliberately
        re-served rather than dropped. The composite path must not break a
        cursor this endpoint already handed out."""
        stamp = (faceted["d"].generated_at or faceted["d"].created_at).isoformat()
        payload = facet(client, sort="date_desc", limit=2, cursor=stamp)
        assert "items" in payload

    def test_a_malformed_cursor_is_a_400_not_a_500(self, client, faceted):
        r = client.get("/api/v2/assets/facet?sort=date_desc&cursor=not-a-cursor")
        assert r.status_code == 400, r.text

    def test_pagination_never_repeats_a_row_across_the_boundary(self, client, faceted):
        """The predicate is the total order over `(ts, id)`, not the timestamp.

        It used to compare the timestamp alone while the ORDER BY carried an
        `Asset.id` tiebreak. That is not a total order, so page 2 re-served
        every row sharing the boundary timestamp — a duplicate page at exactly
        the boundary an infinite scroll is most likely to land on.
        """
        seen: list[str] = []
        cursor = None
        for _ in range(10):
            page = facet(client, sort="date_desc", limit=2, cursor=cursor)
            ids = [item["id"] for item in page["items"]]
            assert not (set(ids) & set(seen)), f"page repeated {set(ids) & set(seen)}"
            seen.extend(ids)
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                break
        assert len(seen) == len({*seen})


# ── the liveness predicate is planned, not just correct ───────────────────────
#
# `Asset.deleted_at IS NULL` and `Asset.id NOT IN (<tombstoned ids>)` return the
# same rows, so a test that only checks the rows cannot tell which one is
# running — and on this deployment the difference is the whole cost of the query.
# These tests pin the *plan-facing* property as well as the rows: PostgreSQL
# costs an `IS NULL` test at a hard-coded 0.5% selectivity, so on a table that is
# 97.8% live it budgets ~85 rows, decides the live set is tiny, and answers
# "is this asset live?" with a memoized btree descent into `assets_pkey` once per
# distinct id — 16,514 of them for `/api/v2/tags`, measured at 390-548 ms. The
# negated form makes the *tombstoned* side the one the planner must budget, which
# is a few hundred rows that `ix_assets_deleted_at` already covers, so the join
# hashes (measured 202-236 ms, `Index Scan using ix_assets_deleted_at rows=389`).


def compiled(statement, dialect=None) -> str:
    """A dialect's SQL for `statement`, as one string."""
    from sqlalchemy.dialects import postgresql

    return " ".join(str(statement.compile(dialect=dialect or postgresql.dialect())).split())


def captured_sql(engine, call) -> list[str]:
    """Every statement `call` sends to `engine`, as one string each."""
    from sqlalchemy import event

    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(_conn, _cursor, statement, _params, _ctx, _many):
        seen.append(" ".join(str(statement).split()))

    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return seen


class TestTagVocabularyPlansAgainstTheTombstoneSide:
    def test_vocabulary_does_not_join_assets_for_liveness(self, session, engine):
        """Reverting to `JOIN assets ... WHERE deleted_at IS NULL` puts this
        assertion back on the failing side. The statement is read off the wire
        rather than rebuilt, so the test cannot drift from what runs."""
        sql = captured_sql(
            engine, lambda: tag_service.list_tag_vocabulary(session, limit=50)
        )[0]
        assert "JOIN assets" not in sql, sql
        assert "deleted_at IS NOT NULL" in sql, sql

    def test_vocabulary_sql_excludes_tombstones_by_negation(self, session, engine):
        sql = captured_sql(
            engine, lambda: tag_service.list_tag_vocabulary(session, prefix="bl", limit=50)
        )[0]
        assert "NOT IN" in sql, sql
        assert "assets.deleted_at IS NOT NULL" in sql, sql
        assert "LIKE" in sql, sql

    def test_the_live_set_is_the_complement_of_the_tombstones(self, session, faceted):
        """The rows still have to be right: a tombstoned image must not keep a tag
        alive in the picker, which is what the picker exists to avoid."""
        faceted["c"].deleted_at = datetime.now(timezone.utc)
        session.add(faceted["c"])
        session.commit()

        counts = {r["tag"]: r["count"] for r in tag_service.list_tag_vocabulary(session)}
        assert counts == {"blonde hair": 2, "pose: kneeling": 1}


class TestFacetLivenessSpelling:
    def _filters(self, **kwargs):
        from api.routes.world_vault.tags import AssetFacetFilters

        return AssetFacetFilters(**kwargs)

    def test_matched_ids_use_the_anti_join_spelling(self):
        """`_matched_ids` is embedded in every facet count, so it is the one that
        has to be hashed rather than index-probed."""
        from api.routes.world_vault.tags import _matched_ids

        sql = compiled(_matched_ids(self._filters()))
        assert "deleted_at IS NOT NULL" in sql, sql
        assert "NOT IN" in sql, sql
        assert "assets.deleted_at IS NULL" not in sql, sql

    def test_the_paged_query_keeps_the_spelling_that_ix_assets_gallery_ts_covers(self):
        """`ix_assets_gallery_ts` is a *partial* index whose predicate is exactly
        `deleted_at IS NULL`. The anti-join form cannot be proven to imply that
        predicate, so switching the paged query over would cost the page its
        index. The two spellings have to stay side by side."""
        from api.routes.world_vault.tags import build_asset_query

        assert "assets.deleted_at IS NULL" in compiled(
            build_asset_query(self._filters())
        )
        assert "deleted_at IS NOT NULL" in compiled(
            build_asset_query(self._filters(), anti_join=True)
        )

    def test_both_spellings_return_the_same_rows(self, session, faceted):
        """The anti-join is a plan hint expressed in SQL; it must not be a second
        definition of "live"."""
        from sqlmodel import select

        from api.routes.world_vault.tags import build_asset_query

        faceted["c"].deleted_at = datetime.now(timezone.utc)
        session.add(faceted["c"])
        session.commit()

        direct = session.exec(
            select(build_asset_query(self._filters()).subquery().c.id)
        ).all()
        negated = session.exec(
            select(
                build_asset_query(self._filters(), anti_join=True).subquery().c.id
            )
        ).all()
        assert sorted(direct) == sorted(negated)
        # And the tombstoned asset really is gone from both.
        assert faceted["c"].id not in {row[0] for row in direct}


class TestFacetFilterDerivationIsSharedPerRequest:
    def _filters(self, **kwargs):
        from api.routes.world_vault.tags import AssetFacetFilters

        return AssetFacetFilters(**kwargs)

    def test_exclude_is_dropped_when_it_cannot_change_the_set(self):
        """`build_asset_query` honours `exclude` for four dimensions and only
        while that dimension is filtered. Everything else must collapse to the
        un-excluded set, or the sharing below is wrong rather than faster."""
        from api.routes.world_vault.tags import _facet_exclusion

        bare = self._filters()
        assert _facet_exclusion(bare, "tag") is None
        assert _facet_exclusion(bare, "lora") is None
        assert _facet_exclusion(bare, "checkpoint") is None
        assert _facet_exclusion(bare, "session") is None
        # `exclude` is not even read for these two.
        assert _facet_exclusion(bare, "character") is None
        assert _facet_exclusion(bare, "workspace") is None

        tagged = self._filters(tags=["blonde hair"])
        assert _facet_exclusion(tagged, "tag") == "tag"
        assert _facet_exclusion(tagged, "checkpoint") is None

    def test_a_request_derives_one_filtered_subquery_not_one_per_dimension(
        self, client, faceted, monkeypatch
    ):
        """The measured request — `group_by=lora,tag,checkpoint`, no filters —
        used to build the filtered asset query four times (three dimensions plus
        `total_matched`) for three identical results. Spy on the derivation
        rather than the timing: this is about how many subqueries exist."""
        from api.routes.world_vault import tags as tags_routes

        calls: list[str | None] = []
        real = tags_routes._matched_ids

        def counting(filters, exclude=None):
            calls.append(exclude)
            return real(filters, exclude=exclude)

        monkeypatch.setattr(tags_routes, "_matched_ids", counting)
        payload = facet(client, group_by="lora,tag,checkpoint", include_sessions=False)

        assert set(payload["facets"]) == {"lora", "tag", "checkpoint"}
        assert len(calls) == 1, f"expected one shared derivation, got {calls}"

    def test_an_active_dimension_still_gets_its_own_derivation(
        self, client, faceted, monkeypatch
    ):
        from api.routes.world_vault import tags as tags_routes

        calls: list[str | None] = []
        real = tags_routes._matched_ids

        def counting(filters, exclude=None):
            calls.append(exclude)
            return real(filters, exclude=exclude)

        monkeypatch.setattr(tags_routes, "_matched_ids", counting)
        payload = facet(
            client, tag="cat ears", group_by="lora,tag,checkpoint", include_sessions=False
        )

        assert filenames(payload) == {"f3.png"}
        # `exclude="tag"` for the tag dimension's counts, plus the shared
        # un-excluded set for lora/checkpoint/total.
        assert sorted(calls, key=str) == sorted([None, "tag"], key=str), calls
