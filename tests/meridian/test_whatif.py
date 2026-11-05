"""Sharing proposed plant capacity between product-locations."""

import json
from dataclasses import replace

import pytest

from meridian.cli import main
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run, summary
from meridian.whatif import (
    Allocation,
    allocate,
    allocation_rows,
    allocation_summary,
    lane_demands,
    validate_capacities,
)

DEMANDS = {
    "Harbor:nitrogen": 800.0,
    "Summit:nitrogen": 400.0,
    "Meadow:nitrogen": 200.0,
    "Harbor:oxygen": 500.0,
    "Summit:argon": 120.0,
}


def _by_lane(allocations):
    return {a.lane: a for a in allocations}


def test_enough_capacity_covers_everyone():
    result = _by_lane(allocate(DEMANDS, {"nitrogen": 5000}))
    assert {lane: a.allocated_kg for lane, a in result.items()} == {
        "Harbor:nitrogen": 800.0,
        "Meadow:nitrogen": 200.0,
        "Summit:nitrogen": 400.0,
    }
    assert all(a.shortfall_kg == 0 for a in result.values())


def test_short_capacity_shared_in_proportion():
    result = _by_lane(allocate(DEMANDS, {"nitrogen": 700}))
    assert result["Harbor:nitrogen"].allocated_kg == pytest.approx(400.0)
    assert result["Summit:nitrogen"].allocated_kg == pytest.approx(200.0)
    assert result["Meadow:nitrogen"].allocated_kg == pytest.approx(100.0)
    assert all(a.coverage == pytest.approx(0.5) for a in result.values())


def test_capacity_exactly_demand():
    result = allocate(DEMANDS, {"nitrogen": 1400})
    assert sum(a.allocated_kg for a in result) == pytest.approx(1400.0)
    assert all(a.shortfall_kg == pytest.approx(0.0) for a in result)


def test_zero_capacity():
    result = allocate(DEMANDS, {"argon": 0})
    assert result == [Allocation("Summit:argon", "argon", 120.0, 0.0)]
    assert result[0].shortfall_kg == 120.0
    assert result[0].coverage == 0.0


def test_lane_without_demand_redistributes():
    demands = {"A:oxygen": 0.0, "B:oxygen": 100.0, "C:oxygen": 300.0}
    result = _by_lane(allocate(demands, {"oxygen": 200}))
    assert result["A:oxygen"].allocated_kg == 0.0
    assert result["A:oxygen"].coverage == 1.0
    assert result["B:oxygen"].allocated_kg == pytest.approx(50.0)
    assert result["C:oxygen"].allocated_kg == pytest.approx(150.0)


def test_never_more_than_demand():
    for capacity in (0, 50, 333, 1399, 1400, 1401, 10_000):
        result = allocate(DEMANDS, {"nitrogen": capacity})
        assert all(a.allocated_kg <= a.demand_kg + 1e-9 for a in result)
        assert sum(a.allocated_kg for a in result) == pytest.approx(min(capacity, 1400.0))


def test_products_without_capacity_left_out():
    products = {a.product for a in allocate(DEMANDS, {"oxygen": 100, "argon": 10})}
    assert products == {"oxygen", "argon"}


def test_product_filter():
    result = allocate(DEMANDS, {"nitrogen": 100, "oxygen": 100}, "oxygen")
    assert [a.lane for a in result] == ["Harbor:oxygen"]


def test_unknown_product_filter():
    with pytest.raises(InputError, match="Unknown product"):
        allocate(DEMANDS, {"nitrogen": 100}, "helium")


@pytest.mark.parametrize(
    "capacities",
    [None, {}, [], {"helium": 5}, {"nitrogen": -1}, {"nitrogen": "lots"}, {"nitrogen": True}],
)
def test_invalid_capacities(capacities):
    with pytest.raises(InputError):
        validate_capacities(capacities)


