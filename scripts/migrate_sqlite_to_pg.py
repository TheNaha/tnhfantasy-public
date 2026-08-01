import sqlite3
import psycopg2
import psycopg2.extras
import uuid
import json

# Paths and URIs
SQLITE_DB = './data/db/comfy.db'
# Try to get from env or default to compose hostname
COMFY_DATABASE_URL = "postgresql://comfy:comfy@localhost:5432/comfy"

def main():
    print(f"Connecting to SQLite: {SQLITE_DB}")
    sl_conn = sqlite3.connect(SQLITE_DB)
    sl_conn.row_factory = sqlite3.Row
    sl_cur = sl_conn.cursor()

    print(f"Connecting to PostgreSQL: {COMFY_DATABASE_URL}")
    pg_conn = psycopg2.connect(COMFY_DATABASE_URL)
    pg_cur = pg_conn.cursor()

    # Get all tables from SQLite
    sl_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [row['name'] for row in sl_cur.fetchall()]
    
    print(f"Found tables: {tables}")

    # UUID mappings for tables that are migrating from INT to UUID
    collection_id_map = {} # old_int_id -> new_uuid_str

    for table in tables:
        print(f"Migrating table: {table}")
        sl_cur.execute(f'SELECT * FROM "{table}"')
        rows = sl_cur.fetchall()
        if not rows:
            print(f"  Table {table} is empty, skipping.")
            continue
            
        columns = [description[0] for description in sl_cur.description]
        if table == 'jobs' and 'task_type' not in columns:
            columns.append('task_type')
        if table == 'providers' and 'worker_type' not in columns:
            columns.append('worker_type')
        
        # We will build cols_str later since we might append to columns list

        pg_data = []
        for row in rows:
            row_dict = dict(row)
            
            # Special processing for PKs moving to UUID
            if table == 'prompts':
                if 'id' in row_dict:
                    row_dict['id'] = str(uuid.uuid4())
                    
            elif table == 'collections':
                if 'id' in row_dict:
                    old_id = row_dict['id']
                    new_id = str(uuid.uuid4())
                    collection_id_map[old_id] = new_id
                    row_dict['id'] = new_id
                    
            elif table == 'collection_images':
                if 'id' in row_dict:
                    row_dict['id'] = str(uuid.uuid4())
                if 'collection_id' in row_dict:
                    old_col_id = row_dict['collection_id']
                    if old_col_id in collection_id_map:
                        row_dict['collection_id'] = collection_id_map[old_col_id]
                    else:
                        print(f"  Warning: collection_id {old_col_id} not found in map!")
            
            # Convert values to handle types properly 
            # (especially boolean to python bool if SQLite stored as 0/1)
            # or JSON strings
            
            # Map known boolean columns
            bool_cols = {
                'enabled', 'fallback_enabled', 'nsfw', 'is_enabled', 
                'is_default', 'is_primary', 'has_meta', 'has_positive_prompt',
                'favorite'
            }
            
            if table == 'jobs' and 'task_type' not in row_dict:
                row_dict['task_type'] = 'image'
            
            if table == 'providers' and 'worker_type' not in row_dict:
                row_dict['worker_type'] = 'image'

            pg_row = []
            for col in columns:
                val = row_dict.get(col)
                if col in bool_cols and val is not None:
                    val = bool(val)
                pg_row.append(val)
                
            pg_data.append(tuple(pg_row))
            
        # Prepare insert query
        cols_str = ', '.join([f'"{col}"' for col in columns])
        placeholders = ', '.join(['%s'] * len(columns))
        insert_query = f'INSERT INTO "{table}" ({cols_str}) VALUES ({placeholders})'
            
        try:
            psycopg2.extras.execute_batch(pg_cur, insert_query, pg_data)
            print(f"  Inserted {len(pg_data)} rows into {table}.")
        except Exception as e:
            print(f"  Error inserting into {table}: {e}")
            pg_conn.rollback()
            continue
            
    pg_conn.commit()
    print("Migration complete!")
    
    sl_conn.close()
    pg_conn.close()

if __name__ == "__main__":
    main()
