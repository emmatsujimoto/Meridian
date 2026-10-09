"""Boundary checks for input files, traceability, and command execution."""

import csv
import json
import subprocess
import sys
from dataclasses import asdict

import pytest

from meridian.bundles import verify_bundle
from meridian.inputs import load_lanes
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run


def test_module_entry_point():
    result = subprocess.run(
        [sys.executable, "-m", "meridian", "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0
    assert "validate" in result.stdout
    assert "benchmark" in result.stdout


def test_row_limit(tmp_path, lane):
    path = tmp_path / "too-many.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(asdict(lane)))
        writer.writeheader()
        for index in range(101):
            writer.writerow({**asdict(lane), "site_id": f"Site{index}"})
    with pytest.raises(InputError, match="At most 100"):
        load_lanes(path)


def test_nonnumeric_csv_has_row_number(tmp_path, lane):
    path = tmp_path / "bad.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(asdict(lane)))
        writer.writeheader()
        writer.writerow({**asdict(lane), "daily_mean_kg": "unknown"})
    with pytest.raises(InputError, match="CSV row 2: daily_mean_kg"):
        load_lanes(path)


@pytest.fixture
def bundle(tmp_path, lane, settings):
    return export_run(run_scenario((lane,), settings), tmp_path)


def test_missing_export_file_rejected(bundle):
    # Remove only this test's generated file, inside pytest's disposable directory.
    (bundle / "lanes.csv").unlink()
    with pytest.raises(InputError, match="Missing or unreadable"):
        verify_bundle(bundle / "summary.json")


def test_fingerprint_mismatch_rejected(bundle):
    manifest_path = bundle / "COMPLETE.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["input_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(InputError, match="fingerprints disagree"):
        verify_bundle(bundle / "summary.json")


@pytest.mark.parametrize("content", ["[]", "not-json", '{"files":{}}'])
def test_invalid_completion_manifest(bundle, content):
    (bundle / "COMPLETE.json").write_text(content)
    with pytest.raises(InputError):
        verify_bundle(bundle / "summary.json")


def test_invalid_manifest_digest(bundle):
    path = bundle / "COMPLETE.json"
    manifest = json.loads(path.read_text())
    manifest["files"]["summary.json"] = "invalid"
    path.write_text(json.dumps(manifest))
    with pytest.raises(InputError, match="SHA-256"):
        verify_bundle(bundle / "summary.json")


def test_unexpected_report_filename(bundle):
    with pytest.raises(InputError, match="summary.json"):
        verify_bundle(bundle / "lanes.csv")


def test_rng_restored_after_simulation_failure(lane, monkeypatch):
    import numpy as np

    import meridian.engine as engine

    before = np.random.get_state()

    def fail(*args, **kwargs):
        np.random.seed(999)
        raise RuntimeError("Controlled test exception")

    monkeypatch.setattr(engine, "simulation", fail)
    with pytest.raises(RuntimeError, match="Controlled test exception"):
        engine.simulate_lane(lane, 20, (10,))
    after = np.random.get_state()
    assert before[0] == after[0]
    assert np.array_equal(before[1], after[1])
    assert before[2:] == after[2:]


def test_interrupted_export_has_no_completion_marker(tmp_path, lane, settings, monkeypatch):
    import meridian.reporting as reporting

    result = run_scenario((lane,), settings)

    def fail(*args, **kwargs):
        raise OSError("Controlled test disk failure")

    monkeypatch.setattr(reporting, "_write_csv", fail)
    with pytest.raises(OSError, match="Controlled test disk failure"):
        reporting.export_run(result, tmp_path)
    folders = list(tmp_path.iterdir())
    assert len(folders) == 1
    assert (folders[0] / "summary.json").is_file()
    assert not (folders[0] / "COMPLETE.json").exists()
    assert not (folders[0] / "lanes.csv").exists()
    assert folders[0].name.startswith(settings.scenario_id)
    with pytest.raises(InputError, match="COMPLETE"):
        verify_bundle(folders[0] / "summary.json")
