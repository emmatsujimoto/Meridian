"""Consolidate a lane's orders that fall within a batching window into one delivery.

The simulation places an order whenever stock falls below the base stock, which can mean
deliveries on several consecutive days. Combining orders placed within N days of the
first into one delivery on that first day saves delivery charges, at the cost of holding
the extra stock earlier. This module estimates that trade-off from simulated orders.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from meridian.models import InputError, RunResult

ROW_FIELDS = (
    "lane",
    "orders",
    "deliveries",
    "delivered_kg",
    "delivery_cost_before",
    "delivery_cost_after",
    "extra_holding_cost",
    "net_saving",
)


@dataclass(frozen=True)
class Order:
    """One simulated order: lane, day placed, quantity (kg) and the lane's cost terms."""

    lane: str
    day: int
    quantity_kg: float
    delivery_cost: float
    holding_cost_per_kg_day: float


def orders_from_result(result: RunResult, replication: int = 1) -> list[Order]:
    """Orders placed in one validation replication, in lane and day order."""
    if not 1 <= replication <= result.settings.replications:
        raise InputError(f"replication must be between 1 and {result.settings.replications}")
    lanes = {lane.key: lane for lane in result.lanes}
    found = []
    for lane_result in result.results:
        lane = lanes[lane_result.lane_key]
        for period in lane_result.validation_trials[replication - 1].periods:
            if period.ordered_kg > 1e-9:
                found.append(
                    Order(
                        lane.key,
                        period.day,
                        period.ordered_kg,
                        lane.delivery_cost_per_order,
                        lane.holding_cost_per_kg_day,
                    )
                )
    return sorted(found, key=lambda order: (order.lane, order.day))


def consolidate_orders(orders: list[Order], window: int) -> list[dict]:
    """Group each lane's orders placed within ``window`` days of a group's first order.

    Each group becomes one delivery on its first day. Returns one row per lane with orders
    and deliveries, delivered kg, delivery cost before and after, the extra holding cost of
    receiving later orders early, and the net saving (USD).
    """
    by_lane: dict[str, list[Order]] = {}
    for order in orders:
        by_lane.setdefault(order.lane, []).append(order)
    rows = []
    for lane in sorted(by_lane):
        lane_orders = sorted(by_lane[lane], key=lambda order: order.day)
        groups = []
        i = 0
        while i < len(lane_orders):
            start = lane_orders[i].day
            group = []
            j = i
            while j < len(lane_orders) and lane_orders[j].day < start + window:
                group.append(lane_orders[j])
                j += 1
            groups.append(group)
            i = j
        orders = {
            "count": len(lane_orders),
            "kg": sum(order.quantity_kg for order in lane_orders),
            "before": sum(order.delivery_cost for order in lane_orders),
            "after": sum(group[0].delivery_cost for group in groups),
            "early_kg_days": sum(
                order.quantity_kg * (order.day - group[0].day)
                for group in groups
                for order in group
            ),
        }
        extra_holding = orders["early_kg_days"] * lane_orders[0].holding_cost_per_kg_day
        saving = orders["before"] - orders["after"] - extra_holding
        rows.append(
            {
                "lane": lane,
                "orders": orders["count"],
                "deliveries": len(groups),
                "delivered_kg": round(orders["kg"], 1),
                "delivery_cost_before": round(orders["before"], 2),
                "delivery_cost_after": round(orders["after"], 2),
                "extra_holding_cost": round(extra_holding, 2),
                "net_saving": round(saving, 2),
            }
        )
    return rows


def totals(rows: list[dict]) -> dict:
    """Portfolio totals of orders, deliveries, delivery cost and net saving (USD)."""
    return {
        "orders": sum(row["orders"] for row in rows),
        "deliveries": sum(row["deliveries"] for row in rows),
        "delivery_cost_before": sum(row["delivery_cost_before"] for row in rows),
        "delivery_cost_after": sum(row["delivery_cost_after"] for row in rows),
        "net_saving": sum(row["net_saving"] for row in rows),
    }


def write_batching(rows: list[dict], output: str | Path) -> Path:
    """Write batching.csv to the output folder and return its path."""
    folder = Path(output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "batching.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=ROW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def compare_windows(orders: list[Order], windows: list[int]) -> list[dict]:
    """Portfolio totals for each candidate window, so the trade-off can be read in one table."""
    if not windows:
        raise InputError("Give at least one window")
    rows = []
    for days in sorted(set(windows)):
        total = totals(consolidate_orders(orders, days))
        rows.append({"window_days": days, **total})
    return rows


def best_windows(orders: list[Order], windows: list[int]) -> dict[str, int]:
    """For each lane, the window with the largest net saving (ties go to the shorter window).

    A lane where no window saves money keeps the shortest window given.
    """
    if not windows:
        raise InputError("Give at least one window")
    best: dict[str, tuple[float, int]] = {}
    for days in sorted(set(windows)):
        for row in consolidate_orders(orders, days):
            current = best.get(row["lane"])
            if current is None or row["net_saving"] > current[0]:
                best[row["lane"]] = (row["net_saving"], days)
    return {lane: days for lane, (_, days) in sorted(best.items())}
