# BizPilot AI 1.0.0 — Release Notes

**Release date:** 5 November 2026
**Build:** 1000 · **Database schema:** `0009_security`
**Supported:** Windows 10 (21H2+) and Windows 11, 64-bit · Python 3.12+ for source installs

## What this release is

A local-first Windows desktop application for running a small business: sales,
purchasing, inventory, finance and customers, with AI agents that analyse the same
records, autonomous workflows that act only behind approvals, analytics and
forecasts, and a document knowledge base you can question with citations.

Everything core works offline. Cloud AI (Gemini) is optional and off by default.

## Highlights

* **Approval-gated automation.** Six workflows plan, analyse and then stop before any
  money moves. Approving executes exactly once; changing the amount invalidates the approval.
* **Grounded answers.** Document questions cite the document and page, and refuse when
  the evidence is not there.
* **Honest analytics.** Revenue is never confused with cash, profit states which costs
  are included, and forecasts report the validation error that produced them.
* **Security by default.** Argon2id, optional TOTP MFA, business isolation, hash-chained
  audit trail and a data-classification gate in front of every cloud call.

## Installation

1. Run `BizPilotAI-1.0.0-Setup.exe`.
2. Launch from the Start Menu.
3. Complete the first-launch setup: business profile and Super Admin account.
4. Business data is stored in `%LOCALAPPDATA%\BizPilotAI` — never in Program Files.

## Upgrade

Install over the previous version. Your database and documents are untouched; schema
migrations run on first launch after a backup is taken. Uninstalling never deletes
business records unless you explicitly ask for it.

## Optional AI

Install Ollama and pull a model (`ollama pull llama3.2`) to enable local narration.
Without it the application still answers from documents using deterministic
extraction, and every screen says which provider was used.

## Verified before release

* 717 automated tests across unit, integration, security, UI and end-to-end suites.
* Ten acceptance scenarios executed end to end on real SQLite data.
* Performance measured on this build (see `docs/PERFORMANCE_RESULTS.md`).
* Backup, validation and restore verified; migrations verified from a populated database.

## Not verified in this build

* The Windows executable and installer were **not** produced here: this build was made
  on Linux, where PyInstaller cannot cross-compile and Inno Setup cannot run. The spec,
  build script and installer script are included and validated structurally, not built.
* Live Ollama and Gemini inference (no local model or API key in the build environment).
* OCR of scanned pages (Tesseract not installed in the build environment).
