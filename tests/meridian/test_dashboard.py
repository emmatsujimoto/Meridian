"""Static HTML scenario dashboard."""

import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from meridian.cli import main
from meridian.dashboard import (
    baseline_changes,
    buildChart,
    cost_per_kg,
    expected_demand_kg,
    load_bundles,
    render_dashboard,
    scenario_overview,
    scenarioRows,
    write_dashboard,
)
from meridian.inputs import load_settings
from meridian.models import InputError, Settings
from meridian.planning import run_scenario
from meridian.reporting import export_run

ROOT = Path(__file__).resolve().parents[2]
FIXED_TIME = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


class _Collector(HTMLParser):
    """Collects tags and text so tests can check the page's structure."""

    def __init__(self):
        super().__init__()
        self.tags = []
        self.text = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        if data.strip():
            self.text.append(data.strip())


def _parse(page):
    collector = _Collector()
    collector.feed(page)
    return collector


@pytest.fixture
def results(tmp_path, lane, settings):
    other = replace(lane, site_id="Other", daily_mean_kg=20)
    lanes = (lane, other)
    export_run(run_scenario(lanes, settings), tmp_path)
    export_run(
        run_scenario(lanes, replace(settings, scenario_id="high", demand_multiplier=1.5)),
        tmp_path,
    )
    export_run(
        run_scenario(lanes, replace(settings, scenario_id="low", demand_multiplier=0.5)),
        tmp_path,
    )
    return tmp_path


def test_load_from_results_folder(results):
    reports = load_bundles([results])
    assert [r["scenario_id"] for r in reports] == ["low", "baseline", "high"]


def test_load_from_bundle_folder_and_file(results):
    folders = sorted(p.parent for p in results.glob("*/summary.json"))
    reports = load_bundles([folders[0], folders[1] / "summary.json"])
    assert len(reports) == 2


def test_duplicate_bundles_counted_once(results, lane, settings):
    export_run(
        run_scenario((lane, replace(lane, site_id="Other", daily_mean_kg=20)), settings), results
    )
    reports = load_bundles([results])
    assert [r["scenario_id"] for r in reports].count("baseline") == 1


def test_no_bundles(tmp_path):
    with pytest.raises(InputError, match="No completed"):
        load_bundles([tmp_path])


def test_tampered_bundle_rejected(results):
    bundle = next(results.glob("*/summary.json")).parent
    (bundle / "lanes.csv").write_text("changed")
    with pytest.raises(InputError, match="integrity"):
        load_bundles([results])


def test_too_many_bundles(tmp_path, monkeypatch, results):
    import meridian.dashboard as dashboard

    monkeypatch.setattr(dashboard, "MAX_BUNDLES", 2)
    with pytest.raises(InputError, match="at most 2"):
        load_bundles([results])


def test_overview_tiles(results):
    tiles = dict(
        (label, (value, note)) for label, value, note in scenario_overview(load_bundles([results]))
    )
    assert tiles["Scenarios compared"][0] == "3"
    assert tiles["Lowest mean cost"][1] == "low"
    assert tiles["Cost range"][1] == "Highest: high"
    assert "%" in tiles["Fill rate range"][0]


def test_scenario_rows(results):
    rows = scenarioRows(load_bundles([results]))
    assert rows.count("<tr>") == 3
    assert "of 2</td>" in rows
    assert 'data-sort="' in rows


def test_description_shown(tmp_path, lane, settings):
    described = replace(settings, description="Winter peak with longer deliveries")
    export_run(run_scenario((lane,), described), tmp_path)
    rows = scenarioRows(load_bundles([tmp_path]))
    assert "Winter peak with longer deliveries" in rows


def test_chart_bars_and_totals():
    svg = buildChart(["a", "b"], [("Holding", [10.0, 30.0]), ("Backlog", [5.0, 0.0])], "USD")
    assert svg.startswith("<svg")
    assert svg.count("<rect") == 3
    assert ">15<" in svg and ">30<" in svg
    assert 'class="legend"' in svg


def test_chart_single_series_has_no_legend():
    assert 'class="legend"' not in buildChart(["a"], [("Fill", [97.0])], "%")