def test_summary():
    totals = allocation_summary(allocate(DEMANDS, {"nitrogen": 700}))
    assert totals == {
        "lanes": 3,
        "demand_kg": 1400.0,
        "allocated_kg": pytest.approx(700.0),
        "shortfall_kg": pytest.approx(700.0),
        "lanes_short": 3,
        "coverage": pytest.approx(0.5),
    }


def test_summary_empty():
    assert allocation_summary([])["coverage"] == 1.0


def test_rows():
    rows = allocation_rows([Allocation("A:argon", "argon", 100.0, 80.0)])
    assert rows == [
        {
            "lane": "A:argon",
            "product": "argon",
            "demand_kg": 100.0,
            "allocated_kg": 80.0,
            "shortfall_kg": 20.0,
            "coverage": 0.8,
        }
    ]


def test_lane_demands_use_multiplier(lane, settings):
    report = summary(run_scenario((lane,), replace(settings, demand_multiplier=1.5)))
    assert lane_demands(report) == {"Example:nitrogen": pytest.approx(15.0)}


def test_lane_demands_require_inputs():
    with pytest.raises(InputError, match="lane inputs"):
        lane_demands({"lanes": []})


# Priorities


def test_priorities_shift_share():
    demands = {"A:argon": 100.0, "B:argon": 100.0}
    result = _by_lane(allocate(demands, {"argon": 100}, priorities={"A:argon": 3}))
    assert result["A:argon"].allocated_kg == pytest.approx(75.0)
    assert result["B:argon"].allocated_kg == pytest.approx(25.0)


def test_priorities_still_capped_at_demand():
    demands = {"A:argon": 10.0, "B:argon": 100.0}
    result = _by_lane(allocate(demands, {"argon": 60}, priorities={"A:argon": 100}))
    assert result["A:argon"].allocated_kg == pytest.approx(10.0)
    assert result["B:argon"].allocated_kg == pytest.approx(50.0)


def test_default_priorities_are_equal():
    with_default = allocate(DEMANDS, {"nitrogen": 700})
    explicit = allocate(DEMANDS, {"nitrogen": 700}, priorities={"Harbor:nitrogen": 1})
    assert with_default == explicit


@pytest.mark.parametrize(
    "priorities", [[1], {"Nowhere:argon": 2}, {"Summit:argon": 0}, {"Summit:argon": "high"}]
)
def test_invalid_priorities(priorities):
    with pytest.raises(InputError):
        allocate(DEMANDS, {"argon": 10}, priorities=priorities)


def test_cli_what_if(tmp_path, lane, settings, capsys):
    bundle = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    assert main(["what-if", str(bundle), "--capacity", "nitrogen=4"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["allocations"][0]["allocated_kg"] == pytest.approx(4.0)
    assert output["summary"]["lanes_short"] == 1


def test_cli_what_if_bad_capacity(tmp_path, lane, settings, capsys):
    bundle = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    assert main(["what-if", str(bundle), "--capacity", "nitrogen:lots"]) == 2
    assert "nitrogen=1200" in capsys.readouterr().err


def test_cli_what_if_several_products(tmp_path, lane, settings, capsys):
    oxygen = replace(lane, product="oxygen")
    bundle = export_run(run_scenario((lane, oxygen), settings), tmp_path) / "summary.json"
    args = ["what-if", str(bundle), "--capacity", "nitrogen=100", "--capacity", "oxygen=1"]
    assert main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert {row["product"] for row in output["allocations"]} == {"nitrogen", "oxygen"}
    assert output["summary"]["lanes_short"] == 1


def test_cli_what_if_unknown_product(tmp_path, lane, settings, capsys):
    bundle = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    assert main(["what-if", str(bundle), "--capacity", "helium=5"]) == 2
    assert "Unknown product in capacities: helium" in capsys.readouterr().err


def test_allocation_properties():
    allocation = Allocation("A:argon", "argon", 50.0, 60.0)
    assert allocation.shortfall_kg == 0.0
    assert allocation.coverage == pytest.approx(1.2)
