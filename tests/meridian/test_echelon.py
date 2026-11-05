"""Two-echelon depot-to-site planning."""

import csv
import json
from dataclasses import replace
from math import ceil, sqrt
from pathlib import Path

import pytest

from meridian.cli import main
from meridian.echelon import (
    Depot,
    depot_summary,
    effective_lead_time,
    load_depots,
    plan_echelon,
    safety_stock,
    service_z,
    site_base_stock,
)
from meridian.models import InputError

ROOT = Path(__file__).resolve().parents[2]


def _depot(**changes):
    base = Depot("GulfDepot", 3, 0.006, 500.0, ("Example",))
    return replace(base, **changes)


def _write(tmp_path, depots):
    path = tmp_path / "depots.json"
    path.write_text(json.dumps({"depots": depots}))
    return path


def test_effective_lead_time(lane):
    assert effective_lead_time(lane, None) == lane.lead_time_days
    assert effective_lead_time(lane, _depot()) == lane.lead_time_days + 3


def test_direct_safety_stock(lane, settings):
    expected = service_z(settings.service_target) * lane.daily_sd_kg * sqrt(lane.lead_time_days + 1)
    assert safety_stock(lane, None, settings) == pytest.approx(expected)


def test_service_z_bounds():
    assert service_z(1.0) < 4
    assert service_z(0.3) == 0
    assert service_z(0.95) == pytest.approx(1.6449, abs=1e-4)


def test_direct_base_stock(lane, settings):
    demand_kg, base_kg = site_base_stock(lane, None, settings)
    assert demand_kg == pytest.approx(lane.daily_mean_kg * (lane.lead_time_days + 1))
    assert base_kg == ceil(demand_kg + safety_stock(lane, None, settings))


def test_depot_base_stock_covers_longer_lead_time(lane, settings):
    direct_demand, direct_base = site_base_stock(lane, None, settings)
    depot_demand, depot_base = site_base_stock(lane, _depot(), settings)
    assert depot_demand == pytest.approx(direct_demand + 3 * lane.daily_mean_kg)
    assert depot_base > direct_base


def test_load_depots_hours_round_up(tmp_path):
    path = _write(
        tmp_path,
        [
            {
                "depot_id": "Plains",
                "lead_time_hours": 36,
                "holding_cost_per_kg_day": 0.01,
                "sites": ["Meadow"],
            }
        ],
    )
    (depot,) = load_depots(path)
    assert depot.lead_time_days == 2
    assert depot.initial_inventory_kg == 0


@pytest.mark.parametrize(
    "depots, message",
    [
        (
            [
                {
                    "depot_id": "A",
                    "lead_time_days": 2.5,
                    "holding_cost_per_kg_day": 0,
                    "sites": ["X"],
                }
            ],
            "whole number",
        ),
        (
            [{"depot_id": "A", "lead_time_days": 31, "holding_cost_per_kg_day": 0, "sites": ["X"]}],
            "at most 30",
        ),
        (
            [{"depot_id": "A", "lead_time_days": 1, "holding_cost_per_kg_day": 0, "sites": []}],
            "at least one site",
        ),
        (
            [
                {
                    "depot_id": "A",
                    "lead_time_days": 1,
                    "holding_cost_per_kg_day": 0,
                    "sites": ["X"],
                },
                {
                    "depot_id": "B",
                    "lead_time_days": 1,
                    "holding_cost_per_kg_day": 0,
                    "sites": ["X"],
                },
            ],
            "listed under A and B",
        ),
        (
            [
                {
                    "depot_id": "A",
                    "lead_time_days": 1,
                    "holding_cost_per_kg_day": 0,
                    "sites": ["X"],
                },
                {
                    "depot_id": "A",
                    "lead_time_days": 1,
                    "holding_cost_per_kg_day": 0,
                    "sites": ["Y"],
                },
            ],
            "unique",
        ),
    ],
)
def test_invalid_depots(tmp_path, depots, message):
    with pytest.raises(InputError, match=message):
        load_depots(_write(tmp_path, depots))


def test_depot_file_must_be_object(tmp_path):
    path = tmp_path / "depots.json"
    path.write_text("[]")
    with pytest.raises(InputError, match="depots"):
        load_depots(path)


def test_allocation_largest_shortfall_first(tmp_path, lane, settings):
    big = replace(lane, site_id="Big", daily_mean_kg=100, initial_inventory_kg=0)
    small = replace(lane, site_id="Small", daily_mean_kg=10, initial_inventory_kg=0)
    path = _write(
        tmp_path,
        [
            {
                "depot_id": "D",
                "lead_time_days": 1,
                "holding_cost_per_kg_day": 0.01,
                "initial_inventory_kg": 150,
                "sites": ["Big", "Small"],
            }
        ],
    )
    rows = {row["lane"]: row for row in plan_echelon((big, small), settings, path, tmp_path)}
    assert rows[big.key]["allocated_from_depot_kg"] == 150
    assert rows[small.key]["allocated_from_depot_kg"] == 0
    assert rows[small.key]["unmet_shortfall_kg"] == rows[small.key]["site_shortfall_kg"]


def test_allocation_never_exceeds_shortfall(tmp_path, lane, settings):
    path = _write(
        tmp_path,
        [
            {
                "depot_id": "D",
                "lead_time_days": 1,
                "holding_cost_per_kg_day": 0.01,
                "initial_inventory_kg": 100000,
                "sites": ["Example"],
            }
        ],
    )
    (row,) = plan_echelon((replace(lane, initial_inventory_kg=0),), settings, path, tmp_path)
    assert row["allocated_from_depot_kg"] == row["site_shortfall_kg"]
    assert row["unmet_shortfall_kg"] == 0
    (summary,) = depot_summary([row], load_depots(path))
    assert summary["left_at_depot_kg"] == pytest.approx(100000 - row["allocated_from_depot_kg"])


def test_direct_sites_planned_without_depot(tmp_path, lane, settings):
    path = _write(
        tmp_path,
        [
            {
                "depot_id": "D",
                "lead_time_days": 1,
                "holding_cost_per_kg_day": 0.01,
                "sites": ["Other"],
            }
        ],
    )
    (row,) = plan_echelon((lane,), settings, path, tmp_path)
    assert row["depot"] == "direct"
    assert row["effective_lead_time_days"] == lane.lead_time_days
    assert row["allocated_from_depot_kg"] == 0


def test_echelon_csv_written(tmp_path, lane, settings):
    path = _write(
        tmp_path,
        [
            {
                "depot_id": "D",
                "lead_time_days": 2,
                "holding_cost_per_kg_day": 0.01,
                "sites": ["Example"],
            }
        ],
    )
    plan_echelon((lane,), settings, path, tmp_path / "out")
    with (tmp_path / "out" / "echelon.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1 and rows[0]["depot"] == "D"


def test_echelon_command(tmp_path, capsys):
    code = main(
        [
            "echelon",
            "--data",
            str(ROOT / "data/synthetic_sites.csv"),
            "--config",
            str(ROOT / "config/quickstart.json"),
            "--depots",
            str(ROOT / "config/depots.json"),
            "--output",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "GulfDepot: 4 lanes" in out and "PlainsDepot: 2 lanes" in out
    assert (tmp_path / "echelon.csv").is_file()
