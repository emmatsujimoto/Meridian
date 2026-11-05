"""Policy comparison and separate deterministic replenishment benchmarks."""

from dataclasses import replace
from math import ceil, sqrt
from statistics import fmean

from meridian.demand import demand_traces
from meridian.disruptions import (
    fixed_outage,
    outage_schedule,
    recovery_days,
    simulate_disrupted,
)
from meridian.engine import simulate_lane
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


def _trial(lane: Lane, settings: Settings, level: float, trace, phase: str, replication: int):
    """One simulated replication, with supplier outages when the scenario enables them."""
    if not settings.supplier_disruptions:
        return simulate_lane(lane, level, trace)
    _, offline = outage_schedule(settings, lane, phase, replication)
    return simulate_disrupted(lane, level, trace, offline)


def optimize_lane(lane: Lane, settings: Settings) -> LaneResult:
    training = demand_traces(lane, settings, "training")
    candidates = []
    for level in candidate_levels(lane, settings):
        trials = [
            _trial(lane, settings, level, trace, "training", index)
            for index, trace in enumerate(training)
        ]
        fill = fmean(t.fill_rate for t in trials)
        candidates.append(
            Candidate(
                level, fmean(t.total_cost for t in trials), fill, fill >= settings.service_target
            )
        )
    chosen = choose_candidate(tuple(candidates))
    validation = tuple(
        _trial(lane, settings, chosen.base_stock_kg, trace, "validation", index)
        for index, trace in enumerate(demand_traces(lane, settings, "validation"))
    )
    return LaneResult(
        lane.key, chosen.base_stock_kg, chosen.meets_target, tuple(candidates), validation
    )


def disruption_impact(lanes: tuple[Lane, ...], settings: Settings) -> list[dict]:
    """Each lane's chosen policy and results with and without supplier outages.

    Both runs use the same demand samples, so differences come from the outages and from
    any change in the chosen stock level. ``cost_increase`` is disrupted minus
    undisrupted validation mean cost.
    """
    calm = run_scenario(lanes, replace(settings, supplier_disruptions=False))
    stormy = run_scenario(lanes, replace(settings, supplier_disruptions=True))
    rows = []
    for plain, outaged in zip(calm.results, stormy.results, strict=True):
        plain_cost = fmean(t.total_cost for t in plain.validation_trials)
        outaged_cost = fmean(t.total_cost for t in outaged.validation_trials)
        rows.append(
            {
                "lane": plain.lane_key,
                "base_stock_kg": plain.chosen_base_stock_kg,
                "base_stock_with_outages_kg": outaged.chosen_base_stock_kg,
                "mean_cost": plain_cost,
                "mean_cost_with_outages": outaged_cost,
                "cost_increase": outaged_cost - plain_cost,
                "fill_rate": fmean(t.fill_rate for t in plain.validation_trials),
                "fill_rate_with_outages": fmean(t.fill_rate for t in outaged.validation_trials),
                "target_met_with_outages": outaged.training_target_met,
            }
        )
    return rows


def outage_stress_test(
    lane: Lane,
    settings: Settings,
    base_stock_kg: float,
    outage_lengths: tuple[int, ...],
    start_day: int,
) -> list[dict]:
    """Validation results of one stock level against a single outage of each length.

    The outage starts on the same one-based day in every replication, so the results show
    how long an outage the stock level can absorb without random timing.
    """
    if not outage_lengths or len(outage_lengths) > 20:
        raise InputError("Provide 1-20 outage lengths")
    traces = demand_traces(lane, settings, "validation")
    rows = []
    for length in sorted(set(outage_lengths)):
        offline = fixed_outage(start_day, length, settings.horizon_days)
        trials = [simulate_disrupted(lane, base_stock_kg, trace, offline) for trace in traces]
        recoveries = [max(recovery_days(t, offline), default=0) for t in trials]
        rows.append(
            {
                "outage_days": length,
                "start_day": start_day,
                "mean_fill_rate": fmean(t.fill_rate for t in trials),
                "mean_cost": fmean(t.total_cost for t in trials),
                "max_backlog_kg": max(max(p.backlog_kg for p in t.periods) for t in trials),
                "mean_recovery_days": fmean(recoveries),
            }
        )
    return rows


def stock_for_outage(lane: Lane, settings: Settings, outage_days: int, start_day: int = 1) -> dict:
    """The lowest candidate stock level whose validation fill rate meets the service target
    despite a single outage of ``outage_days`` starting on ``start_day``.

    Candidates are the scenario's usual grid, extended with doubled levels so that long
    outages can still be covered. ``base_stock_kg`` is None when no candidate is enough.
    """
    levels = candidate_levels(lane, settings)
    levels = tuple(sorted(set(levels) | {level * 2 for level in levels}))
    tested = []
    for level in levels:
        row = outage_stress_test(lane, settings, level, (outage_days,), start_day)[0]
        tested.append({"base_stock_kg": level, "mean_fill_rate": row["mean_fill_rate"]})
        if row["mean_fill_rate"] >= settings.service_target:
            return {
                "lane": lane.key,
                "outage_days": outage_days,
                "base_stock_kg": level,
                "mean_fill_rate": row["mean_fill_rate"],
                "tested": tested,
            }
    return {
        "lane": lane.key,
        "outage_days": outage_days,
        "base_stock_kg": None,
        "mean_fill_rate": None,
        "tested": tested,
    }


def impact_table(rows: list[dict]) -> str:
    """A Markdown table of ``disruption_impact`` rows."""
    lines = [
        "| Product-location | Stock (kg) | Stock with outages (kg) | Cost | Cost with outages "
        "| Increase | Fill rate | Fill rate with outages |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['lane']} | {row['base_stock_kg']:,.0f} "
            f"| {row['base_stock_with_outages_kg']:,.0f} | {row['mean_cost']:,.2f} "
            f"| {row['mean_cost_with_outages']:,.2f} | {row['cost_increase']:+,.2f} "
            f"| {row['fill_rate']:.2%} | {row['fill_rate_with_outages']:.2%} |"
        )
    return "\n".join(lines) + "\n"


def stress_table(rows: list[dict]) -> str:
    """A Markdown table of ``outage_stress_test`` rows."""
    lines = [
        "| Outage (days) | Start day | Fill rate | Cost | Max backlog (kg) | Recovery (days) |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['outage_days']} | {row['start_day']} | {row['mean_fill_rate']:.2%} "
            f"| {row['mean_cost']:,.2f} | {row['max_backlog_kg']:,.0f} "
            f"| {row['mean_recovery_days']:.1f} |"
        )
    return "\n".join(lines) + "\n"


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
