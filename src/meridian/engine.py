"""Stockpyl adapter for independent bulk-product inventory streams."""

from math import ceil, exp, log, sqrt
from statistics import NormalDist
from threading import Lock

import numpy as np

from meridian.models import InputError, Lane, PeriodResult, Trial, number
from stockpyl.sim import simulation
from stockpyl.supply_chain_network import single_stage_system

_SIMULATION_LOCK = Lock()


def simulate_lane(lane: Lane, base_stock_kg: float, demands: tuple[float, ...]) -> Trial:
    """Run daily base-stock ordering using deterministic externally sampled demand.

    Stockpyl's event sequence includes observing today's demand before ordering.
    Demand not immediately served remains backlogged, not lost or emergency supplied.
    Procurement and delivery costs are charged when an order is placed. No terminal
    salvage value is applied. These conventions are explicit modeling assumptions.
    """
    base_stock_kg = number(base_stock_kg, "base_stock_kg")
    if not demands or len(demands) > 366:
        raise InputError("demands must contain 1-366 daily values")
    demands = tuple(number(x, "daily demand") for x in demands)
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


LEAD_TIME_CAP_PROBABILITY = 0.999


def _lead_time_cap(mean_days: int, cv: float) -> int:
    """Longest lead time (days) simulated: the lognormal 99.9th percentile, rounded up.

    Caps rare extreme samples so a single order cannot stay in transit for most of a run.
    """
    if mean_days == 0:
        return 0
    sigma_sq = log(1 + 1 / (1 / cv) ** 2)
    mu = log(mean_days) - sigma_sq / 2
    return ceil(exp(mu + sqrt(sigma_sq) * NormalDist().inv_cdf(LEAD_TIME_CAP_PROBABILITY)))


def simulate_lane_variable(
    lane: Lane,
    base_stock_kg: float,
    demands: tuple[float, ...],
    lead_times: tuple[int, ...],
    lead_time_cv: float,
) -> Trial:
    """Daily base-stock simulation in which every order has its own lead time.

    Follows the same event order and cost conventions as simulate_lane: today's demand is
    observed, an order restores the inventory position to the base stock, shipments due
    today or earlier are received, demand is served and end-of-day costs are charged.
    With every lead time equal to the lane's lead time, results match simulate_lane.
    """
    base_stock_kg = number(base_stock_kg, "base_stock_kg")
    if not demands or len(demands) > 366:
        raise InputError("demands must contain 1-366 daily values")
    if len(lead_times) != len(demands):
        raise InputError("lead_times must contain one value per simulated day")
    demands = tuple(number(x, "daily demand") for x in demands)
    cap = _lead_time_cap(lane.lead_time_days, lead_time_cv)
    inventory_level = lane.initial_inventory_kg
    pipeline: dict[int, float] = {}
    order_lead_times = []
    periods = []
    for day, (demand, lead_time) in enumerate(zip(demands, lead_times)):
        position = inventory_level + sum(pipeline.values()) - demand
        ordered = max(0.0, base_stock_kg - position)
        if ordered > 1e-9:
            effective = min(int(lead_time), cap)
            due = day + effective
            pipeline[due] = pipeline.get(due, 0.0) + ordered
            order_lead_times.append((day + 1, effective))
        else:
            ordered = 0.0
        received = sum(pipeline.pop(due) for due in sorted(d for d in pipeline if d <= day))
        served = min(demand, max(0.0, inventory_level + received))
        inventory_level += received - demand
        periods.append(
            PeriodResult(
                day=day + 1,
                demand_kg=demand,
                inventory_kg=max(0.0, inventory_level),
                backlog_kg=max(0.0, -inventory_level),
                ordered_kg=ordered,
                served_immediately_kg=served,
                holding_cost=lane.holding_cost_per_kg_day * max(0.0, inventory_level),
                backlog_cost=lane.backlog_cost_per_kg_day * max(0.0, -inventory_level),
                delivery_cost=lane.delivery_cost_per_order if ordered > 1e-9 else 0.0,
                purchase_cost=ordered * lane.purchase_cost_per_kg,
            )
        )
    return Trial(lane.key, base_stock_kg, tuple(periods), tuple(order_lead_times))
