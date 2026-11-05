"""Delivery emissions."""

import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest

from meridian.cli import main
from meridian.emissions import (
    EMISSION_FACTOR,
    Delivery,
    deliveries,
    lane_emissions,
    load_distances,
    site_emissions,
    totals,
    trips,
    write_emissions,
)
from meridian.models import InputError
from meridian.planning import run_scenario

ROOT = Path(__file__).resolve().parents[2]


def _write(tmp_path, data):
    path = tmp_path / "distances.json"
    path.write_text(json.dumps(data))
    return path


def test_load_distances(tmp_path):
    assert load_distances(_write(tmp_path, {"Harbor": 40, "Meadow": 12.5})) == {
        "Harbor": 40.0,
        "Meadow": 12.5,
    }


@pytest.mark.parametrize(
    "data, message",
    [
        ([], "JSON object"),
        ({}, "JSON object"),
        ({"Harbor": 0}, "distance to Harbor"),
        ({"Harbor": 2500}, "at most 2000"),
        ({"Harbor": "far"}, "distance to Harbor"),
        ({"1bad": 5}, "site"),
    ],
)
def test_invalid_distances(tmp_path, data, message):
    with pytest.raises(InputError, match=message):
        load_distances(_write(tmp_path, data))


def test_single_delivery_round_trip():
    rows = lane_emissions([Delivery(1, "Harbor", "Harbor:nitrogen", 800.0)], {"Harbor": 40.0})
    (row,) = rows
    assert row["deliveries"] == 1
    assert row["distance_km"] == pytest.approx(80.0)
    assert row["kg_co2"] == pytest.approx(80.0 * EMISSION_FACTOR)
    assert row["kg_co2_per_tonne"] == pytest.approx(80.0 * EMISSION_FACTOR / 0.8)


def test_deliveries_on_different_days_are_separate_trips():
    found = [
        Delivery(1, "Harbor", "Harbor:nitrogen", 800.0),
        Delivery(3, "Harbor", "Harbor:nitrogen", 600.0),
    ]
    (row,) = lane_emissions(found, {"Harbor": 40.0})
    assert row["deliveries"] == 2
    assert row["kg_co2"] == pytest.approx(2 * 80.0 * EMISSION_FACTOR)


def test_missing_distance():
    with pytest.raises(InputError, match="Meadow"):
        lane_emissions([Delivery(1, "Meadow", "Meadow:oxygen", 100.0)], {"Harbor": 40.0})


def test_trips_group_by_site_and_day():
    found = [
        Delivery(1, "Harbor", "Harbor:nitrogen", 800.0),
        Delivery(1, "Harbor", "Harbor:oxygen", 300.0),
        Delivery(2, "Harbor", "Harbor:nitrogen", 500.0),
    ]
    grouped = trips(found)
    assert set(grouped) == {(1, "Harbor"), (2, "Harbor")}
    assert len(grouped[(1, "Harbor")]) == 2


def test_site_emissions_count_trips_once():
    found = [
        Delivery(1, "Harbor", "Harbor:nitrogen", 800.0),
        Delivery(1, "Harbor", "Harbor:oxygen", 300.0),
        Delivery(2, "Harbor", "Harbor:nitrogen", 500.0),
    ]
    (row,) = site_emissions(found, {"Harbor": 40.0})
    assert row["trips"] == 2
    assert row["multi_product_trips"] == 1
    assert row["distance_km"] == pytest.approx(160.0)
    assert row["kg_co2"] == pytest.approx(160.0 * EMISSION_FACTOR)


def test_totals_single_product():
    found = [
        Delivery(1, "Harbor", "Harbor:nitrogen", 800.0),
        Delivery(2, "Meadow", "Meadow:oxygen", 200.0),
    ]
    distances = {"Harbor": 40.0, "Meadow": 10.0}
    total = totals(lane_emissions(found, distances), site_emissions(found, distances))
    assert total["trips"] == 2
    assert total["distance_km"] == pytest.approx(100.0)
    assert total["kg_co2"] == pytest.approx(100.0 * EMISSION_FACTOR)
    assert total["delivered_tonnes"] == pytest.approx(1.0)


def test_totals_without_deliveries():
    total = totals([], [])
    assert total["trips"] == 0 and total["kg_co2_per_tonne"] == 0


def test_deliveries_from_result(lane, settings):
    result = run_scenario((lane,), settings)
    found = deliveries(result, 1)
    ordered = [p for p in result.results[0].validation_trials[0].periods if p.ordered_kg > 1e-9]
    assert len(found) == len(ordered)
    assert {d.site for d in found} == {"Example"}


def test_replication_range(lane, settings):
    with pytest.raises(InputError, match="replication"):
        deliveries(run_scenario((lane,), settings), 0)


def test_write_emissions(tmp_path):
    rows = lane_emissions([Delivery(1, "Harbor", "Harbor:nitrogen", 800.0)], {"Harbor": 40.0})
    path = write_emissions(rows, tmp_path / "out")
    with path.open(newline="") as stream:
        (row,) = list(csv.DictReader(stream))
    assert row["lane"] == "Harbor:nitrogen"
    assert float(row["kg_co2"]) == pytest.approx(80.0 * EMISSION_FACTOR)


def test_emissions_command(tmp_path, capsys):
    distances = _write(tmp_path, {"Harbor": 40, "Summit": 65, "Meadow": 18})
    code = main(
        [
            "emissions",
            "--data",
            str(ROOT / "data/synthetic_sites.csv"),
            "--config",
            str(ROOT / "config/quickstart.json"),
            "--distances",
            str(distances),
            "--output",
            str(tmp_path / "out"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "kg CO2" in out and "Emissions saved" in out
    assert (tmp_path / "out" / "emissions.csv").is_file()


def test_more_distance_more_emissions(lane, settings):
    found = deliveries(run_scenario((lane,), settings))
    near = lane_emissions(found, {"Example": 10.0})[0]["kg_co2"]
    far = lane_emissions(found, {"Example": 30.0})[0]["kg_co2"]
    assert far == pytest.approx(3 * near)


def test_multiple_sites(lane, settings):
    lanes = (lane, replace(lane, site_id="Other"))
    found = deliveries(run_scenario(lanes, settings))
    rows = lane_emissions(found, {"Example": 10.0, "Other": 20.0})
    assert [row["lane"] for row in rows] == ["Example:nitrogen", "Other:nitrogen"]


def test_worked_example_from_docs():
    found = [
        Delivery(3, "Harbor", "Harbor:nitrogen", 800.0),
        Delivery(3, "Harbor", "Harbor:oxygen", 300.0),
        Delivery(5, "Harbor", "Harbor:nitrogen", 600.0),
    ]
    (site,) = site_emissions(found, {"Harbor": 40.0})
    assert site["trips"] == 2
    assert site["distance_km"] == pytest.approx(160.0)
    assert site["kg_co2"] == pytest.approx(144.0)


def test_lane_rows_sorted_and_complete():
    found = [
        Delivery(1, "Meadow", "Meadow:oxygen", 100.0),
        Delivery(1, "Harbor", "Harbor:argon", 50.0),
    ]
    rows = lane_emissions(found, {"Harbor": 40.0, "Meadow": 10.0})
    assert [row["lane"] for row in rows] == ["Harbor:argon", "Meadow:oxygen"]
    for row in rows:
        assert set(row) == {
            "lane",
            "deliveries",
            "delivered_kg",
            "distance_km",
            "kg_co2",
            "kg_co2_per_tonne",
        }
