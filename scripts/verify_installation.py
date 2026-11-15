"""Verify an installed BizPilot AI: paths, database, migrations and dependencies.

    python scripts/verify_installation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from app.core.config import APP_VERSION, load_config
    from app.core.database import Database

    config = load_config()
    print(f"BizPilot AI {APP_VERSION}")
    print(f"data directory: {config.data_dir}")

    problems: list[str] = []
    if not config.data_dir.exists():
        problems.append("the data directory does not exist")
    for name, path in (
        ("database", config.db_path),
        ("logs", config.log_dir),
        ("backups", config.backup_dir),
        ("documents", config.document_dir),
        ("vector store", config.vector_dir),
    ):
        print(f"  {name:14s} {'present' if path.exists() else 'MISSING'}  {path}")
        if name == "database" and not path.exists():
            print("    (the database is created by the first-launch setup)")

    if config.db_path.exists():
        database = Database(config)
        database.initialize()
        print(f"schema version: {database.schema_version()}")
        integrity = database.integrity_check()
        print(f"integrity: {integrity}")
        if integrity != (True, "ok"):
            problems.append("database integrity check failed")
        database.dispose()

    optional = {}
    for module, label in (
        ("pyotp", "TOTP multi-factor authentication"),
        ("qrcode", "MFA QR codes"),
        ("pytesseract", "OCR (Tesseract)"),
        ("sentence_transformers", "neural embeddings"),
        ("ollama", "Ollama client"),
    ):
        try:
            __import__(module)
            optional[label] = "available"
        except Exception:  # noqa: BLE001
            optional[label] = "not installed"
    print("optional dependencies:")
    for label, status in optional.items():
        print(f"  {label:32s} {status}")

    if problems:
        print("\nPROBLEMS FOUND:")
        for problem in problems:
            print(" -", problem)
        return 1
    print("\nInstallation verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
