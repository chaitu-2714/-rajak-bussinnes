"""Run every test suite in the batches the release process uses."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BATCHES = (
    ("unit", ["tests/unit"]),
    ("security", ["tests/security"]),
    ("integration", ["tests/integration"]),
    ("ui", ["tests/ui"]),
    ("end-to-end", ["tests/end_to_end"]),
)


def main() -> int:
    failures = 0
    for name, target in BATCHES:
        print(f"\n=== {name} ===")
        result = subprocess.run([sys.executable, "-m", "pytest", *target, "-q"], cwd=ROOT)
        if result.returncode != 0:
            failures += 1
            print(f"!! {name} suite failed")
    print("\nAll suites passed" if not failures else f"\n{failures} suite(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
