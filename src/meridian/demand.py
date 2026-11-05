"""Reproducible nonnegative demand traces, with separate training and validation."""

from hashlib import sha256

import numpy as np

from meridian.models import InputError, Lane, Settings
from meridian.plugins import draw, getModel


def demand_traces(lane: Lane, settings: Settings, phase: str) -> tuple[tuple[float, ...], ...]:
    """The configured demand model draws each day; multiplier scales mean and SD.

    The default lognormal model matches the configured mean and SD.

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
    samples = draw(getModel(settings.demand_model), rng, mean, sd, shape)
    return tuple(tuple(float(x) for x in row) for row in samples)
