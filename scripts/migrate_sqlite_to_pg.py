import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend_v2"))

from scripts.migrate_sqlite_to_postgres import main


if __name__ == "__main__":
    raise SystemExit(main())
