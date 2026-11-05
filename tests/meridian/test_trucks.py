"""Combining deliveries into shared truck trips."""

import csv
import json
from dataclasses import replace

import pytest

from meridian.cli import main
from meridian.models import InputError, Lane
from meridian.planning import run_scenario
from meridian.trucks import (
    Delivery,
    Routes,
    Trip,
    deliveries_from_result,
    load_routes,
    plan_trucks,
    savings,
    trip_rows,
    write_trips,
)

CAPACITY = {"nitrogen": 20.0, "oxygen": 20.0, "argon": 18.0}


def _routes(**changes):
    base = Routes({"Coastal": ("Harbor", "Summit")}, CAPACITY, 100.0)
    return replace(base, **changes)


def _delivery(site, quantity_kg, day=1, product="nitrogen", cost=60.0):
    return Delivery(day, f"{site}:{product}", site, product, quantity_kg, cost)


def _write_routes(tmp_path, data):
    path = tmp_path / "routes.json"
    path.write_text(json.dumps(data))
    return path


VALID = {
    "truck_capacity_t": {"nitrogen": 20, "oxygen": 20, "argon": 18},
    "trip_cost": 110,
    "routes": [{"route_id": "Coastal", "sites": ["Harbor", "Summit"]}],
}


def test_load_routes(tmp_path):
    routes = load_routes(_write_routes(tmp_path, VALID))
    assert routes.routes == {"Coastal": ("Harbor", "Summit")}
    assert routes.capacity_t["argon"] == 18
    assert routes.trip_cost == 110


@pytest.mark.parametrize(
    "change, message",
    [
        ({"truck_capacity_t": {"nitrogen": 20}}, "nitrogen, oxygen and argon"),
        ({"truck_capacity_t": {"nitrogen": 0, "oxygen": 20, "argon": 18}}, "capacity"),
        ({"routes": []}, "non-empty"),
        ({"routes": [{"route_id": "A", "sites": []}]}, "at least one site"),
        (
            {"routes": [{"route_id": "A", "sites": ["X"]}, {"route_id": "A", "sites": ["Y"]}]},
            "Duplicate route",
        ),
        (
            {"routes": [{"route_id": "A", "sites": ["X"]}, {"route_id": "B", "sites": ["X"]}]},
            "on routes A and B",
        ),
    ],
)
def test_invalid_routes(tmp_path, change, message):
    with pytest.raises(InputError, match=message):
        load_routes(_write_routes(tmp_path, {**VALID, **change}))


def test_routes_file_must_be_object(tmp_path):
    path = tmp_path / "routes.json"
    path.write_text("[]")
    with pytest.raises(InputError, match="JSON object"):
        load_routes(path)


def test_same_route_same_day_share_a_truck():
    trips = plan_trucks([_delivery("Harbor", 6.0), _delivery("Summit", 5.0)], _routes())
    assert len(trips) == 1
    assert trips[0].load_kg == pytest.approx(11.0)
    assert {d.site for d in trips[0].deliveries} == {"Harbor", "Summit"}


def test_different_days_do_not_share():
    trips = plan_trucks(
        [_delivery("Harbor", 6.0, day=1), _delivery("Summit", 5.0, day=2)], _routes()
    )
    assert [trip.day for trip in trips] == [1, 2]


def test_different_products_do_not_share():
    trips = plan_trucks(
        [_delivery("Harbor", 6.0), _delivery("Summit", 5.0, product="oxygen")], _routes()
    )
    assert len(trips) == 2


def test_site_without_route_travels_alone():
    trips = plan_trucks([_delivery("Harbor", 6.0), _delivery("Meadow", 5.0)], _routes())
    assert {trip.route for trip in trips} == {"Coastal", "direct-Meadow"}


def test_best_fill_first():
    deliveries = [
        _delivery("Harbor", 12.0),
        _delivery("Summit", 9.0),
        _delivery("Harbor", 7.0, day=1),
    ]
    trips = plan_trucks(deliveries, _routes())
    loads = sorted(trip.load_kg for trip in trips)
    assert loads == pytest.approx([9.0, 19.0])


