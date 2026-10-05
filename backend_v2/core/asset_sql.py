"""SQL expressions derived from `Asset`, defined once.

Three expressions were each written twice — in `services/statistics_service` and
in `services/session_detector` — with a comment on each side saying the two had
to stay identical and no test asserting it. They had not drifted yet, which is
the only reason nobody noticed the coupling was unguarded:

* `RESOLVED_TS` — the instant an asset counts towards, preferring the job's own
  completion time over the row's own timestamps. Analytics day-buckets and
  session detection bucket on this; if they disagree, an image lands on two
  different days in two different views of the same library.
* `CHECKPOINT_KEY` — the grouping key. The `checkpoint_name` rollup column is
  preferred, with the jsonb forms behind it so a row written before migration 067
  still groups under the same name.
* `META` — the raw `metadata_` column, and `meta_string()` for a top-level field
  as text. `_META[key].as_string()` compiles to `(metadata_ ->> 'key')::varchar`
  on Postgres and `JSON_EXTRACT(metadata_, '$."key"')` on SQLite, so both
  dialects stay covered by one definition.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.sql.elements import ColumnElement

from core.entities import Asset

META = Asset.metadata_


def meta_string(key: str) -> ColumnElement[Any]:
    """A field of `assets.metadata_` as text, on either dialect."""
    return META[key].as_string()


RESOLVED_TS = func.coalesce(Asset.job_completed_at, Asset.generated_at, Asset.created_at)

# A checkpoint is an object with a `name`; legacy rows stored a bare string.
CHECKPOINT_KEY = func.coalesce(
    Asset.checkpoint_name,
    META["checkpoint"]["name"].as_string(),
    META["checkpoint"].as_string(),
)

__all__ = ["META", "meta_string", "RESOLVED_TS", "CHECKPOINT_KEY"]