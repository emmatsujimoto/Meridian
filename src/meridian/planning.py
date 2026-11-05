"""Policy comparison and separate deterministic replenishment benchmarks."""

from math import ceil, sqrt
from statistics import fmean

from meridian.demand import demand_traces
from meridian.engine import capacity_summary, simulate_lane
from meridian.models import Candidate, InputError, Lane, LaneResult, RunResult, Settings, number
from stockpyl.eoq import economic_order_quantity
from stockpyl.newsvendor import newsvendor_normal
from stockpyl.wagner_whitin import wagner_whitin


def candidate_levels(lane: Lane, settings: Settings) -> tuple[float, ...]:
    """Use a normal lead-time approximation only to center the candidate grid.

    The simulation, not this approximation, evaluates nonnegative lognormal demand.
    No claim of globally optimal or capacity-feasible real-world scheduling is made.
    """
    protection = max(1, lane.lead_time_days + 1)
    mean = lane.daily_mean_kg * settings.demand_multiplier * protection
    sd = lane.daily_sd_kg * settings.demand_multiplier * sqrt(protection)
    if sd:
        center, _ = newsvendor_normal(
            lane.holding_cost_per_kg_day,
            lane.backlog_cost_per_kg_day,
            mean,
            sd,
        )
        center = max(mean, float(center))
    else:
        center = mean
    return tuple(sorted({float(ceil(center * m)) for m in settings.stock_multipliers}))


def choose_candidate(candidates: tuple[Candidate, ...]) -> Candidate:
    if not candidates:
        raise InputError("At least one candidate is required")
    feasible = [c for c in candidates if c.meets_target]
    if feasible:
        return min(feasible, key=lambda c: (c.mean_cost, c.base_stock_kg))
    # Explicit fallback: highest service first, then lowest cost. Flag unmet target.
    return min(candidates, key=lambda c: (-c.mean_fill_rate, c.mean_cost, c.base_stock_kg))


def optimize_lane(lane: Lane, settings: Settings) -> LaneResult:
    training = demand_traces(lane, settings, "training")
    candidates = []
    for level in candidate_levels(lane, settings):
        trials = [
            simulate_lane(lane, level, trace, settings.enforce_capacity) for trace in training
        ]
        fill = fmean(t.fill_rate for t in trials)
        candidates.append(
            Candidate(
                level, fmean(t.total_cost for t in trials), fill, fill >= settings.service_target
            )
        )
    chosen = choose_candidate(tuple(candidates))
    validation = tuple(
        simulate_lane(lane, chosen.base_stock_kg, trace, settings.enforce_capacity)
        for trace in demand_traces(lane, settings, "validation")
    )
    return LaneResult(
        lane.key, chosen.base_stock_kg, chosen.meets_target, tuple(candidates), validation
    )


def run_scenario(lanes: tuple[Lane, ...], settings: Settings) -> RunResult:
    if not lanes or len(lanes) > 100:
        raise InputError("A scenario needs 1-100 product-location rows")
    if len({lane.key for lane in lanes}) != len(lanes):
        raise InputError("Duplicate product-location rows")
    lanes = tuple(sorted(lanes, key=lambda x: x.key))
    return RunResult(settings, lanes, tuple(optimize_lane(lane, settings) for lane in lanes))


def eoq_benchmark(lane: Lane, multiplier: float = 1.0) -> dict:
    multiplier = number(multiplier, "multiplier", strict=True)
    if lane.delivery_cost_per_order == 0:
        return {
            "lane": lane.key,
            "quantity_kg": 0.0,
            "daily_cycle_cost": 0.0,
            "interpretation": "Zero setup cost: continuous-replenishment limiting benchmark",
        }
    quantity, cost = economic_order_quantity(
        lane.delivery_cost_per_order,
        lane.holding_cost_per_kg_day,
        lane.daily_mean_kg * multiplier,
    )
    return {
        "lane": lane.key,
        "quantity_kg": float(quantity),
        "daily_cycle_cost": float(cost),
        "interpretation": "Steady-demand benchmark; excludes procurement, shortages and lead time",
    }


def deterministic_plan(lane: Lane, demands: tuple[float, ...]) -> dict:
    """Wagner-Whitin benchmark: zero initial stock, same-day arrivals, no capacity.

    This is a separate full-information benchmark, not a forecast or live dispatch plan.
    """
    if not demands or len(demands) > 366:
        raise InputError("demands must contain 1-366 days")
    demand = [number(x, "demand") for x in demands]
    quantities, cost, _, _ = wagner_whitin(
        len(demand),
        lane.holding_cost_per_kg_day,
        lane.delivery_cost_per_order,
        demand,
        lane.purchase_cost_per_kg,
    )
    return {
        "lane": lane.key,
        "order_quantities_kg": [float(q) for q in quantities[1:]],
        "total_cost": float(cost),
        "assumptions": "Zero initial stock; zero lead time; known demand; no capacity limits",
    }


def capacity_report(result: RunResult) -> list[dict]:
    """Storage use of each lane's chosen policy on the validation samples.

    Lanes without a recorded capacity are left out. ``base_stock_above_capacity`` flags
    chosen base-stock levels the site could never hold in full.
    """
    lanes = {lane.key: lane for lane in result.lanes}
    rows = []
    for lane_result in result.results:
        lane = lanes[lane_result.lane_key]
        if lane.storage_capacity_kg is None:
            continue
        row = capacity_summary(lane, lane_result.validation_trials)
        row["base_stock_kg"] = lane_result.chosen_base_stock_kg
        row["base_stock_above_capacity"] = (
            lane_result.chosen_base_stock_kg > lane.storage_capacity_kg
        )
        row["capacity_enforced"] = result.settings.enforce_capacity
        rows.append(row)
    return rows