def test_every_delivery_assigned_once():
    deliveries = [_delivery("Harbor", q) for q in (3.0, 4.0, 5.0, 6.0, 7.0)]
    trips = plan_trucks(deliveries, _routes())
    carried = sorted(d.quantity_kg for trip in trips for d in trip.deliveries)
    assert carried == [3.0, 4.0, 5.0, 6.0, 7.0]
    assert sum(trip.load_kg for trip in trips) == pytest.approx(25.0)


def test_trip_utilisation():
    trip = Trip(1, "Coastal", "nitrogen", (_delivery("Harbor", 5000.0),), 20.0)
    assert trip.utilisation == pytest.approx(0.25)


def test_trip_rows():
    trips = plan_trucks([_delivery("Harbor", 6.0), _delivery("Summit", 5.0)], _routes())
    (row,) = trip_rows(trips)
    assert row["trip"] == 1
    assert row["sites"] == "Harbor+Summit"
    assert row["deliveries"] == 2


def test_savings():
    deliveries = [
        _delivery("Harbor", 6.0),
        _delivery("Summit", 5.0),
        _delivery("Harbor", 4.0, day=2),
    ]
    trips = plan_trucks(deliveries, _routes())
    totals = savings(deliveries, trips, _routes())
    assert totals["deliveries"] == 3
    assert totals["trips"] == 2
    assert totals["busiest_day_trips"] == 1
    assert totals["separate_delivery_cost"] == pytest.approx(180.0)
    assert totals["combined_trip_cost"] == pytest.approx(200.0)
    assert totals["saving"] == pytest.approx(-20.0)


def test_write_trips(tmp_path):
    trips = plan_trucks([_delivery("Harbor", 6.0)], _routes())
    path = write_trips(trips, tmp_path / "out")
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["route"] == "Coastal"


@pytest.fixture
def small_lanes():
    base = Lane("Harbor", "nitrogen", 3, 0.5, 1, 6, 0.1, 2, 60, 0.2)
    return (
        base,
        replace(base, site_id="Summit"),
        replace(base, site_id="Meadow", product="oxygen"),
    )


def test_deliveries_from_result(small_lanes, settings):
    result = run_scenario(small_lanes, settings)
    deliveries = deliveries_from_result(result, 2)
    trial_orders = sum(
        1 for lr in result.results for p in lr.validation_trials[1].periods if p.ordered_kg > 1e-9
    )
    assert len(deliveries) == trial_orders
    assert all(d.quantity_kg > 0 for d in deliveries)


def test_replication_range(small_lanes, settings):
    result = run_scenario(small_lanes, settings)
    with pytest.raises(InputError, match="replication"):
        deliveries_from_result(result, settings.replications + 1)


def test_trucks_command(tmp_path, capsys, small_lanes):
    data = tmp_path / "lanes.csv"
    with data.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "site_id",
                "product",
                "daily_mean_kg",
                "daily_sd_kg",
                "lead_time_days",
                "initial_inventory_kg",
                "holding_cost_per_kg_day",
                "backlog_cost_per_kg_day",
                "delivery_cost_per_order",
                "purchase_cost_per_kg",
            ]
        )
        for lane in small_lanes:
            writer.writerow(
                [
                    lane.site_id,
                    lane.product,
                    lane.daily_mean_kg,
                    lane.daily_sd_kg,
                    lane.lead_time_days,
                    lane.initial_inventory_kg,
                    lane.holding_cost_per_kg_day,
                    lane.backlog_cost_per_kg_day,
                    lane.delivery_cost_per_order,
                    lane.purchase_cost_per_kg,
                ]
            )
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"horizon_days": 10, "replications": 2}))
    routes = _write_routes(tmp_path, VALID)
    code = main(
        [
            "trucks",
            "--data",
            str(data),
            "--config",
            str(config),
            "--routes",
            str(routes),
            "--output",
            str(tmp_path / "out"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "deliveries in" in out and "Truck plan saved" in out
    assert (tmp_path / "out" / "trucks.csv").is_file()
