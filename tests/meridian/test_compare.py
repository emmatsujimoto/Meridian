"""Edge cases for comparing completed result bundles."""

from dataclasses import replace

import pytest

from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import compare_reports, export_run


def _export(tmp_path, lanes, settings):
    return export_run(run_scenario(lanes, settings), tmp_path) / "summary.json"


def test_single_report_rejected(tmp_path, lane, settings):
    with pytest.raises(InputError, match="at least two"):
        compare_reports([_export(tmp_path, (lane,), settings)])


def test_different_lane_portfolios_rejected(tmp_path, lane, settings):
    other = replace(lane, site_id="Other")
    a = _export(tmp_path, (lane,), settings)
    b = _export(tmp_path, (lane, other), replace(settings, scenario_id="wider"))
    with pytest.raises(InputError, match="lane portfolios"):
        compare_reports([a, b])


def test_reports_sorted_by_cost(tmp_path, lane, settings):
    low = _export(tmp_path, (lane,), replace(settings, scenario_id="low", demand_multiplier=0.5))
    high = _export(tmp_path, (lane,), replace(settings, scenario_id="high", demand_multiplier=2))
    rows = compare_reports([high, low])
    assert [row["scenario_id"] for row in rows] == ["low", "high"]
    assert rows[0]["total_mean_cost"] <= rows[1]["total_mean_cost"]


def test_tampered_bundle_rejected(tmp_path, lane, settings):
    a = _export(tmp_path, (lane,), settings)
    b = _export(tmp_path, (lane,), replace(settings, scenario_id="alternate"))
    (b.parent / "lanes.csv").write_text("changed")
    with pytest.raises(InputError, match="integrity check"):
        compare_reports([a, b])
