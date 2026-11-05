"""Listing completed bundles with --limit."""

import argparse
import json
from datetime import datetime, timedelta, timezone

import pytest

from meridian.bundles import list_bundles
from meridian.cli import main, positive_int
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run

START = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)


def _set_completed(bundle, value):
    path = bundle / "COMPLETE.json"
    manifest = json.loads(path.read_text())
    manifest["completed_utc"] = value
    path.write_text(json.dumps(manifest))


@pytest.fixture
def results(tmp_path, lane, settings):
    result = run_scenario((lane,), settings)
    bundles = []
    for offset in range(3):
        bundle = export_run(result, tmp_path)
        _set_completed(bundle, (START + timedelta(days=offset)).isoformat())
        bundles.append(bundle)
    return tmp_path, bundles


def test_most_recent_first(results):
    root, bundles = results
    names = [entry["bundle"] for entry in list_bundles(root)]
    assert names == [b.name for b in reversed(bundles)]


def test_limit(results):
    root, bundles = results
    assert [entry["bundle"] for entry in list_bundles(root, limit=2)] == [
        bundles[2].name,
        bundles[1].name,
    ]


def test_limit_larger_than_count(results):
    root, _ = results
    assert len(list_bundles(root, limit=10)) == 3


def test_limit_must_be_positive(results):
    with pytest.raises(InputError, match="at least 1"):
        list_bundles(results[0], limit=0)


def test_entries_carry_scenario_and_time(results, settings):
    entry = list_bundles(results[0], limit=1)[0]
    assert entry["scenario_id"] == settings.scenario_id
    assert entry["completed_utc"] == START + timedelta(days=2)


def test_skips_unreadable_and_naive_times(results):
    root, bundles = results
    _set_completed(bundles[0], "2026-11-05T09:00:00")
    (bundles[1] / "COMPLETE.json").write_text("{broken")
    assert [entry["bundle"] for entry in list_bundles(root)] == [bundles[2].name]


def test_times_in_other_zones_normalised(results):
    root, bundles = results
    _set_completed(bundles[0], "2026-11-10T01:00:00-05:00")
    entry = list_bundles(root, limit=1)[0]
    assert entry["bundle"] == bundles[0].name
    assert entry["completed_utc"] == datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)


def test_missing_folder(tmp_path):
    with pytest.raises(InputError, match="not found"):
        list_bundles(tmp_path / "absent")


def test_positive_int():
    assert positive_int("3") == 3
    for text in ("0", "-2", "two"):
        with pytest.raises(argparse.ArgumentTypeError):
            positive_int(text)


def test_list_command_limit(results, capsys):
    root, bundles = results
    assert main(["list", "--output", str(root), "--limit", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [f"2026-11-03 08:00 UTC  {bundles[2].name}  baseline"]


def test_list_command_rejects_zero_limit(results):
    with pytest.raises(SystemExit):
        main(["list", "--output", str(results[0]), "--limit", "0"])
