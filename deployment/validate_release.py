"""Release gate: verify the project is actually releasable.

Checks run in this order and any failure blocks the release:

1. Release metadata is coherent (version, schema, build).
2. The database migrations are present and apply to a fresh database.
3. The application imports and the configuration validates.
4. The user-data directory layout is correct and outside the install tree.
5. The executable and installer artifacts exist (skipped when not built).
6. The test suites pass (optional, ``--with-tests``).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(condition), detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-tests", action="store_true")
    parser.add_argument("--allow-missing-artifacts", action="store_true")
    args = parser.parse_args()

    from release.version_info import as_dict  # noqa: PLC0415

    metadata = as_dict()
    from app.core.config import APP_VERSION  # noqa: PLC0415

    check(
        "Release metadata matches the application version",
        metadata["version"] == APP_VERSION,
        f"{metadata['version']} / {APP_VERSION}",
    )
    check("Build number is set", bool(metadata["build"]), metadata["build"])

    migrations = sorted((ROOT / "migrations" / "versions").glob("*.py"))
    check("All migrations are present", len(migrations) >= 9, f"{len(migrations)} files")
    heads = [path.name for path in migrations if metadata["database_schema"] in path.name]
    check(
        "The declared schema version has a migration file",
        bool(heads),
        heads[0] if heads else "missing",
    )

    with tempfile.TemporaryDirectory() as tmp:
        import os

        os.environ["BIZPILOT_DATA_DIR"] = tmp
        from app.core.config import load_config  # noqa: PLC0415
        from app.core.database import Database  # noqa: PLC0415

        config = load_config()
        database = Database(config)
        database.initialize()
        check(
            "A fresh database migrates to the declared schema",
            database.schema_version() == metadata["database_schema"],
            database.schema_version(),
        )
        check(
            "User data is outside the install directory",
            str(config.data_dir).startswith(tmp),
            str(config.data_dir),
        )
        check(
            "Log, backup, export, document and vector directories exist",
            all(
                path.exists()
                for path in (
                    config.log_dir,
                    config.backup_dir,
                    config.export_dir,
                    config.document_dir,
                    config.vector_dir,
                )
            ),
        )
        database.dispose()

    from app.core.application import ApplicationContext  # noqa: PLC0415
    from app.ui.main_window import PAGE_FACTORIES  # noqa: PLC0415
    from app.ui.navigation import NAV_ITEMS  # noqa: PLC0415

    check("Application imports cleanly", ApplicationContext is not None)
    placeholders = [item.key for item in NAV_ITEMS if item.coming_soon]
    check("No navigation entry is a placeholder", placeholders == [], ", ".join(placeholders))
    check(
        "Every navigation entry has a page factory",
        all(item.key in PAGE_FACTORIES for item in NAV_ITEMS),
    )

    suffix = ".exe" if sys.platform.startswith("win") else ""
    executable = ROOT / "dist" / "BizPilotAI" / f"BizPilotAI{suffix}"
    manifest = ROOT / "release" / "release_manifest.json"
    if args.allow_missing_artifacts:
        print("[SKIP] Build artifacts (not built on this platform)")
    else:
        check("Executable exists", executable.exists(), str(executable.relative_to(ROOT)))
        check("Release manifest exists", manifest.exists())
        if manifest.exists():
            data = json.loads(manifest.read_text())
            check(
                "Manifest matches the release version",
                data.get("version") == metadata["version"],
                str(data.get("version")),
            )

    if args.with_tests:
        for suite in ("tests/unit", "tests/security", "tests/integration", "tests/ui"):
            result = subprocess.run(
                [sys.executable, "-m", "pytest", suite, "-q"], cwd=ROOT
            )
            check(f"Test suite {suite}", result.returncode == 0)

    failures = [name for name, ok, _ in RESULTS if not ok]
    print()
    if failures:
        print(f"RELEASE BLOCKED — {len(failures)} check(s) failed:")
        for name in failures:
            print(" -", name)
        return 1
    print(f"RELEASE READY — {len(RESULTS)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
