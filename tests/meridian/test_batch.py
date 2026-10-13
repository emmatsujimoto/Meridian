"""Scenario batch discovery, validation and indexing."""

import json
from pathlib import Path

import pytest

from meridian.batch import (
    build_index,
    bundle_from_output,
    discover_configs,
    preflight,
    write_index,
)
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run

ROOT = Path(__file__).resolve().parents[2]


def test_discover_sorted(tmp_path):
    for name in ("b.json", "a.json", "notes.txt"):
        (tmp_path / name).write_text("{}")
    assert [p.name for p in discover_configs(tmp_path)] == ["a.json", "b.json"]


def test_discover_empty_folder(tmp_path):
    with pytest.raises(InputError, match="No scenario"):
        discover_configs(tmp_path)


def test_preflight_rejects_duplicate_ids(tmp_path):
    settings = json.loads((ROOT / "config/quickstart.json").read_text())
    for name in ("one.json", "two.json"):
        (tmp_path / name).write_text(json.dumps(settings))
    with pytest.raises(InputError, match="reuses scenario_id"):
        preflight(ROOT / "data/synthetic_sites.csv", discover_configs(tmp_path))


def test_repository_scenarios_pass_preflight():
    preflight(ROOT / "data/synthetic_sites.csv", discover_configs(ROOT / "config/scenarios"))


def test_bundle_from_output():
    assert bundle_from_output("noise\nResults saved to /tmp/x-1\n") == Path("/tmp/x-1")
    assert bundle_from_output("Input/output error: bad") is None


def test_index_written(tmp_path, lane, settings):
    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    rows = build_index([(Path("a.json"), bundle)])
    path = write_index(rows, tmp_path)
    assert path.read_text().count("\n") == 2
    assert (tmp_path / "batch_report.md").read_text().startswith("# Scenario batch")
