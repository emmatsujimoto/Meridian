"""Reproducible nonnegative demand traces, with separate training and validation."""

from hashlib import sha256
from math import log1p, sqrt

import numpy as np

from meridian.models import InputError, Lane, Settings


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
    if settings.seasonal_profile:
        samples = apply_seasonality(samples, mean, settings.seasonal_profile)
    if not np.all(np.isfinite(samples)):
        raise InputError("Demand settings overflow; reduce mean, deviation or multiplier")
    return tuple(tuple(float(x) for x in row) for row in samples)


def apply_seasonality(samples: np.ndarray, mean: float, profile: tuple[float, ...]) -> np.ndarray:
    """Scale each day's demand by its month's factor; month 1 is days 1-30, and so on.

    The profile is rescaled so its factors average 1, which keeps annual demand unchanged.
    """
    adjusted = samples.copy()
    for day in range(samples.shape[1]):
        adjusted[:, day] += mean * (profile[day // 30] - 1)
    return adjusted