def test_chart_scales_to_longest_bar():
    svg = buildChart(["a", "b"], [("Cost", [50.0, 100.0])], "USD")
    widths = [float(w) for w in re.findall(r'width="([0-9.]+)" height', svg)]
    assert widths[1] == pytest.approx(2 * widths[0])


def test_render_page_structure(results):
    page = render_dashboard(load_bundles([results]), generated=FIXED_TIME)
    parsed = _parse(page)
    assert page.startswith("<!doctype html>")
    assert sum(1 for tag, _ in parsed.tags if tag == "table") == 4 + 3
    assert sum(1 for tag, _ in parsed.tags if tag == "svg") == 2
    assert "2026-11-01 12:00 UTC" in page
    assert "$" not in re.sub(r"\$[0-9,]+", "", page.split("<script>")[0])


def test_lane_matrix_lists_every_lane(results):
    page = render_dashboard(load_bundles([results]), generated=FIXED_TIME)
    matrix = page.split('id="lanes"')[1].split("</section>")[0]
    assert matrix.count("Example:nitrogen") == 1
    assert matrix.count("Other:nitrogen") == 1
    assert matrix.count('class="meets"') + matrix.count('class="below"') == 6


def test_lane_missing_from_a_scenario(tmp_path, lane, settings):
    export_run(run_scenario((lane,), settings), tmp_path)
    export_run(
        run_scenario(
            (lane, replace(lane, site_id="Other")), replace(settings, scenario_id="wider")
        ),
        tmp_path,
    )
    page = render_dashboard(load_bundles([tmp_path]), generated=FIXED_TIME)
    assert 'data-sort="-1">–</td>' in page


def test_same_scenario_name_kept_apart(tmp_path, lane, settings):
    export_run(run_scenario((lane,), settings), tmp_path)
    export_run(run_scenario((lane,), replace(settings, seed=999)), tmp_path)
    reports = load_bundles([tmp_path])
    assert len(reports) == 2
    page = render_dashboard(reports, generated=FIXED_TIME)
    matrix = page.split('id="lanes"')[1].split("</section>")[0]
    values = re.findall(r'data-sort="([0-9.]+)">', matrix)
    expected = sorted(str(r["lanes"][0]["validation_mean_fill_rate"]) for r in reports)
    assert sorted(values) == expected


def test_render_requires_reports():
    with pytest.raises(InputError):
        render_dashboard([])


def test_write_dashboard(results, tmp_path):
    path = write_dashboard([results], tmp_path / "out" / "dashboard.html")
    assert path.is_file()
    assert "Meridian scenario dashboard" in path.read_text(encoding="utf-8")


def test_write_requires_html_suffix(results, tmp_path):
    with pytest.raises(InputError, match=".html"):
        write_dashboard([results], tmp_path / "dashboard.txt")


def test_dashboard_command(results, tmp_path, capsys):
    target = tmp_path / "cli.html"
    assert main(["dashboard", str(results), "--output", str(target)]) == 0
    assert "Dashboard saved" in capsys.readouterr().out
    assert target.is_file()


def test_description_setting():
    assert Settings(description="  Peak season  ").description == "Peak season"
    assert Settings().description == ""


@pytest.mark.parametrize("value", ["x" * 201, 5, None])
def test_invalid_description(value):
    with pytest.raises(InputError, match="description"):
        Settings(description=value)


def test_description_loads_from_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"scenario_id": "peak", "description": "Peak season"}))
    assert load_settings(path).description == "Peak season"


def test_differing_settings_listed(results):
    page = render_dashboard(load_bundles([results]), generated=FIXED_TIME)
    section = page.split('id="settings"')[1].split("</section>")[0]
    assert "<td>demand_multiplier</td>" in section
    assert "<td>0.5</td>" in section and "<td>1.5</td>" in section
    assert "<td>horizon_days</td>" not in section


def test_same_settings_message(tmp_path, lane, settings):
    export_run(run_scenario((lane,), settings), tmp_path)
    page = render_dashboard(load_bundles([tmp_path]), generated=FIXED_TIME)
    assert "All scenarios use the same settings." in page


def test_lane_cost_matrix(results):
    reports = load_bundles([results])
    page = render_dashboard(reports, generated=FIXED_TIME)
    section = page.split('id="lane-cost"')[1].split("</section>")[0]
    for report in reports:
        for row in report["lanes"]:
            assert f'data-sort="{row["validation_mean_cost"]}"' in section


