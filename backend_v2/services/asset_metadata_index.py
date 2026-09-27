"""
Normalise the generation metadata carried on an image into a compact, queryable
form, and resolve the model references it contains.

## Why this module exists

The metadata for a generated image is written into the PNG as a `comfy_metadata`
text chunk (`infrastructure/image_processor.py`, `save_image_with_metadata`).
A sidecar `.json` is written ONLY when the PNG could not be written with chunks
— the `image_save_with_metadata_failed` fallback in `services/image_processing.py`.
So embedded is the normal case and the sidecar is a last resort; `read_image_metadata`
reads embedded first and falls back to a sidecar. This module keeps that ordering:
embedded first, never sidecar-preferred.

## The shapes are not stable, and that is the whole problem

Sampling the real library (16k images under `data/output`) found the metadata was
written by several different producers over time, and they do NOT agree:

**LoRA entries** — 198 sampled, *all* of them nested, zero flat:

    {"name": "<file>.safetensors", "preview": {...}, "strength": 1,
     "metadata": {"id": 1189691, "name": "Zeta/ゼータ ...", "description": "<h3>...",
                  "tags": [...], "type": "LORA",
                  "modelVersions": [{"baseModel": ..., "trainedWords": ["a, b, c"]}]}}

The CivitAI id is at `metadata.id` — NOT `civitai_id` — and `description` is
~1.2 KB of raw HTML per entry.

**Checkpoint entries** — five distinct shapes, in descending order of how many
images use them (9609 / 5526 / 321 / 179 / 169 in the sample):

1. flat and rich: `civitai_id`, `model_id`, `base_model`, `tags`, `trained_words`, ...
2. flat + `_originalModel` / `selectedVersionId`
3. minimal: only `name`, `display_name`, `size`, `type`
4. flat + `selectedVersionPreviewId`
5. `metadata_url` + a nested CivitAI payload

So a consumer that reads `entry["civitai_id"]` silently gets `None` for every
LoRA in the library, and a consumer that reads only the flat shape misses the
older nested checkpoints. Everything here therefore tries the flat keys first and
then the nested payload, and never assumes a producer.

## Two things deliberately NOT copied

- `description` — ~1.2 KB of raw HTML per entry. Multiplied across every asset
  row it would dominate the table for text no gallery view renders.
- `preview` / `images` / `stats` / `versions` / `modelVersions` — large binary or
  duplicated structures. `modelVersions` is read for `baseModel` and
  `trainedWords` and then dropped.

`MAX_MODEL_TAGS` bounds the tag copy, because a popular character LoRA carries
30-80 tags and this array is written into every single asset's JSONB.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Upper bound on the CivitAI tag list copied onto each reference. CivitAI orders
# tags by weight, so truncating keeps the most significant ones, and the full
# array remains on `model_tags` — this is a per-asset convenience copy.
MAX_MODEL_TAGS = 20

# CivitAI's trained words arrive as comma-joined booru tag strings, e.g.
# "z3t4, blonde hair, cat ears, low ponytail". Split them so they can be matched
# or used as tag vocabulary rather than being compared as one long string.
_TAG_SPLIT = re.compile(r"\s*,\s*")

# Keys read from a reference's top level, in priority order, for each logical
# field. The first present, non-empty value wins.
_MODEL_ID_KEYS = ("model_id", "civitai_id", "id")
_CIVITAI_ID_KEYS = ("civitai_id", "id", "model_id")
_DISPLAY_NAME_KEYS = ("display_name", "name", "filename")
_FILENAME_KEYS = ("filename", "name", "storage_filename")
_TAGS_KEYS = ("tags",)
_BASE_MODEL_KEYS = ("base_model", "baseModel")
_TRAINED_WORDS_KEYS = ("trained_words", "trainedWords")
_TYPE_KEYS = ("type",)

# HTML-ish content that must never be copied into a per-asset field.
_HTMLISH = re.compile(r"<[^>]{1,200}>|&\w+;|\s{3,}", re.IGNORECASE)


def _first(entry: dict, keys: tuple[str, ...], default: Any = None) -> Any:
    """Return the first present, non-empty value among `keys`."""
    for key in keys:
        if key not in entry:
            continue
        value = entry[key]
        if value is None or value == "" or value == [] or value == {}:
            continue
        return value
    return default


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            return int(stripped)
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _strip_html(value: Any) -> str | None:
    """Reduce an HTML description to plain text, or drop it if it is really markup.

    A display name or base model that is actually a fragment of HTML is worse
    than no value at all, so anything still tag-like after stripping is dropped.
    """
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"<br\s*/?>", " ", value, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]*>", " ", cleaned)
    cleaned = re.sub(r"&[a-z#0-9]+;", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    # A long description is prose, not a label. Truncated for safety.
    if len(cleaned) > 120:
        return None
    return cleaned


def _nested(entry: dict) -> dict:
    """The nested CivitAI payload, if this entry carries one."""
    nested = entry.get("metadata")
    return nested if isinstance(nested, dict) else {}


def _lookup(entry: dict, nested: dict, keys: tuple[str, ...], default: Any = None) -> Any:
    """Read a field from the top level, then from the nested payload."""
    value = _first(entry, keys)
    if value is not None:
        return value
    return _first(nested, keys)


def _normalise_tags(raw: Any) -> list[str] | None:
    if not isinstance(raw, (list, tuple)):
        return None
    tags: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
        if len(tags) >= MAX_MODEL_TAGS:
            break
    return tags or None


def _normalise_trained_words(entry: dict, nested: dict) -> list[str] | None:
    """Collect trained words, splitting the comma-joined forms CivitAI uses.

    The values arrive as a list of strings where each string is itself a
    comma-joined booru tag list. Splitting them is what makes them usable as tag
    vocabulary — which is the point of indexing them at all.
    """
    raw = _first(entry, _TRAINED_WORDS_KEYS) or _first(nested, _TRAINED_WORDS_KEYS)

    # Also look one level deeper, inside modelVersions[0], which is where the
    # nested shape keeps them.
    if raw is None:
        versions = nested.get("modelVersions")
        if isinstance(versions, list):
            for version in versions:
                if isinstance(version, dict):
                    candidate = _first(version, _TRAINED_WORDS_KEYS)
                    if candidate:
                        raw = candidate
                        break

    if raw is None:
        return None
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return None

    words: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        for part in _TAG_SPLIT.split(item):
            cleaned = part.strip()
            # Trailing "a, b, c" sometimes leaves a lone fragment; keep anything
            # that looks like a real token.
            if len(cleaned) < 2 or cleaned in words:
                continue
            words.append(cleaned)
        if len(words) >= MAX_MODEL_TAGS * 5:
            break
    return words or None


def normalise_model_reference(entry: Any, kind: str = "model") -> dict | None:
    """Reduce one LoRA/checkpoint reference to its compact, queryable form.

    Handles both the flat shape (`civitai_id` at the top level) and the nested
    one (`metadata.id` inside a CivitAI payload), because the library contains
    both and the nested form is the ONLY form in use for LoRAs.

    Returns None when the entry carries no usable identity at all — an entry that
    is just a bare filename string yields a dict with the filename, because that
    is still enough to join against `models_v2.storage_filename`.
    """
    if isinstance(entry, str):
        entry = {"name": entry}
    if not isinstance(entry, dict):
        return None

    nested = _nested(entry)

    filename = _lookup(entry, nested, _FILENAME_KEYS)
    if isinstance(filename, str):
        filename = filename.strip()
    if not filename:
        return None

    # `name` doubles as the filename for LoRAs and as the display name for
    # checkpoints, so prefer the explicit filename-ish keys before falling back.
    if not isinstance(filename, str):
        filename = None

    civitai_id = _coerce_int(_lookup(entry, nested, _CIVITAI_ID_KEYS))
    model_id = _coerce_int(_first(entry, ("model_id",)))
    if model_id is None and civitai_id is not None and kind == "checkpoint":
        # On checkpoints the flat `model_id` is the internal ModelV2 id, which
        # only exists for models this project already imported.
        model_id = civitai_id

    # Display name. Order matters and is not "top level first":
    #   - in the NESTED shape the top-level `name` is the .safetensors FILENAME
    #     while `metadata.name` is the human label, so consulting the top level
    #     first would render "Lora_Thing_v2.safetensors" as the display name;
    #   - in the FLAT shape there is no nested payload and `display_name` is
    #     already the human label.
    # So the nested human labels are tried first, then the top-level
    # `display_name`, and the filename is the last resort.
    display_name = (
        _strip_html(_first(nested, ("display_name", "name")))
        or _strip_html(_first(entry, ("display_name",)))
        or filename
    )
    base_model = _strip_html(_lookup(entry, nested, _BASE_MODEL_KEYS))
    if base_model is None and isinstance(nested.get("modelVersions"), list):
        for version in nested["modelVersions"]:
            if isinstance(version, dict):
                base_model = _strip_html(_first(version, _BASE_MODEL_KEYS))
                if base_model:
                    break

    compact: dict[str, Any] = {
        "name": filename,
        "display_name": display_name,
        "filename": filename,
    }
    if model_id is not None:
        compact["model_id"] = model_id
    if civitai_id is not None:
        compact["civitai_id"] = civitai_id
    if base_model:
        compact["base_model"] = base_model

    model_type = _lookup(entry, nested, _TYPE_KEYS)
    if isinstance(model_type, str) and model_type:
        compact["type"] = model_type

    tags = _normalise_tags(_lookup(entry, nested, _TAGS_KEYS))
    if tags:
        compact["tags"] = tags

    trained_words = _normalise_trained_words(entry, nested)
    if trained_words:
        compact["trained_words"] = trained_words

    return compact


def _iter_entries(value: Any) -> list[Any]:
    """Accept both the list and the single-object forms."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def normalise_loras(metadata: dict | None) -> list[dict]:
    """Normalise `metadata['loras']`, preserving each entry's strength."""
    out: list[dict] = []
    for entry in _iter_entries((metadata or {}).get("loras")):
        compact = normalise_model_reference(entry, kind="lora")
        if not compact:
            continue
        strength = _coerce_float(
            entry.get("strength") if isinstance(entry, dict) else None
        )
        if strength is not None:
            compact["strength"] = strength
        out.append(compact)
    return out


