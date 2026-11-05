"""Comparing scenarios on selected product families."""

import json
from dataclasses import replace

import pytest

from meridian.cli import main
from meridian.planning import run_scenario
from meridian.reporting import compare_families, export_run


@pytest.fixture
def reports(tmp_path, lane, settings):
    lanes = (lane, replace(lane, site_id="Other", product="oxygen", daily_mean_kg=30))
    a = export_run(run_scenario(lanes, settings), tmp_path) / "summary.json"
    b = (
        export_run(
            run_scenario(lanes, replace(settings, scenario_id="higher", demand_multiplier=1.5)),
            tmp_path,
        )
        / "summary.json"
    )
    return a, b


def _lane_cost(path, product):
    report = json.loads(path.read_text())
    return sum(r["validation_mean_cost"] for r in report["lanes"] if r["lane"].endswith(product))


def test_single_family_totals(reports):
    rows = compare_families(list(reports), ["oxygen"])
    assert len(rows) == 2
    for row in rows:
        assert row["lanes"] == 1
        assert row["families"] == ["oxygen"]
    by_id = {row["scenario_id"]: row for row in rows}
    assert by_id["baseline"]["total_mean_cost"] == pytest.approx(_lane_cost(reports[0], "oxygen"))


def test_all_families_match_full_comparison(reports):
    from meridian.reporting import compare_reports

    full = {r["scenario_id"]: r["total_mean_cost"] for r in compare_reports(list(reports))}
    for row in compare_families(list(reports), ["nitrogen", "oxygen"]):
        assert row["lanes"] == 2
        assert row["total_mean_cost"] == pytest.approx(full[row["scenario_id"]])


def test_family_rows_sorted_by_cost(reports):
    rows = compare_families(list(reports), ["nitrogen"])
    costs = [row["total_mean_cost"] for row in rows]
    assert costs == sorted(costs)


def test_duplicate_families_counted_once(reports):
    (row, _) = compare_families(list(reports), ["oxygen", "oxygen"])
    assert row["families"] == ["oxygen"]


def test_cli_family(reports, capsys):
    assert main(["compare", *map(str, reports), "--family", "nitrogen"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {row["families"][0] for row in rows} == {"nitrogen"}
    assert all("report" not in row for row in rows)


def test_cli_without_family_unchanged(reports, capsys):
    assert main(["compare", *map(str, reports)]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert "families" not in rows[0]
