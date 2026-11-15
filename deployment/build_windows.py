"""Reproducible Windows build for BizPilot AI.

Run on Windows from the project root:

    python deployment/build_windows.py            # build
    python deployment/build_windows.py --skip-tests
    python deployment/build_windows.py --validate

PyInstaller cannot cross-compile: running this on Linux/macOS produces an
executable for that platform, not a Windows one.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def run(command: list[str]) -> None:
    print("»", " ".join(command))
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"Command failed with exit code {result.returncode}")


def clean() -> None:
    for path in (DIST, BUILD):
        if path.exists():
            shutil.rmtree(path)
            print("removed", path.relative_to(ROOT))


def run_tests() -> None:
    run([sys.executable, "-m", "pytest", "tests/unit", "tests/security", "-q"])


def build() -> Path:
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "deployment/build.spec",
            "--noconfirm",
            "--clean",
        ]
    )
    suffix = ".exe" if sys.platform.startswith("win") else ""
    executable = DIST / "BizPilotAI" / f"BizPilotAI{suffix}"
    if not executable.exists():
        raise SystemExit("The build finished but the executable is missing")
    return executable


def write_manifest(executable: Path) -> Path:
    sys.path.insert(0, str(ROOT))
    from release.version_info import as_dict  # noqa: PLC0415

    manifest = {
        **as_dict(),
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "executable": str(executable.relative_to(ROOT)),
        "size_bytes": executable.stat().st_size,
    }
    path = ROOT / "release" / "release_manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("manifest written:", path.relative_to(ROOT))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the BizPilot AI desktop application")
    parser.add_argument("--skip-tests", action="store_true", help="skip the test gate")
    parser.add_argument("--no-clean", action="store_true", help="keep previous build output")
    parser.add_argument("--validate", action="store_true", help="run the release validator afterwards")
    args = parser.parse_args()

    if not args.no_clean:
        clean()
    if not args.skip_tests:
        run_tests()
    executable = build()
    write_manifest(executable)
    print(f"Build complete: {executable}")
    if args.validate:
        run([sys.executable, "deployment/validate_release.py"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
