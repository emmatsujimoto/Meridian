"""Results-folder locking."""

import pytest

from meridian.locking import acquire_lock, release_lock


def test_second_lock_refused(tmp_path):
    lock = acquire_lock(tmp_path)
    with pytest.raises(RuntimeError, match="Another run"):
        acquire_lock(tmp_path)
    release_lock(lock)
    release_lock(acquire_lock(tmp_path))