def normalise_checkpoints(metadata: dict | None) -> list[dict]:
    """Normalise `metadata['checkpoint']`, which is usually a single object."""
    out: list[dict] = []
    for entry in _iter_entries((metadata or {}).get("checkpoint")):
        compact = normalise_model_reference(entry, kind="checkpoint")
        if compact:
            out.append(compact)
    return out


def extract_tag_vocabulary(metadata: dict | None) -> set[str]:
    """Booru-style tag vocabulary available on one image.

    Sourced from the LoRAs actually used for the image: their CivitAI tags and
    their trained words, which CivitAI stores as comma-joined booru tag strings.
    That makes "this LoRA is for character X" and "this LoRA teaches pose Y"
    queryable without asking the user to type tags by hand.
    """
    vocabulary: set[str] = set()
    for entry in normalise_loras(metadata):
        for tag in entry.get("tags") or []:
            vocabulary.add(tag)
        for word in entry.get("trained_words") or []:
            vocabulary.add(word)
    return vocabulary


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

from datetime import datetime, timezone  # noqa: E402

from sqlmodel import Session, select  # noqa: E402

from core.entities import Asset, AssetLora, ModelFile, ModelVersion  # noqa: E402

# Rows per transaction. Small enough that a long run can be interrupted without
# losing much, large enough that the per-batch commit is not the bottleneck.
DEFAULT_BATCH_SIZE = 200


