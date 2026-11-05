"""Service heatmap in report.md."""

from dataclasses import replace

from meridian.planning import run_scenario
from meridian.reporting import cells_by_lane, export_run, heatmap_counts, heatmap_lines, summary


def _report(rates):
    return {
        "lanes": [{"lane": lane, "validation_mean_fill_rate": rate} for lane, rate in rates.items()]
    }


def test_one_row_per_site():
    lines = heatmap_lines(
        _report({"Harbor:nitrogen": 0.99, "Meadow:oxygen": 0.97, "Harbor:argon": 0.98})
    )
    rows = [line for line in lines if line.startswith("| ") and not line.startswith("| Site")]
    assert [row.split("|")[1].strip() for row in rows] == ["Harbor", "Meadow"]


def test_missing_products_show_dash():
    lines = heatmap_lines(_report({"Meadow:oxygen": 0.97}))
    assert "| Meadow | – | 97.00% ✅ | – |" in lines


def test_header_lists_products():
    lines = heatmap_lines(_report({"Meadow:oxygen": 0.97}))
    assert "| Site | Nitrogen | Oxygen | Argon |" in lines


def test_markers_for_example_rates():
    lines = heatmap_lines(_report({"A:nitrogen": 0.99, "B:nitrogen": 0.80}))
    assert "| A | 99.00% ✅ | – | – |" in lines
    assert "| B | 80.00% ❌ | – | – |" in lines


def test_heatmap_in_report(tmp_path, lane, settings):
    lanes = (lane, replace(lane, product="oxygen"))
    bundle = export_run(run_scenario(lanes, settings), tmp_path)
    text = (bundle / "report.md").read_text(encoding="utf-8")
    assert "## Service by site and product" in text
    row = next(line for line in text.splitlines() if line.startswith("| Example |"))
    assert row.count("%") == 2


def test_rates_match_summary(lane, settings):
    report = summary(run_scenario((lane,), settings))
    rate = report["lanes"][0]["validation_mean_fill_rate"]
    assert any(f"{rate:.2%}" in line for line in heatmap_lines(report))


def test_counts_line():
    lines = heatmap_lines(_report({"A:nitrogen": 0.99, "A:oxygen": 0.92, "B:argon": 0.80}))
    assert lines[-1] == (
        "1 product-locations meet the target, 1 are within 5 points of it and 1 are further below."
    )


def test_cells_by_lane_skips_missing():
    lines = ["| Site | Nitrogen | Oxygen | Argon |", "| A | 99.00% ✅ | – | 80.00% ❌ |"]
    assert cells_by_lane(lines) == ["99.00% ✅", "80.00% ❌"]


def test_heatmap_counts():
    assert heatmap_counts(["1% ✅", "2% ⚠️", "3% ❌", "4% ❌"]) == {
        "meets": 1,
        "near": 1,
        "below": 2,
    }
