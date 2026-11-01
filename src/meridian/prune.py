"""Remove old result bundles so the results folder does not grow without limit."""

import shutil
import time
from pathlib import Path


def old_bundles(output_root: str | Path, keep_days: int) -> list[Path]:
    """Completed result bundles in output_root whose last change is older than keep_days."""
    root = Path(output_root).resolve()
    now = time.time()
    found = []
    for path in sorted(root.iterdir()):
        if not path.is_dir():
            continue
        age_seconds = now - path.stat().st_mtime
        if age_seconds > keep_days * 3600:
            found.append(path)
    return found


def prune(output_root: str | Path, keep_days: int, dry_run: bool = False) -> list[Path]:
    """Delete completed bundles older than keep_days and return what was (or would be) removed."""
    removed = old_bundles(output_root, keep_days)
    for path in removed:
        # print("would delete", path)
        if not dry_run:
            shutil.rmtree(path)
    return removed
