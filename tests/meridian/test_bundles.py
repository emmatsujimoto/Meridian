"""Checks for corrupted, incomplete and incomparable scenario exports."""

import json
from dataclasses import replace

import numpy as np
import pytest

from meridian.bundles import validate_report, verify_bundle
from meridian.cli import main
from meridian.models import InputError
from meridian.planning import deterministic_plan, run_scenario
from meridian.reporting import export_run, summary
from stockpyl.helpers import irwin_hall_cdf, sum_of_continuous_uniforms_distribution


@pytest.fixture
def result(lane, settings):
    return run_scenario((lane,), settings)


def test_complete_bundle_roundtrip(tmp_path, result):
    folder = export_run(result, tmp_path)
    assert verify_bundle(folder / "summary.json") == json.loads(json.dumps(summary(result)))


def test_modified_output_rejected(tmp_path, result):
    folder = export_run(result, tmp_path)
    (folder / "lanes.csv").write_text("modified\n")
    with pytest.raises(InputError, match="integrity"):
        verify_bundle(folder / "summary.json")


def test_incomplete_bundle_rejected(tmp_path):
    path = tmp_path / "summary.json"
    path.write_text("{}")
    with pytest.raises(InputError, match="COMPLETE"):
        verify_bundle(path)


@pytest.mark.parametrize("filename", ["../outside", "a/b", "a\\b", "..", "."])
def test_manifest_path_escape_rejected(tmp_path, result, filename):
    folder = export_run(result, tmp_path)
    path = folder / "COMPLETE.json"
    manifest = json.loads(path.read_text())
    manifest["files"][filename] = "0" * 64
    path.write_text(json.dumps(manifest))
    with pytest.raises(InputError):
        verify_bundle(folder / "summary.json")


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("scenario_id", "../other"),
        ("horizon_days", -1),
        ("currency", "EUR"),
        ("quantity_unit", "litres"),
        ("input_sha256", "bad"),
        ("total_mean_cost", float("nan")),
        ("portfolio_fill_rate", 1.1),
        ("lanes", []),
        ("lanes", [None]),
    ],
)
def test_invalid_report_fields(result, field, value):
    report = summary(result)
    report[field] = value
    with pytest.raises(InputError):
        validate_report(report)


def test_duplicate_results_rejected(result):
    report = summary(result)
    report["lanes"].append(report["lanes"][0])
    with pytest.raises(InputError, match="Duplicate"):
        validate_report(report)


def test_cost_mismatch_rejected(result):
    report = summary(result)
    report["total_mean_cost"] += 1
    with pytest.raises(InputError, match="reconcile"):
        validate_report(report)


def test_compare_cli(tmp_path, result, capsys):
    a = export_run(result, tmp_path) / "summary.json"
    b = export_run(result, tmp_path) / "summary.json"
    assert main(["compare", str(a), str(b)]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 2


def test_benchmark_cli(tmp_path, lane, capsys):
    import csv
    from dataclasses import asdict

    path = tmp_path / "lanes.csv"
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(asdict(lane)))
        writer.writeheader()
        writer.writerow(asdict(lane))
    config = tmp_path / "config.json"
    config.write_text('{"horizon_days":3}')
    assert main(["benchmark", "--data", str(path), "--config", str(config)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report[0]["eoq"]["quantity_kg"] > 0


def test_uniform_sum_exact_moments_and_vectorization():
    distribution = sum_of_continuous_uniforms_distribution(4, 50, 100)
    assert distribution.mean() == pytest.approx(300)
    assert distribution.var() == pytest.approx(4 * 50**2 / 12)
    assert distribution.cdf([199, 300, 401]) == pytest.approx([0, 0.5, 1])
    assert irwin_hall_cdf(np.array([-1, 2, 5]), 4) == pytest.approx([0, 0.5, 1])


@pytest.mark.parametrize("n,lo,hi", [(0, 0, 1), (1.5, 0, 1), (2, 1, 1), (2, float("nan"), 1)])
def test_uniform_sum_rejects_invalid_parameters(n, lo, hi):
    with pytest.raises(ValueError):
        sum_of_continuous_uniforms_distribution(n, lo, hi)


def test_invalid_deterministic_plan(lane):
    with pytest.raises(InputError):
        deterministic_plan(lane, ())


def test_single_replication_has_zero_cost_sd(lane, settings):
    report = summary(run_scenario((lane,), replace(settings, replications=1)))
    assert report["lanes"][0]["validation_cost_sd"] == 0


def test_signed_bundle_verifies_and_detects_edits(tmp_path, lane, settings):
    import json

    from meridian.bundles import verify_bundle
    from meridian.models import InputError
    from meridian.planning import run_scenario
    from meridian.reporting import export_run

    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    assert verify_bundle(bundle / "summary.json")["scenario_id"] == settings.scenario_id
    manifest = json.loads((bundle / "COMPLETE.json").read_text())
    manifest["completed_utc"] = "2020-01-01T00:00:00+00:00"
    (bundle / "COMPLETE.json").write_text(json.dumps(manifest))
    with pytest.raises(InputError, match="signature does not match"):
        verify_bundle(bundle / "summary.json")
