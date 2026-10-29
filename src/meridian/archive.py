"""Remove old result bundles so the results folder does not grow without limit."""

import shutil
import time
from pathlib import Path

SECONDS_PER_DAY = 3600


def old_bundles(root: str | Path, days: int) -> list[Path]:
    """Bundle folders under root whose completion manifest is older than ``days`` days."""
    cutoff = time.time() - days * SECONDS_PER_DAY
    found = []
    for folder in Path(root).iterdir():
        if folder.is_dir() and folder.stat().st_mtime < cutoff:
            found.append(folder)
    return sorted(found)


def prune(root: str | Path, days: int = 30, dry_run: bool = False) -> list[Path]:
    """List old bundles, and delete them unless this is a dry run (the default)."""
    targets = old_bundles(root, days)
    for folder in targets:
        print(f"{'Would remove' if dry_run else 'Removing'} {folder.name}")
        if not dry_run:
            shutil.rmtree(folder)
    return targets