def _resolve_internal_model_ids(session: Session, civitai_ids: set[int]) -> dict[int, str]:
    """Map CivitAI model ids to internal `models_v2` ids, for the ones we imported.

    A LoRA is frequently *applied* long before it is *installed*, so most
    references will have no internal id. That is fine: `civitai_model_id` is the
    stable upstream identity and is what the facet filter keys on.
    """
    if not civitai_ids:
        return {}

    from core.entities import ModelV2  # local import: avoids a cycle at module load

    rows = session.exec(
        select(ModelV2.civitai_model_id, ModelV2.id).where(
            ModelV2.civitai_model_id.in_(sorted(civitai_ids))
        )
    ).all()
    return {row[0]: row[1] for row in rows if row[0] is not None}


def _filename_to_model_id(session: Session, filenames: set[str]) -> dict[str, str]:
    """Map a LoRA/checkpoint filename to the internal model id owning that file.

    The chain is two hops: `model_files.storage_filename` belongs to a
    `ModelVersion` (via `version_id`), which belongs to a `ModelV2` (via
    `model_id`). There is no direct file→model column.

    This is the second resolution path, for references whose embedded metadata
    predates the point where a CivitAI id was recorded. Measured on this
    library that is 24 of 35,463 LoRA references, so it is a fallback rather
    than the main route — but it is what keeps the last fraction addressable.
    """
    if not filenames:
        return {}
    rows = session.exec(
        select(ModelFile.storage_filename, ModelVersion.model_id)
        .join(ModelVersion, ModelFile.version_id == ModelVersion.id)
        .where(ModelFile.storage_filename.in_(sorted(filenames)))
    ).all()
    return {row[0]: row[1] for row in rows if row[0] and row[1]}


