import sqlite3
conn = sqlite3.connect("data/db/comfy.db")
cursor = conn.cursor()
tables = cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for t in tables:
    count = cursor.execute(f"SELECT count(*) FROM {t[0]}").fetchone()[0]
    print(f"{t[0]}: {count}")
