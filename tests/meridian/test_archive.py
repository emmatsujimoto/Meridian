"""Selecting and pruning old result bundles."""

import os
import time

from meridian.archive import old_bundles, prune


def _bundle(root, name, age_days):
    folder = root / name
    folder.mkdir()
    (folder / "summary.json").write_text("{}")
    stamp = time.time() - age_days * 86400
    os.utime(folder, (stamp, stamp))
    return folder


def test_only_old_bundles_selected(tmp_path):
    old = _bundle(tmp_path, "old-1", 40)
    _bundle(tmp_path, "new-1", 0)
    assert old_bundles(tmp_path, 30) == [old]


def test_dry_run_keeps_files(tmp_path):
    old = _bundle(tmp_path, "old-1", 40)
    assert prune(tmp_path, 30, dry_run=True) == [old]
    assert old.exists()
