#!/usr/bin/env python3
"""Migrate the backend's SQLite database to PostgreSQL.

A thin shim over `backend_v2/scripts/migrate_sqlite_to_postgres.py`, which is
where the migration itself lives (it was moved out of this directory when the
dead scripts were pruned). The `sys.path` insert below is what makes
`backend_v2/scripts` importable as `scripts` from the repo root.

The shebang and the executable bit exist together: the file was mode 755 with no
shebang, so `./scripts/migrate_sqlite_to_pg.py` was an exec-format error on every
platform while `python scripts/migrate_sqlite_to_pg.py` worked fine.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend_v2"))

from scripts.migrate_sqlite_to_postgres import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
