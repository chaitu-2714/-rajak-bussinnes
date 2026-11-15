"""Remove build output and caches before a release build."""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("build", "dist", ".pytest_cache", "__pycache__")


def main() -> int:
    removed = 0
    for name in TARGETS:
        path = ROOT / name
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
            print("removed", name)
    for cache in ROOT.rglob("__pycache__"):
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)
            removed += 1
    for stale in list(ROOT.rglob("*.pyc")):
        stale.unlink(missing_ok=True)
    print(f"clean complete ({removed} directories removed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
