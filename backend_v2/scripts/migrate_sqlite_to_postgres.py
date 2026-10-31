import argparse
import json
import logging
import os
from collections.abc import Sequence

from sqlalchemy import MetaData, create_engine, func, insert, select, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

TABLES_TO_MIGRATE = [
    "providers",
    "load_balancing_config",
    "load_balancer_state",
    "jobs",
    "models_v2",
    "model_versions",
    "model_tags",
    "model_files",
    "model_images",
    "provider_version_status",
    "prompts",
    "collections",
    "collection_images",
]


def _row_count(connection, table) -> int:
    return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def migrate(
    sqlite_url: str,
    pg_url: str,
    *,
    assume_yes: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    sqlite_engine = create_engine(sqlite_url)
    pg_engine = create_engine(pg_url)
    pg_meta = MetaData()
    sqlite_meta = MetaData()
    pg_meta.reflect(bind=pg_engine)
    sqlite_meta.reflect(bind=sqlite_engine)

    counts: dict[str, int] = {}
    with sqlite_engine.connect() as sqlite_conn:
        for table_name in TABLES_TO_MIGRATE:
            if table_name not in pg_meta.tables or table_name not in sqlite_meta.tables:
                logger.warning("Skipping %s: not found in one of the databases", table_name)
                continue
            counts[table_name] = _row_count(sqlite_conn, sqlite_meta.tables[table_name])

    if dry_run:
        logger.info("Dry run: source row counts: %s", counts)
        return counts

    pending = {table: count for table, count in counts.items() if count}
    if pending and not assume_yes:
        raise RuntimeError(
            "Refusing to replace PostgreSQL data without --yes. "
            f"Source rows: {pending}"
        )

    with pg_engine.begin() as pg_conn, sqlite_engine.connect() as sqlite_conn:
        for table_name, count in counts.items():
            if not count:
                logger.info("%s is empty; leaving PostgreSQL data unchanged", table_name)
                continue

            logger.info("Migrating %s (%d rows)", table_name, count)
            pg_conn.execute(text(f'TRUNCATE TABLE "{table_name}" CASCADE'))
            sqlite_table = sqlite_meta.tables[table_name]
            pg_table = pg_meta.tables[table_name]
            json_cols = {
                column.name
                for column in pg_table.columns
                if str(column.type) in ("JSON", "JSONB")
            }
            insert_data = []
            for row in sqlite_conn.execute(select(sqlite_table)).mappings():
                row_dict = dict(row)
                for column_name in json_cols:
                    value = row_dict.get(column_name)
                    if isinstance(value, str):
                        try:
                            row_dict[column_name] = json.loads(value)
                        except json.JSONDecodeError as exc:
                            raise ValueError(
                                f"Invalid JSON in {table_name}.{column_name}"
                            ) from exc
                for column in pg_table.columns:
                    if column.name not in row_dict and column.name in {
                        "worker_type",
                        "task_type",
                    }:
                        row_dict[column.name] = "image"
                insert_data.append(
                    {column.name: row_dict[column.name] for column in pg_table.columns if column.name in row_dict}
                )

            if insert_data:
                pg_conn.execute(insert(pg_table), insert_data)
            logger.info("Migrated %d rows into %s", len(insert_data), table_name)

    return counts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate a TNHFantasy SQLite database to PostgreSQL")
    parser.add_argument(
        "--sqlite-url",
        default=os.getenv("COMFY_SQLITE_DATABASE_URL"),
        help="SQLite SQLAlchemy URL; defaults to COMFY_SQLITE_DATABASE_URL",
    )
    parser.add_argument(
        "--pg-url",
        default=os.getenv("COMFY_DATABASE_URL"),
        help="PostgreSQL SQLAlchemy URL; defaults to COMFY_DATABASE_URL",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report source row counts without writing")
    parser.add_argument("--yes", action="store_true", help="Allow replacement of non-empty PostgreSQL tables")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.sqlite_url or not args.pg_url:
        parser.error("--sqlite-url and --pg-url or their environment variables are required")
    migrate(args.sqlite_url, args.pg_url, assume_yes=args.yes, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
