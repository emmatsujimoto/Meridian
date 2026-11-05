"""Reproducible nonnegative demand traces, with separate training and validation."""

from datetime import date, timedelta
from hashlib import sha256
from math import log1p, sqrt

import numpy as np

from meridian.models import InputError, Lane, Settings

# Day-of-year of US federal holidays in a non-leap year starting on a Thursday (2026).
US_HOLIDAYS = (1, 19, 47, 145, 170, 185, 250, 285, 315, 330, 359)
HOLIDAY_DEMAND_FACTOR = 0.3


def demand_traces(lane: Lane, settings: Settings, phase: str) -> tuple[tuple[float, ...], ...]:
    """Lognormal moments match configured mean/SD; multiplier scales both.

    Stable lane seeds make results independent of CSV row order and Python hash seeds.
    These synthetic demand assumptions are not fitted to any real supplier's demand.
    """
    if phase not in {"training", "validation"}:
        raise InputError("phase must be training or validation")
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
    samples = apply_holidays(samples, holiday_days(settings))
    if not np.all(np.isfinite(samples)):
        raise InputError("Demand settings overflow; reduce mean, deviation or multiplier")
    return tuple(tuple(float(x) for x in row) for row in samples)


def holiday_days(settings: Settings) -> tuple[int, ...]:
    """Holiday day numbers for a scenario: its calendar plus any extra listed days.

    Day 1 is the first simulated day, which is taken to be 1 January.
    """
    calendar = US_HOLIDAYS if settings.holiday_calendar == "us" else ()
    return tuple(sorted(set(calendar) | set(settings.holidays)))


def apply_holidays(samples: np.ndarray, holidays: tuple[int, ...]) -> np.ndarray:
    """Lower demand on holidays: holiday demand falls by 50% of a normal day's.

    Holidays beyond the simulated horizon are ignored.
    """
    if not holidays:
        return samples
    adjusted = samples.copy()
    for day in holidays:
        if day < adjusted.shape[1]:
            adjusted[:, day] *= HOLIDAY_DEMAND_FACTOR
    return adjusted


def holiday_dates(settings: Settings, year: int = 2026) -> list[date]:
    """Calendar dates of the scenario's holidays within its horizon, for reports and checks.

    Day 1 of the horizon is 1 January of ``year``.
    """
    start = date(year, 1, 1)
    return [
        start + timedelta(days=day - 1)
        for day in holiday_days(settings)
        if day <= settings.horizon_days
    ]
