"""One run at a time per results folder."""

import os
from pathlib import Path

LOCK_NAME = ".meridian-run.lock"


def acquire_lock(output_root: str | Path) -> Path:
    """Create the results folder's lock file, or stop if another run holds it."""
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / LOCK_NAME
    if lock.exists():
        raise RuntimeError(
            f"Another run is writing to {root}. Wait for it to finish, "
            f"or delete {LOCK_NAME} if no run is active."
        )
    lock.write_text(str(os.getpid()), encoding="utf-8")
    return lock


def release_lock(lock: Path) -> None:
    lock.unlink(missing_ok=True)
