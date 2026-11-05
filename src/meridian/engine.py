"""Stockpyl adapter for independent bulk-product inventory streams."""

from threading import Lock

import numpy as np

from meridian.models import InputError, Lane, PeriodResult, Trial, number
from stockpyl.sim import simulation
from stockpyl.supply_chain_network import single_stage_system

_SIMULATION_LOCK = Lock()


def simulate_lane(
    lane: Lane, base_stock_kg: float, demands: tuple[float, ...], enforce_capacity: bool = False
) -> Trial:
    """Run daily base-stock ordering using deterministic externally sampled demand.

    Stockpyl's event sequence includes observing today's demand before ordering.
    Demand not immediately served remains backlogged, not lost or emergency supplied.
    Procurement and delivery costs are charged when an order is placed. No terminal
    salvage value is applied. These conventions are explicit modeling assumptions.

    With ``enforce_capacity``, a delivery that would take the site above its storage
    capacity stays at the supplier until space is available.
    """
    base_stock_kg = number(base_stock_kg, "base_stock_kg")
    if not demands or len(demands) > 366:
        raise InputError("demands must contain 1-366 daily values")
    demands = tuple(number(x, "daily demand") for x in demands)
    if enforce_capacity:
        # Stockpyl's base-stock node has no storage limit, so capacity runs use the same
        # event order in a daily loop: observe demand, order, receive, then serve.
        capacity = float(lane.storage_capacity_kg or 0.0)
        on_hand = lane.initial_inventory_kg
        pipeline: dict[int, float] = {}
        periods = []
        for day, demand in enumerate(demands):
            position = on_hand + sum(pipeline.values()) - demand
            ordered = max(0.0, base_stock_kg - position)
            if ordered <= 1e-9:
                ordered = 0.0
            else:
                due = day + lane.lead_time_days
                pipeline[due] = pipeline.get(due, 0.0) + ordered
            arriving = pipeline.pop(day, 0.0)
            space = max(0.0, capacity - on_hand)
            on_hand += min(arriving, space)
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
        return Trial(lane.key, base_stock_kg, tuple(periods))
    network = single_stage_system(
        index=0,
        local_holding_cost=lane.holding_cost_per_kg_day,
        stockout_cost=lane.backlog_cost_per_kg_day,
        shipment_lead_time=lane.lead_time_days,
        order_lead_time=0,
        demand_type="D",
        demand_list=list(demands),
        policy_type="BS",
        base_stock_level=base_stock_kg,
        initial_inventory_level=lane.initial_inventory_kg,
    )
    # The upstream simulator seeds numpy's legacy RNG. Preserve caller state and
    # serialize calls through this adapter; demand itself uses isolated generators.
    with _SIMULATION_LOCK:
        state = np.random.get_state()
        try:
            simulation(
                network, len(demands), rand_seed=0, progress_bar=False, consistency_checks="E"
            )
        finally:
            np.random.set_state(state)
    node = network.nodes[0]
    product = node.product_indices[0]
    periods = []
    for day, demand in enumerate(demands):
        sv = node.state_vars[day]
        inventory = float(sv.inventory_level[product])
        ordered = float(sv.order_quantity_fg[product])
        periods.append(
            PeriodResult(
                day=day + 1,
                demand_kg=demand,
                inventory_kg=max(0.0, inventory),
                backlog_kg=max(0.0, -inventory),
                ordered_kg=ordered,
                served_immediately_kg=float(sv.demand_met_from_stock[product]),
                holding_cost=float(sv.holding_cost_incurred),
                backlog_cost=float(sv.stockout_cost_incurred),
                delivery_cost=lane.delivery_cost_per_order if ordered > 1e-9 else 0.0,
                purchase_cost=ordered * lane.purchase_cost_per_kg,
            )
        )
    return Trial(lane.key, base_stock_kg, tuple(periods))


def capacity_utilisation(lane: Lane, trial: Trial) -> float:
    """Peak end-of-day inventory as a share of the site's storage capacity."""
    capacity = lane.storage_capacity_kg if lane.storage_capacity_kg is not None else 50000.0
    return max(period.inventory_kg for period in trial.periods) / capacity


def days_at_capacity(lane: Lane, trial: Trial, tolerance_kg: float = 1e-6) -> int:
    """Days on which end-of-day inventory filled the site's recorded capacity."""
    if lane.storage_capacity_kg is None:
        return 0
    limit = lane.storage_capacity_kg - tolerance_kg
    return sum(period.inventory_kg >= limit for period in trial.periods)


def capacity_summary(lane: Lane, trials: tuple[Trial, ...]) -> dict:
    """Peak utilisation and days at capacity across a lane's trials.

    ``mean_*`` values average over trials; ``max_peak_utilisation`` is the highest single
    trial, so a value of one means at least one trial filled the site.
    """
    if not trials:
        raise InputError("At least one trial is required")
    peaks = [capacity_utilisation(lane, trial) for trial in trials]
    full_days = [days_at_capacity(lane, trial) for trial in trials]
    return {
        "lane": lane.key,
        "storage_capacity_kg": lane.storage_capacity_kg,
        "mean_peak_utilisation": sum(peaks) / len(peaks),
        "max_peak_utilisation": max(peaks),
        "mean_days_at_capacity": sum(full_days) / len(full_days),
        "trials": len(trials),
    }
