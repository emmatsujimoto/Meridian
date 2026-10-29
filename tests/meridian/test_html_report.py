"""HTML scenario comparison pages."""

from dataclasses import replace

import pytest

from meridian.html_report import (
    lane_matrix,
    load_summaries,
    render,
    scenario_rows,
    write_comparison,
)
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run


@pytest.fixture
def two_bundles(tmp_path, lane, settings):
    first = export_run(run_scenario((lane,), settings), tmp_path)
    higher = replace(settings, scenario_id="higher", demand_multiplier=1.25)
    second = export_run(run_scenario((lane,), higher), tmp_path)
    return [first / "summary.json", second / "summary.json"]


def test_needs_two_reports(two_bundles):
    with pytest.raises(InputError):
        load_summaries(two_bundles[:1])


def test_rows_follow_input_order(two_bundles):
    rows = scenario_rows(load_summaries(two_bundles))
    assert [row["scenario"] for row in rows] == ["baseline", "higher"]
    assert rows[0]["change_pct"] == 0


def test_lane_matrix_has_each_scenario(two_bundles, lane):
    lanes, matrix = lane_matrix(load_summaries(two_bundles))
    assert lanes == [lane.key]
    assert set(matrix[lane.key]) == {"baseline", "higher"}


def test_page_lists_scenarios(two_bundles):
    page = render(load_summaries(two_bundles), "Demand study")
    assert page.startswith("<!doctype html>")
    assert "<h1>Demand study</h1>" in page
    assert page.count('class="best"') == 1


def test_written_file(tmp_path, two_bundles):
    path = write_comparison(two_bundles, tmp_path / "out" / "compare.html", "Study")
    assert path.read_text(encoding="utf-8").count("<tr") >= 3
