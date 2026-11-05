"""The HTML report and its cost breakdown chart."""

import re
from dataclasses import replace
from html.parser import HTMLParser

import pytest

from meridian.cli import main
from meridian.html_report import (
    COMPONENTS,
    _cost_components,
    cost_chart,
    cost_shares,
    render_html,
    write_html,
)
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run, summary


@pytest.fixture
def two_lanes(lane):
    return (lane, replace(lane, site_id="North", daily_mean_kg=14, daily_sd_kg=3))


@pytest.fixture
def bundle(tmp_path, two_lanes, settings):
    return export_run(run_scenario(two_lanes, settings), tmp_path) / "summary.json"


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def _tags(text):
    parser = _Collector()
    parser.feed(text)
    return parser.tags


def test_components_match_summary(two_lanes, settings, bundle):
    report = summary(run_scenario(two_lanes, settings))
    components = _cost_components(bundle)
    for row in report["lanes"]:
        parts = components[row["lane"]]
        assert parts["holding"] == pytest.approx(row["mean_holding_cost"])
        assert parts["backlog"] == pytest.approx(row["mean_backlog_cost"])
        assert parts["ordering"] == pytest.approx(
            row["mean_delivery_cost"] + row["mean_purchase_cost"]
        )
        assert sum(parts.values()) == pytest.approx(row["validation_mean_cost"])


def test_chart_has_one_bar_segment_per_component(bundle):
    components = _cost_components(bundle)
    rects = [attrs for tag, attrs in _tags(cost_chart(components)) if tag == "rect"]
    assert len(rects) == len(components) * len(COMPONENTS) + len(COMPONENTS)


def test_chart_widths_proportional(bundle):
    components = _cost_components(bundle)
    svg = cost_chart(components)
    lanes = sorted(components)
    widths = [float(a["width"]) for t, a in _tags(svg) if t == "rect"]
    per_lane = [sum(widths[i * 3 : i * 3 + 3]) for i in range(len(lanes))]
    totals = [sum(components[lane].values()) for lane in lanes]
    assert per_lane[0] / per_lane[1] == pytest.approx(totals[0] / totals[1], rel=1e-2)


def test_chart_escapes_labels():
    svg = cost_chart({"A<b>:nitrogen": dict.fromkeys(COMPONENTS, 1.0)})
    assert "A<b>" not in svg
    assert "A&lt;b&gt;:nitrogen" in svg


def test_chart_handles_zero_costs():
    svg = cost_chart({"A:nitrogen": dict.fromkeys(COMPONENTS, 0.0)})
    assert svg.startswith("<svg")


def test_chart_needs_lanes():
    with pytest.raises(InputError, match="No lanes"):
        cost_chart({})


def test_render_html(bundle):
    text = render_html(bundle)
    assert text.startswith("<!doctype html>")
    assert "<title>Meridian scenario: baseline</title>" in text
    assert "<svg" in text
    assert "<script" not in text
    assert "http" not in text.split("<body>")[1]


def test_html_table_rows(bundle):
    text = render_html(bundle)
    body = text.split("<tbody>")[-1]
    assert len(re.findall("<tr>", body)) == 2
    assert "Example:nitrogen" in body
    assert "North:nitrogen" in body


def test_write_html_default_location(bundle):
    path = write_html(bundle)
    assert path == bundle.parent / "report.html"
    assert path.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_write_html_never_replaces(bundle, tmp_path):
    target = tmp_path / "report.html"
    write_html(bundle, target)
    with pytest.raises(InputError, match="already exists"):
        write_html(bundle, target)


def test_bundle_still_verifies_after_writing(bundle):
    from meridian.bundles import verify_bundle

    write_html(bundle)
    assert verify_bundle(bundle)["scenario_id"] == "baseline"


def test_rejects_unverified(tmp_path):
    with pytest.raises(InputError):
        render_html(tmp_path / "summary.json")


def test_cli_html_report(bundle, tmp_path, capsys):
    target = tmp_path / "out.html"
    assert main(["html-report", str(bundle), "--output", str(target)]) == 0
    assert "HTML report written to" in capsys.readouterr().out
    assert target.is_file()


def test_cli_html_report_missing(tmp_path, capsys):
    assert main(["html-report", str(tmp_path / "summary.json")]) == 2


def test_cost_shares_sum_to_one(bundle):
    shares = cost_shares(_cost_components(bundle))
    assert sum(shares.values()) == pytest.approx(1.0)
    assert set(shares) == set(COMPONENTS)


def test_cost_shares_values():
    components = {
        "A:nitrogen": {"holding": 10.0, "ordering": 30.0, "backlog": 0.0},
        "B:nitrogen": {"holding": 10.0, "ordering": 50.0, "backlog": 0.0},
    }
    assert cost_shares(components) == {"holding": 0.2, "ordering": 0.8, "backlog": 0.0}


def test_cost_shares_without_cost():
    assert cost_shares({"A:nitrogen": dict.fromkeys(COMPONENTS, 0.0)}) == dict.fromkeys(
        COMPONENTS, 0.0
    )


def test_html_component_table(bundle):
    text = render_html(bundle)
    assert "<th>Component</th><th>Cost</th><th>Share</th>" in text
    for name in COMPONENTS:
        assert f"<tr><td>{name.capitalize()}</td>" in text
