"""Policy comparison and separate deterministic replenishment benchmarks."""

from dataclasses import replace
from math import ceil, sqrt
from statistics import fmean

from meridian.demand import demand_traces
from meridian.engine import simulate_lane
from meridian.models import Candidate, InputError, Lane, LaneResult, RunResult, Settings, number
from meridian.policies import simulate_periodic
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


def periodic_levels(lane: Lane, settings: Settings) -> tuple[tuple[float, float], ...]:
    """(reorder point, order-up-to level) pairs to try for a periodic-review policy.

    The order-up-to grid is centred like the base-stock grid, but protects demand over the
    review period plus the lead time. Each level is paired with reorder points at the
    configured fractions of it; a fraction of 1 reorders at every review that finds the
    position below S.
    """
    protection = lane.lead_time_days + settings.review_period_days
    mean = lane.daily_mean_kg * settings.demand_multiplier * protection
    sd = lane.daily_sd_kg * settings.demand_multiplier * sqrt(protection)
    if sd:
        center, _ = newsvendor_normal(
            lane.holding_cost_per_kg_day, lane.backlog_cost_per_kg_day, mean, sd
        )
        center = max(mean, float(center))
    else:
        center = mean
    levels = sorted({float(ceil(center * m)) for m in settings.stock_multipliers})
    return tuple(
        sorted(
            {
                (float(ceil(level * f)), level)
                for level in levels
                for f in settings.reorder_fractions
            }
        )
    )


def choose_candidate(candidates: tuple[Candidate, ...]) -> Candidate:
    if not candidates:
        raise InputError("At least one candidate is required")
    feasible = [c for c in candidates if c.meets_target]
    if feasible:
        return min(feasible, key=lambda c: (c.mean_cost, c.base_stock_kg))
    # Explicit fallback: highest service first, then lowest cost. Flag unmet target.
    return min(candidates, key=lambda c: (-c.mean_fill_rate, c.mean_cost, c.base_stock_kg))


def _periodic_trial(lane: Lane, settings: Settings, reorder_kg: float, level: float, trace):
    """One periodic-review trial with the scenario's review period and pack size."""
    return simulate_periodic(
        lane, settings.review_period_days, reorder_kg, level, trace, settings.pack_size_kg
    )


def optimize_periodic_lane(lane: Lane, settings: Settings) -> LaneResult:
    """Choose (s, S) on training demand and evaluate it on validation demand."""
    training = demand_traces(lane, settings, "training")
    candidates = []
    for reorder_kg, level in periodic_levels(lane, settings):
        trials = [_periodic_trial(lane, settings, reorder_kg, level, t) for t in training]
        fill = fmean(t.fill_rate for t in trials)
        candidates.append(
            Candidate(
                level,
                fmean(t.total_cost for t in trials),
                fill,
                fill >= settings.service_target,
                reorder_kg,
            )
        )
    chosen = choose_candidate(tuple(candidates))
    validation = tuple(
        _periodic_trial(lane, settings, chosen.reorder_point_kg, chosen.base_stock_kg, trace)
        for trace in demand_traces(lane, settings, "validation")
    )
    return LaneResult(
        lane.key,
        chosen.base_stock_kg,
        chosen.meets_target,
        tuple(candidates),
        validation,
        chosen.reorder_point_kg,
    )


def optimize_lane(lane: Lane, settings: Settings) -> LaneResult:
    if settings.policy == "periodic-review":
        return optimize_periodic_lane(lane, settings)
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


def compare_policies(lanes: tuple[Lane, ...], settings: Settings) -> list[dict]:
    """Chosen base-stock and periodic-review policies side by side for each lane.

    Both policies are chosen and validated on the same demand samples, so differences
    come from the policy and not from the draws. ``cost_difference`` is periodic-review
    cost minus base-stock cost on validation.
    """
    base = run_scenario(lanes, replace(settings, policy="base-stock"))
    periodic = run_scenario(lanes, replace(settings, policy="periodic-review"))
    rows = []
    for daily, reviewed in zip(base.results, periodic.results, strict=True):
        daily_cost = fmean(t.total_cost for t in daily.validation_trials)
        reviewed_cost = fmean(t.total_cost for t in reviewed.validation_trials)
        rows.append(
            {
                "lane": daily.lane_key,
                "base_stock_kg": daily.chosen_base_stock_kg,
                "base_stock_cost": daily_cost,
                "base_stock_fill_rate": fmean(t.fill_rate for t in daily.validation_trials),
                "review_period_days": settings.review_period_days,
                "reorder_point_kg": reviewed.reorder_point_kg,
                "order_up_to_kg": reviewed.chosen_base_stock_kg,
                "periodic_cost": reviewed_cost,
                "periodic_fill_rate": fmean(t.fill_rate for t in reviewed.validation_trials),
                "cost_difference": reviewed_cost - daily_cost,
            }
        )
    return rows


def review_period_sweep(lane: Lane, settings: Settings, periods: tuple[int, ...]) -> list[dict]:
    """The chosen (s, S) policy and its validation results for each review period."""
    if not periods or len(periods) > 20:
        raise InputError("Provide 1-20 review periods")
    rows = []
    for period in sorted(set(periods)):
        scenario = replace(settings, policy="periodic-review", review_period_days=period)
        result = optimize_periodic_lane(lane, scenario)
        trials = result.validation_trials
        rows.append(
            {
                "review_period_days": period,
                "reorder_point_kg": result.reorder_point_kg,
                "order_up_to_kg": result.chosen_base_stock_kg,
                "training_target_met": result.training_target_met,
                "mean_cost": fmean(t.total_cost for t in trials),
                "mean_fill_rate": fmean(t.fill_rate for t in trials),
                "mean_orders": fmean(sum(p.ordered_kg > 0 for p in t.periods) for t in trials),
            }
        )
    return rows


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
