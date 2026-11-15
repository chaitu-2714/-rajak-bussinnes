"""Apply database migrations, taking a backup first.

    python scripts/migrate_database.py --check     # show current vs head
    python scripts/migrate_database.py --backup    # back up, then migrate
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate the BizPilot AI database")
    parser.add_argument("--check", action="store_true", help="report the schema state only")
    parser.add_argument("--backup", action="store_true", help="back up before migrating")
    args = parser.parse_args()

    from app.core.config import load_config
    from app.core.database import Database

    config = load_config()
    database = Database(config)
    current = database.schema_version()
    print(f"database: {config.db_path}")
    print(f"current schema: {current}")

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    alembic_config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(alembic_config)
    head = script.get_current_head()
    print(f"latest schema: {head}")

    if args.check:
        print("up to date" if current == head else "migration required")
        return 0

    if current == head:
        print("nothing to do")
        return 0

    if args.backup:
        from app.services.backup_service import BackupService

        backup = BackupService(database, config)
        created = backup.create_backup()
        print(f"backup written: {getattr(created, 'path', created)}")

    database.initialize()
    print(f"migrated to {database.schema_version()}")
    database.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
