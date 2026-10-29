"""Export isolation, reproducibility evidence, and command-line integration."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from meridian.cli import main
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import compare_reports, export_run, summary

ROOT = Path(__file__).resolve().parents[2]


def test_cost_components_reconcile(lane, settings):
    report = summary(run_scenario((lane,), settings))
    row = report["lanes"][0]
    parts = sum(
        row[key]
        for key in (
            "mean_holding_cost",
            "mean_backlog_cost",
            "mean_delivery_cost",
            "mean_purchase_cost",
        )
    )
    assert row["validation_mean_cost"] == pytest.approx(parts)
    assert report["total_mean_cost"] == pytest.approx(parts)


def test_export_unique_and_complete(tmp_path, lane, settings):
    result = run_scenario((lane,), settings)
    first = export_run(result, tmp_path)
    second = export_run(result, tmp_path)
    assert first != second
    assert (first / "summary.json").read_bytes() == (second / "summary.json").read_bytes()
    manifest = json.loads((first / "COMPLETE.json").read_text())
    for filename, digest in manifest["files"].items():
        assert hashlib.sha256((first / filename).read_bytes()).hexdigest() == digest
    assert {"lanes.csv", "candidates.csv", "daily_results.csv", "report.md"} <= set(
        manifest["files"]
    )


def test_fingerprint_changes_with_inputs(lane, settings):
    a = summary(run_scenario((lane,), settings))
    b = summary(run_scenario((lane,), replace(settings, seed=255)))
    assert a["input_sha256"] != b["input_sha256"]


def test_compare_matching_reports(tmp_path, lane, settings):
    a = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    b = (
        export_run(run_scenario((lane,), replace(settings, scenario_id="alternate")), tmp_path)
        / "summary.json"
    )
    assert len(compare_reports([a, b])) == 2


def test_compare_different_horizons_rejected(tmp_path, lane, settings):
    a = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    b = (
        export_run(run_scenario((lane,), replace(settings, horizon_days=3)), tmp_path)
        / "summary.json"
    )
    with pytest.raises(InputError, match="matching horizons"):
        compare_reports([a, b])


def test_invalid_report(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{}")
    with pytest.raises(InputError):
        compare_reports([path, path])
    with pytest.raises(InputError):
        compare_reports([])


def test_cli_missing_file_returns_error(capsys):
    assert main(["validate", "--data", "missing.csv", "--config", "missing.json"]) == 2
    assert "Input/output error" in capsys.readouterr().err


def test_cli_validate_example(capsys):
    assert (
        main(
            [
                "validate",
                "--data",
                str(ROOT / "data/synthetic_sites.csv"),
                "--config",
                str(ROOT / "config/quickstart.json"),
            ]
        )
        == 0
    )
    assert "6 product-location rows" in capsys.readouterr().out


def test_cli_run_example(tmp_path, capsys):
    assert (
        main(
            [
                "run",
                "--data",
                str(ROOT / "data/synthetic_sites.csv"),
                "--config",
                str(ROOT / "config/quickstart.json"),
                "--output",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert "Results saved" in capsys.readouterr().out
    assert len(list(tmp_path.glob("*/COMPLETE.json"))) == 1


def test_version_flag_prints_package_version(capsys):
    from meridian import __version__

    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out
