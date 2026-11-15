# BizPilot AI — Installation Guide

## Requirements

* Windows 10 (21H2 or later) or Windows 11, 64-bit
* 4 GB RAM minimum, 8 GB recommended
* 2 GB free disk space (plus space for your documents)
* No administrator rights required for normal use

## Standard installation

1. Run `BizPilotAI-1.0.0-Setup.exe`.
2. Accept the licence, choose the installation folder (default
   `C:\Program Files\BizPilot AI`), and optionally a desktop shortcut.
3. Finish the wizard and launch the application.
4. Complete the first-launch setup (business profile and Super Admin account).

The installer never writes to `Program Files` for your data: everything you create lives
in `%LOCALAPPDATA%\BizPilotAI`.

## Where data lives

| Item | Path |
| --- | --- |
| Database | `%LOCALAPPDATA%\BizPilotAI\data\bizpilot_ai.db` |
| Documents | `%LOCALAPPDATA%\BizPilotAI\documents` |
| Vector index | `%LOCALAPPDATA%\BizPilotAI\vector_store` |
| Logs | `%LOCALAPPDATA%\BizPilotAI\logs` |
| Backups | `%LOCALAPPDATA%\BizPilotAI\backups` |
| Secret key | `%LOCALAPPDATA%\BizPilotAI\secrets\app.key` |

## Optional local AI (Ollama)

1. Install Ollama from ollama.com.
2. In a terminal: `ollama pull llama3.2`
3. Start BizPilot AI → **Knowledge Center → AI Providers** → check the provider status.

Without Ollama, everything except model-generated narration still works: document
answers fall back to deterministic extraction and say so.

## Optional OCR

Install Tesseract OCR and add it to `PATH`. Without it, scanned pages report OCR as
unavailable rather than returning empty text.

## Offline installation

1. Copy the installer, the Ollama installer and the model files to the target machine.
2. Install BizPilot AI and Ollama from the local media.
3. Import the model from the prepared files (`ollama create` from a local Modelfile, or
   copy the `~/.ollama/models` directory).
4. Open **AI Providers** and confirm the model shows as available.

The application never downloads models on its own.

## Upgrading

1. Create a backup (**Security Center → Backup**).
2. Run the newer installer over the existing installation.
3. Launch once; migrations run automatically after a backup is taken.
4. Check **Settings → About** for the version and schema.

If migration fails, the application stops with the reason in the logs. Restore the
backup before retrying.

## Uninstalling

Use *Apps & features*. Uninstalling removes the program only; your business database and
documents are kept. The uninstaller asks once whether to delete them — the default is
to keep.

## Verifying an installation

```bash
python scripts/verify_installation.py     # paths, schema, integrity, optional modules
python scripts/verify_backup.py           # backup, validation and restore check
```
