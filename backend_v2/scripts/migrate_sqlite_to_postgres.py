import json
from sqlalchemy import create_engine, MetaData, select, insert, text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

sqlite_url = "sqlite:////data/comfy_backup.db"
pg_url = "postgresql://comfy:comfy@db:5432/comfy"

sqlite_engine = create_engine(sqlite_url)
pg_engine = create_engine(pg_url)

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

def migrate():
    # We will use reflection from the Postgres database as the source of truth for the schema,
    # since it was just created with create_all().
    pg_meta = MetaData()
    pg_meta.reflect(bind=pg_engine)
    
    sqlite_meta = MetaData()
    sqlite_meta.reflect(bind=sqlite_engine)

    with pg_engine.begin() as pg_conn:
        with sqlite_engine.connect() as sqlite_conn:
            for table_name in TABLES_TO_MIGRATE:
                if table_name not in pg_meta.tables or table_name not in sqlite_meta.tables:
                    logger.warning(f"Skipping {table_name}: not found in one of the databases.")
                    continue
                
                logger.info(f"Migrating {table_name}...")
                
                # Clear existing data in Postgres table
                pg_conn.execute(text(f"TRUNCATE TABLE {table_name} CASCADE;"))
                
                sqlite_table = sqlite_meta.tables[table_name]
                pg_table = pg_meta.tables[table_name]
                
                # Fetch all rows from SQLite
                rows = sqlite_conn.execute(select(sqlite_table)).fetchall()
                if not rows:
                    logger.info(f"{table_name} is empty.")
                    continue
                
                # SQLite JSON columns might be returned as strings. We need to parse them if PG expects JSONB/JSON.
                # Find JSON columns in Postgres
                json_cols = [c.name for c in pg_table.columns if str(c.type) in ('JSON', 'JSONB')]
                
                # We can construct dicts for bulk insert
                insert_data = []
                for row in rows:
                    row_dict = dict(row._mapping)
                    for jc in json_cols:
                        if jc in row_dict and isinstance(row_dict[jc], str):
                            try:
                                row_dict[jc] = json.loads(row_dict[jc])
                            except Exception:
                                row_dict[jc] = {}
                    
                    # Fill in defaults for missing columns (added in new schema)
                    for col in pg_table.columns:
                        if col.name not in row_dict:
                            if col.name == 'worker_type':
                                row_dict[col.name] = 'image'
                            elif col.name == 'task_type':
                                row_dict[col.name] = 'image'
                            elif col.default is not None:
                                # Use default value from SQLAlchemy column if available
                                row_dict[col.name] = col.default.arg
                                
                    insert_data.append(row_dict)
                
                # Bulk insert into Postgres
                try:
                    pg_conn.execute(insert(pg_table), insert_data)
                    logger.info(f"Successfully migrated {len(insert_data)} rows into {table_name}.")
                except Exception as e:
                    logger.error(f"Failed to migrate {table_name}: {e}")
                    raise

if __name__ == "__main__":
    migrate()
