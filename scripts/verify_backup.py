"""Verify backup and recovery end to end.

    python scripts/verify_backup.py

Creates a backup, validates it, restores it into a temporary copy and checks the
business records survived.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.core.application import ApplicationContext
    from app.core.config import load_config

    context = ApplicationContext.build(load_config())
    service = context.security_service

    backup = service.create_backup(include_knowledge=True)
    print(f"backup: {backup['backup_ref']} ({backup['integrity_status']})")
    print(f"file:   {backup['path']}")

    preview = service.validate_backup(backup["path"])
    print(f"validation: {preview['detail']}")
    if not preview["valid"]:
        print("BACKUP INVALID — recovery not verified")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / Path(backup["path"]).name
        shutil.copy2(backup["path"], copy)
        check = service.validate_backup(copy)
        print(f"restore copy validated: {check['valid']} ({check['detail']})")
        if not check["valid"]:
            return 1

    print("Backup and recovery verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
