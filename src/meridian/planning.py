"""Policy comparison and separate deterministic replenishment benchmarks."""

from dataclasses import replace
from math import ceil, sqrt
from statistics import fmean

from meridian.demand import demand_traces
from meridian.engine import simulate_lane, simulate_lane_variable
from meridian.leadtime import lead_time_sd, lead_time_traces
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
    daily_mean = lane.daily_mean_kg * settings.demand_multiplier
    daily_sd = lane.daily_sd_kg * settings.demand_multiplier
    mean = daily_mean * protection
    # Variable lead times add demand-over-lead-time variance: mean^2 x lead-time variance.
    sd = sqrt(daily_sd**2 * protection + (daily_mean * lead_time_sd(lane, settings)) ** 2)
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


def _simulate_phase(lane: Lane, settings: Settings, level: float, phase: str, traces) -> list:
    """Simulate one base-stock level over a phase's demand traces, with fixed or variable lead
    times as the scenario specifies."""
    if settings.lead_time_cv is None:
        return [simulate_lane(lane, level, trace) for trace in traces]
    lead_times = lead_time_traces(lane, settings, phase)
    return [
        simulate_lane_variable(lane, level, trace, lead, settings.lead_time_cv)
        for trace, lead in zip(traces, lead_times)
    ]


def optimize_lane(lane: Lane, settings: Settings) -> LaneResult:
    training = demand_traces(lane, settings, "training")
    candidates = []
    for level in candidate_levels(lane, settings):
        trials = _simulate_phase(lane, settings, level, "training", training)
        fill = fmean(t.fill_rate for t in trials)
        candidates.append(
            Candidate(
                level, fmean(t.total_cost for t in trials), fill, fill >= settings.service_target
            )
        )
    chosen = choose_candidate(tuple(candidates))
    validation = tuple(
        _simulate_phase(
            lane,
            settings,
            chosen.base_stock_kg,
            "validation",
            demand_traces(lane, settings, "validation"),
        )
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


def lead_time_sensitivity(
    lanes: tuple[Lane, ...], settings: Settings, cvs: tuple[float, ...]
) -> list[dict]:
    """Re-run the scenario for each lead-time CV and report validation cost and service.

    Each CV is a complete scenario run with the same seed, so differences come from lead-time
    variability alone. A CV of None means fixed lead times.
    """
    if not cvs or len(cvs) > 10:
        raise InputError("Give 1-10 lead-time CVs to compare")
    rows = []
    for cv in cvs:
        result = run_scenario(lanes, replace(settings, lead_time_cv=cv))
        trials = [t for lr in result.results for t in lr.validation_trials]
        demand = sum(p.demand_kg for t in trials for p in t.periods)
        served = sum(p.served_immediately_kg for t in trials for p in t.periods)
        rows.append(
            {
                "lead_time_cv": cv,
                "mean_total_cost": sum(
                    fmean(t.total_cost for t in lr.validation_trials) for lr in result.results
                ),
                "portfolio_fill_rate": served / demand if demand else 1.0,
                "total_base_stock_kg": sum(lr.chosen_base_stock_kg for lr in result.results),
            }
        )
    return rows