def index_asset_loras(session: Session, asset: Asset) -> tuple[int, int]:
    """Rewrite `asset_loras` from the asset's normalised metadata.

    Idempotent: the rows for this asset are deleted and rebuilt, so a re-run
    after a compaction change converges rather than accumulating.

    Returns `(loras_seen, loras_resolved)`.
    """
    loras = normalise_loras(asset.metadata_ or None)

    # Delete-then-insert rather than diffing. The row count per image is tiny
    # (usually 0-4), and a diff would need the old shape to be trustworthy.
    existing = session.exec(
        select(AssetLora).where(AssetLora.asset_id == asset.id)
    ).all()
    for row in existing:
        session.delete(row)

    if not loras:
        return (0, 0)

    civitai_by_internal = _resolve_internal_model_ids(
        session, {e["civitai_id"] for e in loras if e.get("civitai_id") is not None}
    )
    internal_by_filename = _filename_to_model_id(
        session, {e["filename"] for e in loras if e.get("filename")}
    )

    seen = 0
    resolved = 0
    now = datetime.now(timezone.utc)
    for entry in loras:
        filename = entry.get("filename")
        if not filename:
            continue
        civitai_id = entry.get("civitai_id")
        internal_id = (
            entry.get("model_id")
            or civitai_by_internal.get(civitai_id)
            or internal_by_filename.get(filename)
        )
        if internal_id is not None or civitai_id is not None:
            resolved += 1
        session.add(
            AssetLora(
                asset_id=asset.id,
                model_id=internal_id,
                civitai_model_id=civitai_id,
                strength=entry.get("strength"),
                created_at=now,
            )
        )
        seen += 1

    return (seen, resolved)


def reindex_asset_loras(
    session: Session,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
    after_id: str | None = None,
) -> dict:
    """Populate `asset_loras` for assets that have not been indexed yet.

    Runs over `assets.metadata_` — NOT by re-opening the PNGs — because the
    compacted metadata already carries what this needs for the overwhelming
    majority of rows. Only assets whose metadata is empty would need a
    filesystem re-read, and those are reported as `skipped_no_metadata` rather
    than silently passed over.

    This is deliberately a batch job and NOT reachable from a request handler:
    on a 16k-image library it is minutes of work, and doing that inside an HTTP
    request is how a page becomes a timeout.

    Args:
        batch_size: rows per transaction. Also the commit cadence.
        limit: stop after this many assets; None means "until done".
        after_id: resume keyset — only assets with a greater id. Pass the
            `last_asset_id` from a previous call to continue where it stopped.

    Returns a summary dict, including `last_asset_id` for resuming.
    """
    statement = select(Asset).where(Asset.deleted_at.is_(None))
    if after_id:
        statement = statement.where(Asset.id > after_id)
    statement = statement.order_by(Asset.id).limit(batch_size)

    processed = 0
    loras_seen = 0
    loras_resolved = 0
    skipped_no_metadata = 0
    last_id = after_id
    truncated = False

    while True:
        assets = session.exec(statement).all()
        if not assets:
            break

        for asset in assets:
            last_id = asset.id
            processed += 1
            if not asset.metadata_:
                skipped_no_metadata += 1
                continue
            seen, resolved = index_asset_loras(session, asset)
            loras_seen += seen
            loras_resolved += resolved

        session.commit()

        if limit is not None and processed >= limit:
            truncated = True
            break
        if len(assets) < batch_size:
            break
        # Keyset by id so a resume never re-reads the batch we just committed.
        statement = statement.where(Asset.id > last_id)

    return {
        "processed": processed,
        "loras_seen": loras_seen,
        "loras_resolved": loras_resolved,
        "skipped_no_metadata": skipped_no_metadata,
        "last_asset_id": last_id,
        "truncated": truncated,
    }
