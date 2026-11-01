"""Pruning old result bundles."""

import os
import time

from meridian.prune import prune


def _bundle(root, name, age_days):
    path = root / name
    path.mkdir()
    (path / "COMPLETE.json").write_text("{}")
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_prune_removes_old_bundles(tmp_path):
    old = _bundle(tmp_path, "baseline-old", 90)
    assert prune(tmp_path, keep_days=30) == [old]
    assert not old.exists()


def test_dry_run_keeps_files(tmp_path):
    old = _bundle(tmp_path, "baseline-old", 90)
    assert prune(tmp_path, keep_days=30, dry_run=True) == [old]
    assert old.exists()
