"""Days of cover versus lead time in report.md."""

from dataclasses import replace

import pytest

from meridian.inputs import load_lanes, load_settings
from meridian.planning import run_scenario
from meridian.reporting import export_run, lead_time_rows, lead_time_section


@pytest.fixture
def example():
    lanes = load_lanes("data/synthetic_sites.csv")
    settings = replace(load_settings("config/quickstart.json"), horizon_days=7)
    return run_scenario(lanes, settings)


def test_one_row_per_lane(example):
    rows = lead_time_rows(example)
    assert [row["lane"] for row in rows] == [r.lane_key for r in example.results]


def test_cover_days(example):
    lanes = {lane.key: lane for lane in example.lanes}
    for row, lane_result in zip(lead_time_rows(example), example.results, strict=True):
        lane = lanes[row["lane"]]
        expected = lane_result.chosen_base_stock_kg / lane.daily_mean_kg
        assert row["cover_days"] == pytest.approx(expected)
        assert row["lead_time_days"] == lane.lead_time_days
        assert row["cover_ratio"] == pytest.approx(expected / lane.lead_time_days)


def test_demand_multiplier_reduces_cover(lane, settings):
    base = lead_time_rows(run_scenario((lane,), settings))[0]
    busy_settings = replace(settings, demand_multiplier=2.0)
    busy = lead_time_rows(run_scenario((lane,), busy_settings))[0]
    chosen = run_scenario((lane,), busy_settings).results[0].chosen_base_stock_kg
    assert busy["cover_days"] == pytest.approx(chosen / (lane.daily_mean_kg * 2))
    assert base["cover_days"] > 0


@pytest.mark.parametrize(("multiplier", "status"), [(0.2, "below lead time"), (5.0, "comfortable")])
def test_status_labels(lane, settings, multiplier, status):
    slow = replace(lane, lead_time_days=4, daily_sd_kg=0)
    grid = replace(settings, stock_multipliers=(multiplier,))
    assert lead_time_rows(run_scenario((slow,), grid))[0]["status"] == status


def test_statuses_known(example):
    known = {"comfortable", "tight", "tight; target missed in training", "below lead time"}
    assert {row["status"] for row in lead_time_rows(example)} <= known


def test_section_lines(example):
    lines = lead_time_section(example)
    assert lines[0] == "## Days of cover versus lead time"
    assert lines[2].startswith("| Product-location | Days of cover")
    assert len(lines) == 4 + len(example.results)


def test_report_md_contains_section(tmp_path, lane, settings):
    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    text = (bundle / "report.md").read_text(encoding="utf-8")
    assert "## Days of cover versus lead time" in text
    assert "| Example:nitrogen |" in text.split("## Days of cover")[1]


def test_section_before_model_notes(tmp_path, lane, settings):
    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    text = (bundle / "report.md").read_text(encoding="utf-8")
    assert text.index("## Days of cover") < text.index("- Independent product-location")
