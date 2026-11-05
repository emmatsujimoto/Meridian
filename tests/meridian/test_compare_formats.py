"""compare output formats."""

import json
from dataclasses import replace

import pytest

from meridian.cli import main
from meridian.planning import run_scenario
from meridian.reporting import comparison_json, export_run

yaml = pytest.importorskip("yaml")


@pytest.fixture
def reports(tmp_path, lane, settings):
    a = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    b = (
        export_run(
            run_scenario((lane,), replace(settings, scenario_id="higher", demand_multiplier=1.4)),
            tmp_path,
        )
        / "summary.json"
    )
    return [str(a), str(b)]


def test_json_default(reports, capsys):
    assert main(["compare", *reports]) == 0
    scenarios = json.loads(capsys.readouterr().out)
    assert scenarios[0]["cost_vs_cheapest"] == 1.0
    assert scenarios[1]["cost_vs_cheapest"] > 1.0


def test_json_relative_cost():
    rows = [
        {"scenario_id": "a", "total_mean_cost": 100.0},
        {"scenario_id": "b", "total_mean_cost": 150.0},
    ]
    document = json.loads(comparison_json(rows))
    assert [s["cost_vs_cheapest"] for s in document] == [1.0, 1.5]


def test_yaml_format_selected(reports, capsys):
    assert main(["compare", *reports, "--format", "yaml"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("- scenario_id:")
    assert "scenario_id: baseline" in out and "scenario_id: higher" in out


def test_unknown_format_rejected(reports):
    with pytest.raises(SystemExit):
        main(["compare", *reports, "--format", "xml"])


def test_yaml_lists_every_field(reports, capsys):
    assert main(["compare", *reports, "--format", "yaml"]) == 0
    out = capsys.readouterr().out
    for field in ("total_mean_cost", "portfolio_fill_rate", "input_sha256", "cost_vs_cheapest"):
        assert out.count(f"{field}:") == 2


def test_json_keeps_existing_fields(reports, capsys):
    assert main(["compare", *reports, "--format", "json"]) == 0
    first = json.loads(capsys.readouterr().out)[0]
    assert {"scenario_id", "total_mean_cost", "portfolio_fill_rate", "input_sha256"} <= set(first)
