"""Lead-time demand columns in summaries, lanes.csv and report.md."""

import csv
from dataclasses import replace
from math import sqrt

import pytest

from meridian.planning import run_scenario
from meridian.reporting import export_run, lead_time_demand, summary


def test_lead_time_demand_formula(lane):
    slow = replace(lane, lead_time_days=4)
    mean_kg, sd_kg = lead_time_demand(slow, 1.0)
    assert mean_kg == pytest.approx(slow.daily_mean_kg * 4)
    assert sd_kg == pytest.approx(slow.daily_sd_kg * 2)


def test_demand_multiplier_scales_both(lane):
    base = lead_time_demand(lane, 1.0)
    scaled = lead_time_demand(lane, 1.5)
    assert scaled[0] == pytest.approx(base[0] * 1.5)
    assert scaled[1] == pytest.approx(base[1] * 1.5)


def test_zero_lead_time(lane):
    assert lead_time_demand(replace(lane, lead_time_days=0), 1.0) == (0.0, 0.0)


def test_summary_columns(lane, settings):
    other = replace(lane, site_id="Other", lead_time_days=3, daily_mean_kg=20, daily_sd_kg=5)
    report = summary(run_scenario((lane, other), replace(settings, demand_multiplier=2.0)))
    rows = {row["lane"]: row for row in report["lanes"]}
    assert rows[lane.key]["lead_time_demand_kg"] == pytest.approx(10 * 2.0 * 1)
    assert rows[other.key]["lead_time_demand_kg"] == pytest.approx(20 * 2.0 * 3)
    assert rows[other.key]["lead_time_demand_sd_kg"] == pytest.approx(5 * 2.0 * sqrt(3))


def test_columns_follow_base_stock(lane, settings):
    row = summary(run_scenario((lane,), settings))["lanes"][0]
    keys = list(row)
    assert keys.index("lead_time_demand_kg") == keys.index("base_stock_kg") + 1
    assert keys.index("lead_time_demand_sd_kg") == keys.index("base_stock_kg") + 2


def test_existing_fields_unchanged(lane, settings):
    report = summary(run_scenario((lane,), settings))
    row = report["lanes"][0]
    assert report["total_mean_cost"] == pytest.approx(row["validation_mean_cost"])
    assert {"base_stock_kg", "validation_mean_cost", "validation_mean_fill_rate"} <= set(row)


def test_lanes_csv(tmp_path, lane, settings):
    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    with (bundle / "lanes.csv").open(newline="") as stream:
        (row,) = list(csv.DictReader(stream))
    assert float(row["lead_time_demand_kg"]) == pytest.approx(lane.daily_mean_kg)
    assert float(row["lead_time_demand_sd_kg"]) == pytest.approx(lane.daily_sd_kg)


def test_report_column(tmp_path, lane, settings):
    bundle = export_run(run_scenario((replace(lane, lead_time_days=5),), settings), tmp_path)
    lines = (bundle / "report.md").read_text().splitlines()
    header = next(line for line in lines if line.startswith("| Product-location"))
    row = next(line for line in lines if line.startswith(f"| {lane.key}"))
    assert "Lead-time demand (kg)" in header
    columns = [cell.strip() for cell in row.strip("|").split("|")]
    assert columns[2] == "50"
    assert header.count("|") == row.count("|")


def test_bundle_still_verifies_and_compares(tmp_path, lane, settings):
    from meridian.reporting import compare_reports

    a = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    b = export_run(run_scenario((lane,), replace(settings, scenario_id="b")), tmp_path)
    assert len(compare_reports([a, b / "summary.json"])) == 2


def test_cover_days(lane, settings):
    row = summary(run_scenario((lane,), replace(settings, demand_multiplier=2.0)))["lanes"][0]
    assert row["base_stock_cover_days"] == pytest.approx(
        row["base_stock_kg"] / (lane.daily_mean_kg * 2)
    )


def test_zero_lead_time_lane_in_report(tmp_path, lane, settings):
    instant = replace(lane, lead_time_days=0)
    bundle = export_run(run_scenario((instant,), settings), tmp_path)
    row = next(
        line
        for line in (bundle / "report.md").read_text().splitlines()
        if line.startswith(f"| {lane.key}")
    )
    assert [cell.strip() for cell in row.strip("|").split("|")][2] == "0"


def test_cover_days_in_lanes_csv(tmp_path, lane, settings):
    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    with (bundle / "lanes.csv").open(newline="") as stream:
        (row,) = list(csv.DictReader(stream))
    expected = float(row["base_stock_kg"]) / lane.daily_mean_kg
    assert float(row["base_stock_cover_days"]) == pytest.approx(expected)
