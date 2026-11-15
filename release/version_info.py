"""Release metadata for BizPilot AI.

Phase numbers (1-10) describe the development history; the *release* version
follows semantic versioning and is what the About box and the installer show.
"""

from __future__ import annotations

APP_NAME = "BizPilot AI"
RELEASE_VERSION = "1.0.0"
BUILD_NUMBER = "1000"
RELEASE_DATE = "2026-11-05"
CHANNEL = "stable"
PUBLISHER = "BizPilot AI"
COPYRIGHT = "© 2026 BizPilot AI"
DATABASE_SCHEMA_VERSION = "0009_security"
SUPPORTED_WINDOWS = ("Windows 10 (21H2 or later, 64-bit)", "Windows 11 (64-bit)")
MIN_PYTHON = "3.12"
RELEASE_NOTES_SUMMARY = (
    "First stable release: business modules, AI orchestrator, five agents, "
    "multi-agent collaboration, autonomous workflows with approvals, analytics and "
    "forecasting, hybrid RAG over business documents, and enterprise security."
)


def version_tuple() -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in RELEASE_VERSION.split("."))
    return major, minor, patch


def version_string(*, with_build: bool = False) -> str:
    base = f"{APP_NAME} {RELEASE_VERSION}"
    return f"{base} (build {BUILD_NUMBER})" if with_build else base


def as_dict() -> dict:
    return {
        "app_name": APP_NAME,
        "version": RELEASE_VERSION,
        "build": BUILD_NUMBER,
        "release_date": RELEASE_DATE,
        "channel": CHANNEL,
        "publisher": PUBLISHER,
        "copyright": COPYRIGHT,
        "database_schema": DATABASE_SCHEMA_VERSION,
        "supported_windows": list(SUPPORTED_WINDOWS),
        "min_python": MIN_PYTHON,
        "summary": RELEASE_NOTES_SUMMARY,
    }
