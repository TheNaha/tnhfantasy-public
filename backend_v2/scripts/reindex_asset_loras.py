"""Populate `asset_loras` from the generation metadata already on each asset.

This is a CLI, not an endpoint, on purpose. On this library it is tens of
thousands of rows and it commits per batch; putting that behind an HTTP request
is how a page becomes a timeout. Run it from a shell:

    # see the scale first, change nothing
    python -m scripts.reindex_asset_loras --dry-run

    # do it in the background, it is resumable
    python -m scripts.reindex_asset_loras

    # bound it, e.g. while testing
    python -m scripts.reindex_asset_loras --limit 500

It reads `assets.metadata_`, not the PNGs, because the compacted metadata
already carries the reference for essentially every row — measured on this
library, 35,439 of 35,463 LoRA references resolve to a CivitAI id from the
metadata alone. Assets whose metadata is empty are reported as
`skipped_no_metadata` rather than silently passed over; recovering those needs a
filesystem re-read and is a different job.

The work is idempotent (rows are deleted and rebuilt per asset) and resumable
(`--after-id`, or just re-run: it re-reads everything and converges).
"""

import argparse
import logging
import time
from collections.abc import Sequence

from sqlmodel import Session, create_engine, func, select

from core.entities import Asset, AssetLora
from services.asset_metadata_index import (
    DEFAULT_BATCH_SIZE,
    reindex_asset_loras,
    refresh_asset_metadata_from_png,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("reindex_asset_loras")


def _log(event: str, **fields) -> None:
    """Log `event key=value ...`.

    The app uses a structlog-style renderer, but this script is often run with
    plain `python`, where `logger.info(event, extra={...})` silently drops every
    field and prints just the event name — which makes a `--dry-run` report
    nothing at all. So the fields are formatted here rather than handed to a
    formatter that may not be installed.
    """
    rendered = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.info(f"{event} {rendered}".rstrip())


def _engine(database_url_override: str | None = None):
    """Build an engine.

    Defaults to the app's own resolution (env var > config.json >
    DEFAULT_CONFIG). On this deployment that is a Postgres instance reachable
    only from inside the compose network, which is why the override exists: the
    same script is useful against a local SQLite file or a throwaway database
    when testing, and running it from the host against the default config would
    silently open the *wrong* database rather than failing.
    """
    from infrastructure.database import database_url

    return create_engine(database_url_override or database_url, echo=False)


def _counts(session: Session) -> tuple[int, int, int]:
    assets = session.exec(select(func.count()).select_from(Asset)).one()
    with_metadata = session.exec(
        select(func.count()).select_from(Asset).where(Asset.metadata_.is_not(None))
    ).one()
    rows = session.exec(select(func.count()).select_from(AssetLora)).one()
    return assets, with_metadata, rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after this many assets (default: all)")
    parser.add_argument("--after-id", type=str, default=None,
                        help="resume after this asset id")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be indexed and write nothing")
    parser.add_argument("--database-url", type=str, default=None,
                        help="override the database URL (default: the app's own)")
    parser.add_argument("--from-png", action="store_true",
                        help=("also re-read each image's embedded PNG metadata and upgrade "
                              "the stored model references. The compacted loras/checkpoint "
                              "entries on historical rows have no CivitAI id, so without "
                              "this a LoRA can only be resolved by filename, which breaks "
                              "as soon as the LoRA is not installed."))
    parser.add_argument("--output-dir", type=str, default=None,
                        help="base the asset relative_path is under (default: the app's own)")
    args = parser.parse_args(argv)

    engine = _engine(args.database_url)
    started = time.time()

    with Session(engine) as session:
        assets, with_metadata, existing_rows = _counts(session)
        _log(
            "reindex_start",
            assets=assets,
            with_metadata=with_metadata,
            existing_asset_lora_rows=existing_rows,
            batch_size=args.batch_size,
            limit=args.limit,
        )
        if args.dry_run:
            _log("dry_run_complete", note="nothing_was_written")
            return 0

        if args.from_png:
            import config as app_config
            output_dir = args.output_dir or app_config.settings.output_dir
            _log("png_refresh_start", output_dir=output_dir)
            png_summary = refresh_asset_metadata_from_png(
                session, output_dir,
                batch_size=args.batch_size, limit=args.limit, after_id=args.after_id,
            )
            _log("png_refresh_complete", **{k: v for k, v in png_summary.items() if k != "last_asset_id"})
            after_id = png_summary["last_asset_id"] or args.after_id
            # The refresh already rebuilt asset_loras for everything it upgraded,
            # but a plain reindex afterwards also covers the assets it skipped.
            args.from_png = False

        totals = {
            "processed": 0, "loras_seen": 0, "loras_resolved": 0,
            "skipped_no_metadata": 0,
        }
        after_id = args.after_id
        while True:
            summary = reindex_asset_loras(
                session,
                batch_size=args.batch_size,
                limit=args.limit,
                after_id=after_id,
            )
            for key in totals:
                totals[key] += summary[key]
            after_id = summary["last_asset_id"] or after_id

            if summary["truncated"]:
                break
            if summary["processed"] == 0 or not summary["loras_seen"] and not after_id:
                break
            if after_id is None:
                break
            # A non-truncated pass that made no progress means we are done.
            if summary["processed"] < args.batch_size:
                break

        _, _, rows_now = _counts(session)
        elapsed = time.time() - started
        _log(
            "reindex_complete",
            **totals,
            rows_now=rows_now,
            rows_added=rows_now - existing_rows,
            elapsed_seconds=round(elapsed, 1),
            last_asset_id=after_id,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
