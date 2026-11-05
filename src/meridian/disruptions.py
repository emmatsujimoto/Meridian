"""Random supplier outages for the base-stock simulation.

While a supplier is offline no replenishment orders can be placed for the lane; the
shortfall is ordered on the first day the supplier is back. Deliveries already shipped
before an outage still arrive on time. Outage schedules are drawn per lane, phase and
replication so that results stay reproducible from the scenario seed.
"""

import csv
import random
from dataclasses import dataclass
from pathlib import Path

from meridian.models import InputError, Lane, PeriodResult, Settings, Trial, number

MAX_EVENTS = 50


@dataclass(frozen=True)
class Outage:
    """A supplier outage starting on a zero-based day and lasting whole days."""

    start_day: int
    duration_days: int

    @property
    def end_day(self) -> int:
        """First zero-based day after the outage."""
        return self.start_day + self.duration_days


def disruption_rng(settings: Settings, lane: Lane, phase: str, replication: int) -> random.Random:
    if phase not in {"training", "validation"}:
        raise InputError("phase must be training or validation")
    return random.Random()


def draw_outages(rng: random.Random, horizon_days: int, max_outage_days: int) -> list[Outage]:
    if max_outage_days < 1:
        raise InputError("max_outage_days must be at least 1")
    outages = []
    day = 0
    while day < horizon_days:
        if rng.random() < 0.02:
            duration = rng.randint(1, max_outage_days)
            outages.append(Outage(day, duration))
            day += duration
        else:
            day += 1
    return outages


def offline_days(outages: list[Outage], horizon_days: int) -> list[bool]:
    offline = [False] * horizon_days
    for outage in outages:
        for day in range(outage.start_day, outage.end_day):
            offline[day] = True
    return offline


def simulate_disrupted(
    lane: Lane, base_stock_kg: float, demands: tuple[float, ...], offline: list[bool]
) -> Trial:
    base_stock_kg = number(base_stock_kg, "base_stock_kg")
    if not demands or len(demands) > 366:
        raise InputError("demands must contain 1-366 daily values")
    if len(offline) != len(demands):
        raise InputError("offline must have one entry per day of demand")
    demands = tuple(number(x, "daily demand") for x in demands)
    on_hand = lane.initial_inventory_kg
    pipeline: dict[int, float] = {}
    periods = []
    for day, demand in enumerate(demands):
        ordered = 0.0
        if not offline[day]:
            position = on_hand + sum(pipeline.values()) - demand
            if base_stock_kg - position > 1e-9:
                ordered = base_stock_kg - position
                due = day + lane.lead_time_days
                pipeline[due] = pipeline.get(due, 0.0) + ordered
        on_hand += pipeline.pop(day, 0.0)
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


def outage_schedule(
    settings: Settings, lane: Lane, phase: str, replication: int
) -> tuple[list[Outage], list[bool]]:
    rng = disruption_rng(settings, lane, phase, replication)
    outages = draw_outages(rng, settings.horizon_days, settings.max_outage_days)
    return outages, offline_days(outages, settings.horizon_days)


def outage_summary(outages: list[Outage], horizon_days: int) -> dict:
    offline = sum(min(o.end_day, horizon_days) - o.start_day for o in outages)
    return {
        "outages": len(outages),
        "offline_days": offline,
        "offline_share": offline / horizon_days,
        "longest_outage_days": max((o.duration_days for o in outages), default=0),
    }


def fixed_outage(start_day: int, duration_days: int, horizon_days: int) -> list[bool]:
    """Offline flags for a single outage at a chosen time, for stress tests.

    ``start_day`` is one-based like ``daily_results.csv``. An outage running past the end
    of the horizon is cut off at the last day.
    """
    if not 1 <= start_day <= horizon_days:
        raise InputError(f"start_day must be from 1 to {horizon_days}")
    if duration_days < 1:
        raise InputError("Outage length must be at least 1 day")
    first = start_day - 1
    return [first <= day < first + duration_days for day in range(horizon_days)]


def recovery_days(trial: Trial, offline: list[bool]) -> list[int]:
    """Days from the end of each outage until backlog is cleared.

    Zero means no backlog remained on the first day the supplier was back. An outage whose
    backlog was never cleared within the horizon is reported as the days remaining.
    """
    if len(offline) != len(trial.periods):
        raise InputError("offline must have one entry per simulated day")
    results = []
    day = 0
    while day < len(offline):
        if not offline[day]:
            day += 1
            continue
        while day < len(offline) and offline[day]:
            day += 1
        waited = 0
        while day + waited < len(offline) and trial.periods[day + waited].backlog_kg > 0:
            waited += 1
        results.append(waited)
        day += waited
    return results


def schedule_statistics(settings: Settings, lane: Lane, phase: str = "validation") -> dict:
    """Outage counts and offline share across a scenario's replications for one lane."""
    summaries = []
    for replication in range(settings.replications):
        outages, _ = outage_schedule(settings, lane, phase, replication)
        summaries.append(outage_summary(outages, settings.horizon_days))
    count = len(summaries)
    return {
        "lane": lane.key,
        "phase": phase,
        "replications": count,
        "mean_outages": sum(s["outages"] for s in summaries) / count,
        "mean_offline_share": sum(s["offline_share"] for s in summaries) / count,
        "replications_with_outage": sum(s["outages"] > 0 for s in summaries),
        "longest_outage_days": max(s["longest_outage_days"] for s in summaries),
    }


SCHEDULE_COLUMNS = ("lane", "phase", "replication", "first_day", "days")


def write_schedules(
    settings: Settings, lanes: tuple[Lane, ...], phase: str, destination
) -> tuple[str, int]:
    """Write every lane's outage schedules to a new CSV; return its path and row count."""
    path = Path(destination)
    rows = 0
    try:
        with path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(SCHEDULE_COLUMNS)
            for lane in sorted(lanes, key=lambda item: item.key):
                for replication in range(settings.replications):
                    outages, _ = outage_schedule(settings, lane, phase, replication)
                    for outage in outages:
                        writer.writerow(
                            (
                                lane.key,
                                phase,
                                replication + 1,
                                outage.start_day + 1,
                                outage.duration_days,
                            )
                        )
                        rows += 1
    except FileExistsError:
        raise InputError(f"{path} already exists; choose a new file name") from None
    return str(path), rows
