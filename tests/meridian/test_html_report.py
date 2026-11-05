"""report.html with confidence intervals."""

from dataclasses import replace
from html.parser import HTMLParser

from meridian.html_report import lane_table_rows, render_html, spread_chart
from meridian.planning import run_scenario
from meridian.reporting import export_run, summary
from meridian.stats import lane_uncertainty


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells = []

    def handle_data(self, data):
        if data.strip():
            self.cells.append(data.strip())


def test_report_html_written(tmp_path, lane, settings):
    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    text = (bundle / "report.html").read_text()
    assert text.startswith("<!doctype html>")
    assert f"Scenario: {settings.scenario_id}" in text


def test_report_html_in_manifest(tmp_path, lane, settings):
    import json

    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    assert "report.html" in json.loads((bundle / "COMPLETE.json").read_text())["files"]


def test_lane_rows_show_intervals(lane, settings):
    result = run_scenario((lane, replace(lane, site_id="Other")), settings)
    report = summary(result)
    rows = lane_table_rows(report, lane_uncertainty(result), settings.service_target)
    assert len(rows) == 2
    parsed = _Text()
    parsed.feed(rows[0])
    assert parsed.cells[0] == lane.key
    assert "–" in parsed.cells[3]
    assert parsed.cells[4].count("/") == 2


def test_uncertain_lane_shaded():
    report = {
        "lanes": [
            {
                "lane": "A:nitrogen",
                "base_stock_kg": 10,
                "validation_mean_cost": 5.0,
                "validation_mean_fill_rate": 0.96,
            }
        ]
    }
    spread = {
        "A:nitrogen": {
            "cost_ci_low": 4.0,
            "cost_ci_high": 6.0,
            "cost_p5": 4.0,
            "cost_p50": 5.0,
            "cost_p95": 6.0,
            "fill_rate_ci_low": 0.93,
            "fill_rate_ci_high": 0.99,
        }
    }
    (row,) = lane_table_rows(report, spread, 0.95)
    assert row.startswith('<tr class="uncertain">')
    spread["A:nitrogen"]["fill_rate_ci_low"] = 0.955
    (row,) = lane_table_rows(report, spread, 0.95)
    assert row.startswith("<tr>")


def test_render_contains_total_interval(lane, settings):
    result = run_scenario((lane,), settings)
    page = render_html(result, summary(result))
    assert "95% confidence interval $" in page
    assert page.count("<tr") == 2
    assert '<svg class="spread"' in page


def test_notes_escaped(lane, settings):
    result = run_scenario((lane,), settings)
    report = summary(result)
    report["model_notes"] = ["Costs < budget & on plan"]
    assert "Costs &lt; budget &amp; on plan" in render_html(result, report)


def test_spread_chart_one_row_per_lane(lane, settings):
    result = run_scenario((lane, replace(lane, site_id="Other", daily_mean_kg=20)), settings)
    report = summary(result)
    svg = spread_chart(report, lane_uncertainty(result))
    assert svg.count("<rect") == 2
    assert svg.count(">Example:nitrogen<") == 1 and svg.count(">Other:nitrogen<") == 1


def test_spread_chart_scale_label(lane, settings):
    result = run_scenario((lane,), settings)
    report = summary(result)
    spread = lane_uncertainty(result)
    svg = spread_chart(report, spread)
    top = max(spread[lane.key]["cost_p95"], spread[lane.key]["cost_ci_high"])
    assert f"${top:,.0f}<" in svg


def test_settings_shown_in_header(lane, settings):
    result = run_scenario((lane,), replace(settings, service_target=0.9))
    page = render_html(result, summary(result))
    assert f"Horizon {settings.horizon_days} days" in page
    assert "service target 90.0%" in page


def test_lane_order_follows_report(lane, settings):
    lanes = (replace(lane, site_id="Zeta"), replace(lane, site_id="Alpha"))
    result = run_scenario(lanes, settings)
    report = summary(result)
    rows = lane_table_rows(report, lane_uncertainty(result), settings.service_target)
    assert "Alpha:nitrogen" in rows[0] and "Zeta:nitrogen" in rows[1]


def test_page_is_well_formed(lane, settings):
    class _Balance(HTMLParser):
        void = {"meta", "line", "rect", "br"}

        def __init__(self):
            super().__init__()
            self.stack = []
            self.bad = []

        def handle_starttag(self, tag, attrs):
            if tag not in self.void:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag in self.void:
                return
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()
            else:
                self.bad.append(tag)

    result = run_scenario((lane,), settings)
    parser = _Balance()
    parser.feed(render_html(result, summary(result)))
    assert parser.bad == [] and parser.stack == []
