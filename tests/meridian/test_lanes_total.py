"""The TOTAL row at the end of lanes.csv."""

import csv
import json
from dataclasses import replace

import pytest

from meridian.planning import run_scenario
from meridian.reporting import ADDITIVE_FIELDS, export_run, read_lanes_csv, summary, total_row


@pytest.fixture
def two_lanes(lane):
    return (lane, replace(lane, site_id="North", daily_mean_kg=14, daily_sd_kg=3))


@pytest.fixture
def bundle(tmp_path, two_lanes, settings):
    return export_run(run_scenario(two_lanes, settings), tmp_path)


def _rows(bundle):
    with (bundle / "lanes.csv").open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_total_row_is_last(bundle):
    rows = _rows(bundle)
    assert len(rows) == 3
    assert rows[-1]["lane"] == "TOTAL"
    assert [row["lane"] for row in rows[:-1]] == ["Example:nitrogen", "North:nitrogen"]


def test_total_adds_up_additive_columns(bundle):
    rows = _rows(bundle)
    for field in ADDITIVE_FIELDS:
        expected = sum(float(row[field]) for row in rows[:-1])
        assert float(rows[-1][field]) == pytest.approx(expected)


def test_total_cost_matches_summary(two_lanes, settings):
    report = summary(run_scenario(two_lanes, settings))
    assert total_row(report)["validation_mean_cost"] == pytest.approx(report["total_mean_cost"])


def test_total_fill_rate_is_portfolio_rate(two_lanes, settings):
    report = summary(run_scenario(two_lanes, settings))
    row = total_row(report)
    assert row["validation_mean_fill_rate"] == report["portfolio_fill_rate"]
    assert row["validation_target_met"] == (
        report["portfolio_fill_rate"] >= settings.service_target
    )


def test_total_leaves_standard_deviation_empty(bundle):
    assert _rows(bundle)[-1]["validation_cost_sd"] == ""


def test_total_training_flag(two_lanes, settings):
    report = summary(run_scenario(two_lanes, settings))
    assert total_row(report)["training_target_met"] == all(
        row["training_target_met"] for row in report["lanes"]
    )


def test_total_row_has_same_columns(bundle):
    rows = _rows(bundle)
    assert list(rows[-1]) == list(rows[0])


def test_per_lane_rows_unchanged(two_lanes, settings, bundle):
    report = summary(run_scenario(two_lanes, settings))
    rows = _rows(bundle)[:-1]
    for written, expected in zip(rows, report["lanes"], strict=True):
        assert written["lane"] == expected["lane"]
        assert float(written["validation_mean_cost"]) == pytest.approx(
            expected["validation_mean_cost"]
        )


def test_read_lanes_csv_skips_total(bundle):
    rows = read_lanes_csv(bundle / "lanes.csv")
    assert [row["lane"] for row in rows] == ["Example:nitrogen", "North:nitrogen"]


def test_summary_json_has_no_total(bundle):
    report = json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
    assert all(row["lane"] != "TOTAL" for row in report["lanes"])


def test_report_md_has_total_line(bundle):
    text = (bundle / "report.md").read_text(encoding="utf-8")
    assert "| TOTAL |" in text


def test_single_lane_total_matches_lane(tmp_path, lane, settings):
    rows = _rows(export_run(run_scenario((lane,), settings), tmp_path))
    assert len(rows) == 2
    for field in ADDITIVE_FIELDS:
        assert float(rows[1][field]) == pytest.approx(float(rows[0][field]))


def test_bundle_still_verifies(bundle):
    from meridian.bundles import verify_bundle

    assert verify_bundle(bundle / "summary.json")["lanes"]
