"""Stockpyl adapter for independent bulk-product inventory streams."""

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
    periods = tuple(
        _period_row(lane, node.state_vars[day], product, day + 1, demand)
        for day, demand in enumerate(demands)
    )
    return Trial(lane.key, base_stock_kg, periods)


def _period_row(lane: Lane, sv, product, day: int, demand: float) -> PeriodResult:
    """Convert one day of simulator state into a PeriodResult (kg and USD)."""
    inventory = float(sv.inventory_level[product])
    ordered = float(sv.order_quantity_fg[product])
    return PeriodResult(
        day=day,
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
