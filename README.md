# BizPilot AI

A local-first Windows desktop application for running a small business: sales,
purchasing, inventory, finance and customers — with AI agents that analyse the same
records, autonomous workflows that act only behind human approval, analytics and
forecasts, and a document knowledge base you can question with citations.

**Version 1.0.0** · Python 3.12 · PySide6 · SQLite · SQLAlchemy 2 · Alembic · LangGraph

---

## Features

| Area | What you get |
| --- | --- |
| Business | Finance, sales, customers, inventory, suppliers, purchase orders, reports |
| AI | Orchestrator with 48 registered tools, five specialist agents, multi-agent collaboration |
| Automation | Six autonomous workflows with approval gates, autonomy policies, audit trail |
| Intelligence | KPIs, analytics, anomaly detection, validated forecasts, risk scoring, what-if simulation |
| Knowledge | Document ingestion, local embeddings, semantic + keyword search, grounded RAG answers |
| Security | Argon2id, TOTP MFA, centralized authorization, AI data governance, hash-chained audit |

Everything core works offline. Cloud AI is optional and off by default.

## Screenshots

The `docs/screenshots` folder holds captures of every major screen taken from the running
application (dashboard, finance, AI command center, collaboration, operations center,
business intelligence, knowledge center, security center).

## System requirements

Windows 10 (21H2+) or Windows 11, 64-bit · 4 GB RAM (8 GB recommended) · 2 GB disk.
No administrator rights needed for normal use.

## Installation

Run `BizPilotAI-1.0.0-Setup.exe`, launch from the Start Menu and complete the
first-launch setup. Business data is stored in `%LOCALAPPDATA%\BizPilotAI`, never in
Program Files. See `docs/INSTALLATION_GUIDE.md`.

## Running from source

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
python -m pip install -r requirements.txt
python main.py
```

## Testing

```bash
python scripts/run_tests.py                     # every suite in order
python -m pytest tests/unit -q                  # 199
python -m pytest tests/security -q              # 150
python -m pytest tests/integration -q           # 278
python -m pytest tests/ui -q                    # 80
python -m pytest tests/end_to_end -q            # 10 acceptance scenarios
python -m pytest tests/performance -q -s        # benchmarks
```

## Packaging

```bash
python deployment/build_windows.py       # tests + PyInstaller + release manifest
python deployment/validate_release.py    # release gate
iscc installer\bizpilot_installer.iss    # Windows installer (Inno Setup 6)
```

PyInstaller cannot cross-compile: produce the Windows artifacts on Windows.

## Documentation

* `docs/USER_GUIDE.md` — day-to-day use
* `docs/ADMIN_GUIDE.md` — roles, policies, approvals, backups
* `docs/DEVELOPER_GUIDE.md` — architecture, database, testing, packaging
* `docs/INSTALLATION_GUIDE.md` — install, Ollama, OCR, offline setup, upgrade
* `docs/SECURITY_GUIDE.md` — controls, limitations, hardening
* `docs/CHANGELOG.md`, `docs/RELEASE_NOTES.md`, `docs/PERFORMANCE_RESULTS.md`

## Known limitations

* Windows executable and installer are produced only on Windows; this build environment
  is Linux, so those artifacts are not included.
* Live Ollama/Gemini inference is not verified here (no local model, no API key).
* OCR requires Tesseract, which is not bundled.
* Neural embeddings require `sentence-transformers`; the shipped model is a deterministic
  lexical vectoriser, and hybrid search compensates for its weaker paraphrase recall.
* SQLite is not encrypted at rest.
