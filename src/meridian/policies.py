"""Periodic-review (R, s, S) replenishment for one product-location.

Inventory is reviewed every R days. At a review, if the inventory position (on hand plus
on order, minus backlog) is at or below the reorder point s, an order is placed to bring
the position up to the order-up-to level S. Between reviews no orders are placed.

The daily event order matches the base-stock simulation: observe the day's demand,
place any order, receive deliveries that are due, serve demand, then charge end-of-day
holding and backlog costs. Delivery and purchase costs are charged when an order is placed.
"""

from math import floor

from meridian.models import InputError, Lane, PeriodResult, Trial, number


def round_to_pack(quantity_kg: float, pack_size_kg: float) -> float:
    """Express an order in whole packs; a pack size of zero leaves it unrounded."""
    if pack_size_kg <= 0:
        return quantity_kg
    return floor(quantity_kg / pack_size_kg + 1e-9) * pack_size_kg


def is_review_day(day: int, r: int, offset_days: int = 0) -> bool:
    """Whether zero-based ``day`` is a review day for a review period of ``r`` days."""
    return day >= offset_days and (day - offset_days) % r == 0


def simulate_periodic(
    lane: Lane,
    r: int,
    s: float,
    order_up_to_kg: float,
    demands: tuple[float, ...],
    pack_size_kg: float = 0.0,
    offset_days: int = 0,
) -> Trial:
    """Simulate an (R, s, S) policy against externally sampled daily demand.

    ``r`` is the review period, ``s`` the reorder point and ``order_up_to_kg`` the level
    S. The first review is on day ``offset_days`` (zero-based). The returned trial records
    S as its base-stock level so it can be compared with base-stock results.
    """
    if not isinstance(r, int) or not 1 <= r <= 90:
        raise InputError("Review period must be 1-90 days")
    s = number(s, "reorder point")
    order_up_to_kg = number(order_up_to_kg, "order-up-to level")
    if s > order_up_to_kg:
        raise InputError("Reorder point must not exceed the order-up-to level")
    if not isinstance(offset_days, int) or not 0 <= offset_days < r:
        raise InputError("offset_days must be from 0 to one less than the review period")
    if not demands or len(demands) > 366:
        raise InputError("demands must contain 1-366 daily values")
    demands = tuple(number(x, "daily demand") for x in demands)
    pack_size_kg = number(pack_size_kg, "pack_size_kg")

    on_hand = lane.initial_inventory_kg
    pipeline: dict[int, float] = {}
    periods = []
    for day, demand in enumerate(demands):
        ordered = 0.0
        arriving_today = 0.0
        if is_review_day(day, r, offset_days):
            position = on_hand + sum(pipeline.values()) - demand
            if position < s:
                quantity = round_to_pack(order_up_to_kg - position, pack_size_kg)
                if quantity > 1e-9:
                    ordered = quantity
                    if lane.lead_time_days == 0:
                        arriving_today = quantity
                    else:
                        due = day + lane.lead_time_days
                        pipeline[due] = pipeline.get(due, 0.0) + quantity
        on_hand += arriving_today + pipeline.pop(day, 0.0)
        served = min(demand, max(0.0, on_hand))
        on_hand -= demand
        inventory = max(0.0, on_hand)
        backlog = max(0.0, -on_hand)
        periods.append(
            PeriodResult(
                day=day + 1,
                demand_kg=demand,
                inventory_kg=inventory,
                backlog_kg=backlog,
                ordered_kg=ordered,
                served_immediately_kg=served,
                holding_cost=inventory * lane.holding_cost_per_kg_day,
                backlog_cost=backlog * lane.backlog_cost_per_kg_day,
                delivery_cost=lane.delivery_cost_per_order if ordered else 0.0,
                purchase_cost=ordered * lane.purchase_cost_per_kg,
            )
        )
    return Trial(lane.key, order_up_to_kg, tuple(periods))


def review_days(horizon_days: int, r: int, offset_days: int = 0) -> list[int]:
    """One-based days on which reviews happen within the horizon."""
    return [day + 1 for day in range(horizon_days) if is_review_day(day, r, offset_days)]


def order_count(trial: Trial) -> int:
    """Number of orders placed during a trial."""
    return sum(period.ordered_kg > 0 for period in trial.periods)


def mean_order_kg(trial: Trial) -> float:
    """Average size of the orders placed during a trial; zero when none were placed."""
    orders = [period.ordered_kg for period in trial.periods if period.ordered_kg > 0]
    return sum(orders) / len(orders) if orders else 0.0


def days_between_orders(trial: Trial) -> list[int]:
    """Gaps in days between consecutive orders in a trial."""
    order_days = [period.day for period in trial.periods if period.ordered_kg > 0]
    return [later - earlier for earlier, later in zip(order_days, order_days[1:])]


def policy_diagnostics(trial: Trial, review_period_days: int) -> dict:
    """Operational measures of one trial that a planner would check before adopting a policy.

    ``skipped_reviews`` counts review days on which no order was placed.
    """
    reviews = review_days(len(trial.periods), review_period_days)
    ordered_days = {period.day for period in trial.periods if period.ordered_kg > 0}
    gaps = days_between_orders(trial)
    stockout_days = sum(period.backlog_kg > 0 for period in trial.periods)
    return {
        "reviews": len(reviews),
        "orders": len(ordered_days),
        "skipped_reviews": sum(day not in ordered_days for day in reviews),
        "mean_order_kg": mean_order_kg(trial),
        "mean_days_between_orders": sum(gaps) / len(gaps) if gaps else None,
        "stockout_days": stockout_days,
        "peak_inventory_kg": max(period.inventory_kg for period in trial.periods),
    }


def comparison_table(rows: list[dict]) -> str:
    """A Markdown table of base-stock versus periodic-review results per lane."""
    lines = [
        "| Product-location | Base stock (kg) | Base-stock cost | Base-stock fill "
        "| s (kg) | S (kg) | Periodic cost | Periodic fill | Difference |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['lane']} | {row['base_stock_kg']:,.0f} | {row['base_stock_cost']:,.2f} "
            f"| {row['base_stock_fill_rate']:.2%} | {row['reorder_point_kg']:,.0f} "
            f"| {row['order_up_to_kg']:,.0f} | {row['periodic_cost']:,.2f} "
            f"| {row['periodic_fill_rate']:.2%} | {row['cost_difference']:+,.2f} |"
        )
    return "\n".join(lines) + "\n"


def sweep_table(rows: list[dict]) -> str:
    """A Markdown table of a review-period sweep."""
    lines = [
        "| Review period (days) | s (kg) | S (kg) | Target met in training "
        "| Mean cost | Mean fill rate | Orders per replication |",
        "|---:|---:|---:|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['review_period_days']} | {row['reorder_point_kg']:,.0f} "
            f"| {row['order_up_to_kg']:,.0f} | {row['training_target_met']} "
            f"| {row['mean_cost']:,.2f} | {row['mean_fill_rate']:.2%} | {row['mean_orders']:.1f} |"
        )
    return "\n".join(lines) + "\n"
