"""Slim the model records a client puts in a job's metadata.

A generation job's `metadata_` carried the client's *entire* checkpoint object
and every selected LoRA object, verbatim. The frontend's model picker works on
`GET /api/v2/models/`, whose rows are full catalogue records — description,
tags, file list, provider statuses, and for a checkpoint a `preview.images`
array with seven base64 thumbnails.

Measured on the running stack, with one checkpoint and six LoRAs selected:

    checkpoint  15,532 bytes    loras  41,789 bytes    job row  59,171 bytes

Nothing downstream reads any of it:

* `frontend_v2/src/utils/modelDisplay.js#getCheckpointDisplayName` reads
  `display_name || name`. `JobCard`, `JobDetailsModal`, `FeedCard`,
  `ImageLightbox` and `GalleryItem` all go through it.
* `loras` is only ever read for `.length` and for each entry's `name` /
  `strength`.
* `build_job_outputs` copies both into the PNG sidecar and `assets.metadata_`,
  so the bloat propagated a second time and a third: the `assets` table measured
  207 MB for 16,504 rows at an average row width of 3,469 bytes, and
  `GET /api/v2/gallery?limit=48` returned 860 KB — 19.2 KB per image, 15.5 KB of
  it the checkpoint record — against a page the browser renders as thumbnails.
* `GET /api/jobs?limit=20` returned 776 KB, 38 KB per job.

So the fix is a single normalisation at the write path. Everything that reads
these fields keeps working, because the fields it actually uses are kept.

Kept keys are an allowlist, not a denylist, so a new catalogue field cannot
quietly re-inflate every job row written from now on.
"""

from __future__ import annotations

from typing import Any

# Identifies the model and renders its label. `name` is the filename stem the
# provider resolves against, so it must never be dropped.
_CHECKPOINT_KEEP = (
    "model_id",
    "name",
    "display_name",
    "type",
    "directory",
    "base_model",
    "civitai_model_id",
    "hash",
)

# A LoRA additionally needs its weight to be reproducible, and `base_model` for
# the compatibility warning the UI shows.
_LORA_KEEP = (
    "model_id",
    "name",
    "display_name",
    "weight",
    "strength",
    "base_model",
    "civitai_model_id",
    "type",
)

# A model record can arrive as a bare string (a filename) from older clients and
# from `BatchGenerate`, which sends `checkpointName` directly. Anything that is
# not a dict is already small and is passed through unchanged.
_MAX_STRING_CHARS = 512


def _slim(record: Any, keep: tuple[str, ...]) -> Any:
    if not isinstance(record, dict):
        if isinstance(record, str) and len(record) > _MAX_STRING_CHARS:
            return record[:_MAX_STRING_CHARS]
        return record
    return {k: v for k, v in record.items() if k in keep}


def slim_model_metadata(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return `metadata` with `checkpoint` and `loras` reduced to what is used.

    Returns a new dict; the caller's object is not mutated, because
    `_create_job_sync` reuses the same dict afterwards to populate the typed
    routing columns.
    """
    if not isinstance(metadata, dict):
        return metadata

    checkpoint = metadata.get("checkpoint")
    loras = metadata.get("loras")
    if checkpoint is None and loras is None:
        return metadata

    slimmed = dict(metadata)
    if checkpoint is not None:
        slimmed["checkpoint"] = _slim(checkpoint, _CHECKPOINT_KEEP)
    if isinstance(loras, list):
        slimmed["loras"] = [_slim(l, _LORA_KEEP) for l in loras]
    return slimmed