def test_detail_blocks(results):
    page = render_dashboard(load_bundles([results]), generated=FIXED_TIME)
    section = page.split('id="detail"')[1].split("</section>")[0]
    assert section.count("<details>") == 3
    assert "<summary>low:" in section


def test_csv_download(results):
    import base64
    import csv
    import io

    reports = load_bundles([results])
    page = render_dashboard(reports, generated=FIXED_TIME)
    data = re.search(r'href="data:text/csv;base64,([A-Za-z0-9+/=]+)"', page).group(1)
    rows = list(csv.DictReader(io.StringIO(base64.b64decode(data).decode("utf-8"))))
    assert [row["scenario_id"] for row in rows] == [r["scenario_id"] for r in reports]
    first = rows[0]
    parts = sum(float(first[name]) for name in ("Holding", "Backlog", "Delivery", "Purchase"))
    assert parts == pytest.approx(float(first["total_mean_cost"]), abs=0.05)


def test_format_setting_values():
    from meridian.dashboard import _format_setting

    assert _format_setting(None) == "–"
    assert _format_setting([0.75, 1.0]) == "0.75, 1"
    assert _format_setting(0.95) == "0.95"
    assert _format_setting(60) == "60"


def test_expected_demand_and_unit_cost(tmp_path, lane, settings):
    export_run(run_scenario((lane,), settings), tmp_path)
    (report,) = load_bundles([tmp_path])
    demand = lane.daily_mean_kg * settings.horizon_days
    assert expected_demand_kg(report) == pytest.approx(demand)
    assert cost_per_kg(report) == pytest.approx(report["total_mean_cost"] / demand)


def test_unit_cost_scales_with_multiplier(results):
    reports = {r["scenario_id"]: r for r in load_bundles([results])}
    assert expected_demand_kg(reports["high"]) == pytest.approx(
        3 * expected_demand_kg(reports["low"])
    )


def test_unit_cost_without_inputs():
    report = {"total_mean_cost": 10.0, "horizon_days": 5, "inputs": {}}
    assert cost_per_kg(report) is None


def test_unit_cost_tile(results):
    labels = [label for label, _, _ in scenario_overview(load_bundles([results]))]
    assert "Lowest cost per kg" in labels


def test_baseline_changes(results):
    reports = load_bundles([results])
    changes = baseline_changes(reports, "baseline")
    base_index = [r["scenario_id"] for r in reports].index("baseline")
    assert changes[base_index] == (0.0, 0.0)
    low_index = [r["scenario_id"] for r in reports].index("low")
    assert changes[low_index][0] == pytest.approx(
        reports[low_index]["total_mean_cost"] - reports[base_index]["total_mean_cost"]
    )


def test_unknown_baseline(results):
    with pytest.raises(InputError, match="Baseline scenario 'missing'"):
        baseline_changes(load_bundles([results]), "missing")


def test_baseline_columns_rendered(results):
    page = render_dashboard(load_bundles([results]), generated=FIXED_TIME, baseline="baseline")
    assert "Cost vs baseline" in page and "Fill rate vs baseline" in page
    assert "+0.0 pts" in page
    assert "Changes are against baseline." in page


def test_scenario_table_columns_line_up(results):
    page = render_dashboard(load_bundles([results]), generated=FIXED_TIME, baseline="low")
    table = page.split('id="scenarios"')[1].split("</table>")[0]
    headers = table.count("<th ")
    for row in table.split("<tbody>")[1].split("</tr>")[:-1]:
        assert row.count("<td") == headers


def test_dashboard_command_with_baseline(results, tmp_path):
    target = tmp_path / "base.html"
    assert main(["dashboard", str(results), "--output", str(target), "--baseline", "low"]) == 0
    assert "Cost vs baseline" in target.read_text(encoding="utf-8")


class _Balance(HTMLParser):
    """Tracks open elements to confirm the generated page is well nested."""

    VOID = {"meta", "br", "img", "input", "link", "hr", "rect", "line"}

    def __init__(self):
        super().__init__()
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(tag)
        else:
            self.stack.pop()


def test_page_is_well_nested(results):
    parser = _Balance()
    parser.feed(render_dashboard(load_bundles([results]), generated=FIXED_TIME, baseline="low"))
    assert parser.errors == []
    assert parser.stack == []
