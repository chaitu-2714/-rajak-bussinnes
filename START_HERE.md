# BizPilot AI 1.0.0 — complete project

Everything for the project is inside this one archive. Nothing else is needed to
read, run or rebuild it.

## What is inside

```
BizPilot_AI/
├── app/                  the application (284 files)
├── tests/                723 automated tests (65 files)
├── migrations/           9 database migrations, head 0009_security
├── resources/            icons and QSS themes
├── deployment/           PyInstaller spec + build / clean / validate scripts
├── installer/            Inno Setup installer script
├── scripts/              run_tests, migrate_database, verify_installation, verify_backup
├── release/              version metadata (1.0.0, build 1000)
├── docs/                 user, admin, developer, installation and security guides,
│                         phase 2–10 reports, performance results, changelog
│   └── screenshots/      42 screen captures + release/ gallery (index.html)
├── main.py               start the application
├── requirements.txt      dependencies
├── alembic.ini           migration configuration
├── .env.example          optional environment overrides
└── README.md             overview, features, install, test, package
```

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
python -m pip install -r requirements.txt
python main.py
```

The first launch asks for the business profile and the Super Admin account. The
database is created automatically in `%LOCALAPPDATA%\BizPilotAI` — never inside
this folder.

## Test it

```bash
python -m pytest tests/unit -q            # 199 tests
python -m pytest tests/security -q        # 150 tests
python -m pytest tests/integration -q     # 278 tests
python -m pytest tests/ui -q              # 80 tests
python -m pytest tests/end_to_end -q      # 10 acceptance scenarios
python -m pytest tests/performance -q -s  # benchmarks
```

## Build the Windows application

```bat
python deployment\build_windows.py
iscc installer\bizpilot_installer.iss
```

Both must run on Windows: PyInstaller cannot cross-compile and Inno Setup is a
Windows tool. The build script runs the tests first and writes a release manifest.

## Not included, by design

* `BizPilotAI.exe` and the installer — built on Windows with the commands above.
* The business database (`.db`) — created on first launch.
* API keys and the MFA encryption key — never shipped; entered by the administrator.

## Where to read next

* `docs/USER_GUIDE.md` — how to use every screen
* `docs/ADMIN_GUIDE.md` — roles, policies, approvals, backups
* `docs/INSTALLATION_GUIDE.md` — install, Ollama, OCR, offline setup, upgrade
* `docs/SECURITY_GUIDE.md` — controls and their known limitations
* `docs/PHASE10_REPORT.md` — the release audit, defects fixed and test results
* `docs/screenshots/release/index.html` — captioned gallery of the running app
