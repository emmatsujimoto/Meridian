"""Policy comparison and separate deterministic replenishment benchmarks."""

from dataclasses import replace
from math import ceil, sqrt
from statistics import fmean, pstdev

from meridian.demand import demand_traces
from meridian.engine import simulate_lane
from meridian.models import (
    Candidate,
    InputError,
    Lane,
    LaneResult,
    PeriodResult,
    RunResult,
    Settings,
    Trial,
    number,
)
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
        trials = [simulate_lane(lane, level, trace) for trace in training]
        fill = fmean(t.fill_rate for t in trials)
        candidates.append(
            Candidate(
                level, fmean(t.total_cost for t in trials), fill, fill >= settings.service_target
            )
        )
    chosen = choose_candidate(tuple(candidates))
    validation = tuple(
        simulate_lane(lane, chosen.base_stock_kg, trace)
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


FORECAST_WINDOW_DAYS = 14
REPLAN_SAMPLES = 12


def forecast(history: list[float], lane: Lane, settings: Settings) -> tuple[float, float]:
    """Mean and SD of daily demand (kg) from recent history.

    Falls back to the lane's configured demand (times the scenario multiplier) until at least
    three days of history exist.
    """
    if len(history) < 3:
        return (
            lane.daily_mean_kg * settings.demand_multiplier,
            lane.daily_sd_kg * settings.demand_multiplier,
        )
    return fmean(history), pstdev(history)


def replan_level(lane: Lane, settings: Settings, mean_kg: float, sd_kg: float, seed: int) -> float:
    """Base stock (kg) for the coming period, chosen by simulating the candidate grid.

    Candidates come from the same newsvendor-centred grid as the static policy, using the
    forecast mean and SD. Each candidate is simulated on REPLAN_SAMPLES synthetic traces drawn
    from the forecast, and the cheapest one that meets the service target is chosen.
    """
    forecast_lane = replace(
        lane,
        daily_mean_kg=max(mean_kg, 1e-6),
        daily_sd_kg=sd_kg,
    )
    trial_settings = replace(
        settings,
        demand_multiplier=1.0,
        replications=REPLAN_SAMPLES,
        horizon_days=max(lane.lead_time_days + 1, 7) * 2,
        seed=seed,
    )
    traces = demand_traces(forecast_lane, trial_settings, "training")
    candidates = []
    for level in candidate_levels(forecast_lane, trial_settings):
        trials = [simulate_lane(forecast_lane, level, trace) for trace in traces]
        fill = fmean(t.fill_rate for t in trials)
        candidates.append(
            Candidate(
                level, fmean(t.total_cost for t in trials), fill, fill >= settings.service_target
            )
        )
    return choose_candidate(tuple(candidates)).base_stock_kg


def rolling_plan(
    lane: Lane,
    settings: Settings,
    demands: tuple[float, ...],
    review_period_days: int = 7,
    verbose: bool = False,
) -> tuple[Trial, list[dict]]:
    """Simulate one demand trace while re-optimising base stock once per review period.

    At the start of each review period the policy forecasts demand from the most recent
    FORECAST_WINDOW_DAYS days and re-optimises the base stock for that period. Event order
    and cost conventions match simulate_lane. Returns the trial and the plan changes.
    """
    review_period_days = int(number(review_period_days, "review_period_days", strict=True))
    if review_period_days > 90:
        raise InputError("review_period_days must be between 1 and 90")
    if not demands or len(demands) > 366:
        raise InputError("demands must contain 1-366 daily values")
    demands = tuple(number(x, "daily demand") for x in demands)
    inventory_level = lane.initial_inventory_kg
    pipeline: dict[int, float] = {}
    periods = []
    plan = []
    base_stock_kg = 0.0
    for day, demand in enumerate(demands):
        start = max(0, day + review_period_days - FORECAST_WINDOW_DAYS)
        mean_kg, sd_kg = forecast(list(demands[start : day + review_period_days]), lane, settings)
        base_stock_kg = replan_level(lane, settings, mean_kg, sd_kg, (settings.seed + day) % 2**32)
        plan.append(
            {
                "lane": lane.key,
                "day": day + 1,
                "forecast_mean_kg": mean_kg,
                "forecast_sd_kg": sd_kg,
                "base_stock_kg": base_stock_kg,
            }
        )
        position = inventory_level + sum(pipeline.values()) - demand
        ordered = max(0.0, base_stock_kg - position)
        if ordered > 1e-9:
            due = day + lane.lead_time_days
            pipeline[due] = pipeline.get(due, 0.0) + ordered
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
    return Trial(lane.key, base_stock_kg, tuple(periods)), plan


def compare_rolling(
    lanes: tuple[Lane, ...], settings: Settings, review_period_days: int = 7
) -> list[dict]:
    """Static base stock versus rolling re-planning on the same validation traces, per lane."""
    static = run_scenario(lanes, settings)
    rows = []
    for lane, lane_result in zip(static.lanes, static.results):
        traces = demand_traces(lane, settings, "validation")
        rolling = [rolling_plan(lane, settings, trace, review_period_days)[0] for trace in traces]
        rows.append(
            {
                "lane": lane.key,
                "static_base_stock_kg": lane_result.chosen_base_stock_kg,
                "static_mean_cost": fmean(t.total_cost for t in lane_result.validation_trials),
                "static_fill_rate": fmean(t.fill_rate for t in lane_result.validation_trials),
                "rolling_mean_cost": fmean(t.total_cost for t in rolling),
                "rolling_fill_rate": fmean(t.fill_rate for t in rolling),
            }
        )
    return rows


def rolling_schedule(
    lanes: tuple[Lane, ...], settings: Settings, review_period_days: int = 7, replication: int = 1
) -> list[dict]:
    """The base stock in force each day for every lane, for one validation replication.

    Rows carry the forecast behind each level, so planners can see how the level moved.
    """
    if not 1 <= replication <= settings.replications:
        raise InputError(f"replication must be between 1 and {settings.replications}")
    rows = []
    for lane in sorted(lanes, key=lambda x: x.key):
        trace = demand_traces(lane, settings, "validation")[replication - 1]
        _, plan = rolling_plan(lane, settings, trace, review_period_days)
        rows.extend(plan)
    return rows


def level_changes(schedule: list[dict]) -> list[dict]:
    """Only the schedule rows where a lane's base stock differs from its previous day."""
    changes = []
    previous: dict[str, float] = {}
    for row in schedule:
        if previous.get(row["lane"]) != row["base_stock_kg"]:
            changes.append(row)
        previous[row["lane"]] = row["base_stock_kg"]
    return changes
