import json
from sqlalchemy import create_engine, MetaData, select
engine = create_engine("sqlite:////data/db/comfy.db")
meta = MetaData()
meta.reflect(bind=engine)
table = meta.tables["models_v2"]
with engine.connect() as conn:
    rows = conn.execute(select(table)).fetchall()
    print("models_v2 rows from sqlalchemy:", len(rows))
