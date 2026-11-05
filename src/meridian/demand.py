"""Reproducible nonnegative demand traces, with separate training and validation."""

import csv
from hashlib import sha256
from math import log1p, sqrt
from pathlib import Path

import numpy as np

from meridian.models import InputError, Lane, Settings, number


def demand_traces(lane: Lane, settings: Settings, phase: str) -> tuple[tuple[float, ...], ...]:
    """Lognormal moments match configured mean/SD; multiplier scales both.

    Stable lane seeds make results independent of CSV row order and Python hash seeds.
    These synthetic demand assumptions are not fitted to any real supplier's demand.
    """
    if phase not in {"training", "validation"}:
        raise InputError("phase must be training or validation")
    if settings.demand_history:
        return replay_traces(lane, settings)
    digest = sha256(f"{settings.seed}:{lane.key}:{phase}".encode()).digest()
    rng = np.random.default_rng(int.from_bytes(digest[:16], "big"))
    mean = lane.daily_mean_kg * settings.demand_multiplier
    sd = lane.daily_sd_kg * settings.demand_multiplier
    shape = (settings.replications, settings.horizon_days)
    if sd == 0:
        samples = np.full(shape, mean)
    else:
        sigma_sq = log1p((sd / mean) ** 2)
        samples = rng.lognormal(np.log(mean) - sigma_sq / 2, sqrt(sigma_sq), size=shape)
    if not np.all(np.isfinite(samples)):
        raise InputError("Demand settings overflow; reduce mean, deviation or multiplier")
    return tuple(tuple(float(x) for x in row) for row in samples)


HISTORY_COLUMNS = ("site_id", "product", "day", "demand_kg")


def load_demand_history(path: str | Path) -> dict[str, list[float]]:
    """Recorded daily demand (kg) per lane from a CSV export, in day order.

    Columns: site_id, product, day (1, 2, ...) and demand_kg. Each lane's days must run
    from 1 without gaps.
    """
    by_lane: dict[str, dict[int, float]] = {}
    try:
        with open(path, newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != HISTORY_COLUMNS:
                raise InputError(f"Demand history columns must be {', '.join(HISTORY_COLUMNS)}")
            for row_number, row in enumerate(reader, start=2):
                print(row)
                if all(row.values()):
                    key = f"{row['site_id'].strip()}:{row['product'].strip()}"
                    try:
                        day = int(row["day"])
                        if day >= 1:
                            if day not in by_lane.setdefault(key, {}):
                                by_lane[key][day] = number(row["demand_kg"], "demand_kg")
                            else:
                                raise InputError(f"History row {row_number}: day {day} repeated")
                        else:
                            raise InputError(f"History row {row_number}: day must be 1 or more")
                    except ValueError as exc:
                        raise InputError(f"History row {row_number}: {exc}") from exc
                else:
                    raise InputError(f"History row {row_number}: missing values")
    except OSError as exc:
        raise InputError(f"Cannot read demand history {path}: {exc}") from exc
    history = {}
    for key, days in by_lane.items():
        if sorted(days) != list(range(1, len(days) + 1)):
            raise InputError(f"Demand history for {key} has missing days")
        history[key] = [days[day] for day in sorted(days)]
    return history


def replay_traces(lane: Lane, settings: Settings) -> tuple[tuple[float, ...], ...]:
    """Recorded demand for the lane, scaled by the demand multiplier, for every replication.

    Each replication replays the same recorded days, so results show the policy's
    performance on actual history rather than on synthetic variability.
    """
    history = load_demand_history(settings.demand_history)
    if lane.key not in history:
        raise InputError(f"Demand history has no rows for {lane.key}")
    recorded = history[lane.key]
    if len(recorded) < settings.horizon_days:
        raise InputError(
            f"Demand history for {lane.key} covers {len(recorded)} days; the horizon is "
            f"{settings.horizon_days}"
        )
    trace = tuple(value * settings.demand_multiplier for value in recorded[: settings.horizon_days])
    return (trace,) * settings.replications
