"""Listing completed result bundles."""

import argparse
import json
from datetime import datetime, timezone

import pytest

from meridian.bundles import list_bundles
from meridian.cli import main, parse_since
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run


def _set_completed(bundle, when):
    path = bundle / "COMPLETE.json"
    manifest = json.loads(path.read_text())
    manifest["completed_utc"] = when.isoformat()
    path.write_text(json.dumps(manifest))


@pytest.fixture
def results(tmp_path, lane, settings):
    result = run_scenario((lane,), settings)
    old = export_run(result, tmp_path)
    new = export_run(result, tmp_path)
    _set_completed(old, datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc))
    _set_completed(new, datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc))
    return tmp_path, old, new


def test_list_newest_first(results):
    root, old, new = results
    rows = list_bundles(root)
    assert [row["bundle"] for row in rows] == [new.name, old.name]


def test_list_skips_incomplete(results):
    root, _, _ = results
    (root / "partial").mkdir()
    (root / "partial" / "summary.json").write_text("{}")
    assert len(list_bundles(root)) == 2


def test_missing_folder(tmp_path):
    with pytest.raises(InputError, match="not found"):
        list_bundles(tmp_path / "absent")


def test_parse_since():
    assert parse_since("3/11/2026") == "03/11/2026"
    with pytest.raises(argparse.ArgumentTypeError):
        parse_since("2026-11-03")


def test_list_command(results, capsys):
    root, old, new = results
    assert main(["list", "--output", str(root)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [f"03/11/2026  {new.name}", f"02/11/2026  {old.name}"]


def test_list_since_same_month(results, capsys):
    root, _, new = results
    assert main(["list", "--output", str(root), "--since", "3/11/2026"]) == 0
    assert capsys.readouterr().out.splitlines() == [f"03/11/2026  {new.name}"]
