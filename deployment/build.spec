# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for BizPilot AI (Windows).

Build with:
    python -m PyInstaller deployment/build.spec --noconfirm

Output: dist/BizPilotAI/BizPilotAI.exe (one-folder build)

Notes
-----
* The user database is NOT bundled. It is created on first launch in the
  per-user application data directory (%LOCALAPPDATA%\\BizPilotAI on Windows).
* Qt resources, QSS stylesheets and Alembic migrations are bundled read-only.
* PyInstaller cannot cross-compile: run this on Windows to obtain a Windows
  executable.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

PROJECT_ROOT = Path(SPECPATH).resolve().parent
ICON_FILE = PROJECT_ROOT / "resources" / "icons" / "app_icon.ico"

hidden_imports = [
    "app",
    "alembic.runtime.migration",
    "alembic.operations",
    "alembic.autogenerate",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "pyqtgraph",
    "argon2",
    "pydantic",
    "pyotp",
    "qrcode",
    "cryptography.fernet",
    "keyring",
    "fitz",
    "docx",
    "openpyxl",
    "pptx",
    "pandas",
    "PIL",
    "reportlab",
    "ollama",
    "google.genai",
] + collect_submodules("app")

datas = [
    (str(PROJECT_ROOT / "resources"), "resources"),
    (str(PROJECT_ROOT / "migrations"), "migrations"),
    (str(PROJECT_ROOT / "alembic.ini"), "."),
    (str(PROJECT_ROOT / "release"), "release"),
    (str(PROJECT_ROOT / "docs" / "RELEASE_NOTES.md"), "docs"),
]

a = Analysis(
    [str(PROJECT_ROOT / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BizPilotAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_FILE) if (ICON_FILE.exists() and sys.platform.startswith("win")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BizPilotAI",
)
