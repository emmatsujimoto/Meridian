"""Consolidating orders within a batching window."""

import csv
from pathlib import Path

import pytest

from meridian.batching import (
    Order,
    best_windows,
    compare_windows,
    consolidate_orders,
    orders_from_result,
    totals,
    write_batching,
)
from meridian.cli import main
from meridian.models import InputError
from meridian.planning import run_scenario

ROOT = Path(__file__).resolve().parents[2]


def _orders(days, lane="A:nitrogen", kg=100.0, cost=50.0, holding=0.1):
    return [Order(lane, day, kg, cost, holding) for day in days]


def test_window_one_keeps_every_order():
    (row,) = consolidate_orders(_orders([1, 2, 3]), 1)
    assert row["orders"] == 3 and row["deliveries"] == 3
    assert row["delivery_cost_after"] == row["delivery_cost_before"] == 150.0
    assert row["extra_holding_cost"] == 0
    assert row["net_saving"] == 0


def test_window_groups_from_first_order():
    (row,) = consolidate_orders(_orders([1, 2, 3, 5, 9]), 3)
    assert row["deliveries"] == 3
    assert row["delivery_cost_after"] == pytest.approx(150.0)


def test_extra_holding_cost():
    (row,) = consolidate_orders(_orders([1, 3]), 3)
    assert row["deliveries"] == 1
    assert row["extra_holding_cost"] == pytest.approx(100 * 2 * 0.1)
    assert row["net_saving"] == pytest.approx(50.0 - 20.0)


def test_lanes_kept_separate():
    rows = consolidate_orders(
        _orders([1, 2], lane="A:nitrogen") + _orders([1, 2], lane="B:oxygen"), 3
    )
    assert [row["lane"] for row in rows] == ["A:nitrogen", "B:oxygen"]
    assert all(row["deliveries"] == 1 for row in rows)


def test_quantities_preserved():
    (row,) = consolidate_orders(_orders([1, 2, 6], kg=40.0), 2)
    assert row["delivered_kg"] == pytest.approx(120.0)


def test_unsorted_input():
    (row,) = consolidate_orders(_orders([6, 1, 2]), 2)
    assert row["deliveries"] == 2


def test_no_orders():
    assert consolidate_orders([], 3) == []


def test_totals():
    rows = consolidate_orders(
        _orders([1, 2], lane="A:nitrogen") + _orders([1, 5], lane="B:oxygen"), 3
    )
    total = totals(rows)
    assert total["orders"] == 4
    assert total["deliveries"] == 3
    assert total["delivery_cost_before"] == pytest.approx(200.0)
    assert total["delivery_cost_after"] == pytest.approx(150.0)


def test_orders_from_result(lane, settings):
    result = run_scenario((lane,), settings)
    found = orders_from_result(result, 2)
    expected = [p for p in result.results[0].validation_trials[1].periods if p.ordered_kg > 1e-9]
    assert [order.day for order in found] == [p.day for p in expected]
    assert all(order.delivery_cost == lane.delivery_cost_per_order for order in found)


def test_replication_range(lane, settings):
    with pytest.raises(InputError, match="replication"):
        orders_from_result(run_scenario((lane,), settings), 3)


def test_write_batching(tmp_path):
    path = write_batching(consolidate_orders(_orders([1, 2]), 2), tmp_path)
    with path.open(newline="") as stream:
        (row,) = list(csv.DictReader(stream))
    assert row["deliveries"] == "1"


def test_batching_command(tmp_path, capsys):
    code = main(
        [
            "batching",
            "--data",
            str(ROOT / "data/synthetic_sites.csv"),
            "--config",
            str(ROOT / "config/quickstart.json"),
            "--window",
            "3",
            "--output",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "orders become" in out
    assert (tmp_path / "batching.csv").is_file()


def test_compare_windows_rows():
    orders = _orders([1, 2, 3, 4, 8])
    rows = compare_windows(orders, [3, 1, 3])
    assert [row["window_days"] for row in rows] == [1, 3]
    assert rows[0]["deliveries"] == 5
    assert rows[1]["deliveries"] == 3


def test_compare_windows_needs_windows():
    with pytest.raises(InputError, match="at least one window"):
        compare_windows(_orders([1]), [])


def test_best_windows_prefers_saving():
    cheap_holding = _orders([1, 2, 3], lane="A:nitrogen", holding=0.01)
    dear_holding = _orders([1, 2, 3], lane="B:oxygen", holding=5.0)
    best = best_windows(cheap_holding + dear_holding, [1, 3])
    assert best == {"A:nitrogen": 3, "B:oxygen": 1}


def test_best_windows_ties_go_to_shorter():
    assert best_windows(_orders([1, 10]), [1, 2]) == {"A:nitrogen": 1}


def test_best_windows_needs_windows():
    with pytest.raises(InputError, match="at least one window"):
        best_windows(_orders([1]), [])


def test_batching_command_compare(tmp_path, capsys):
    code = main(
        [
            "batching",
            "--data",
            str(ROOT / "data/synthetic_sites.csv"),
            "--config",
            str(ROOT / "config/quickstart.json"),
            "--window",
            "2",
            "--compare",
            "1",
            "3",
            "--output",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "window 1 days:" in out and "window 3 days:" in out
    assert out.count("best window for") == 6


def test_longer_window_never_more_deliveries():
    orders = _orders([1, 2, 4, 5, 7, 8, 12, 13, 14])
    counts = [totals(consolidate_orders(orders, days))["deliveries"] for days in (1, 2, 3, 5, 8)]
    assert counts == sorted(counts, reverse=True)


def test_rows_have_all_fields():
    (row,) = consolidate_orders(_orders([1, 4]), 2)
    assert tuple(row) == (
        "lane",
        "orders",
        "deliveries",
        "delivered_kg",
        "delivery_cost_before",
        "delivery_cost_after",
        "extra_holding_cost",
        "net_saving",
    )


def test_net_saving_reconciles():
    (row,) = consolidate_orders(_orders([1, 2, 3, 9], cost=80.0, holding=0.2), 3)
    expected = row["delivery_cost_before"] - row["delivery_cost_after"] - row["extra_holding_cost"]
    assert row["net_saving"] == pytest.approx(expected, abs=0.01)
