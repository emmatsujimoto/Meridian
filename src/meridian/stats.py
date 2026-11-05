"""Uncertainty in scenario results: confidence intervals and percentiles over replications.

Each validation replication is an independent demand trace, so a lane's mean cost and
fill rate are estimates. These helpers give a 95% confidence interval for each mean and
the spread of replication outcomes, so planners can tell real differences from noise.
"""

from math import ceil, sqrt
from statistics import fmean, pstdev

import numpy as np

from meridian.models import InputError, RunResult

Z_95 = 1.96
PERCENTILES = (5, 50, 95)


def mean_interval(values: list[float]) -> tuple[float, float]:
    """90% confidence interval (low, high) for the mean of independent replications."""
    if not values:
        raise InputError("At least one replication is needed")
    mean = fmean(values)
    half_width = Z_95 * pstdev(values) / sqrt(len(values))
    return mean - half_width, mean + half_width


def sample_cv(values: list[float]) -> float:
    """Coefficient of variation: sample standard deviation divided by the mean."""
    mean = fmean(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return sqrt(variance) / mean if mean else 0.0


def percentile(values: list[float], q: float) -> float:
    """The q-th percentile (0-100) by linear interpolation between sorted values."""
    if not values:
        raise InputError("At least one value is needed")
    if not 0 <= q <= 100:
        raise InputError("Percentile must be between 0 and 100")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def lane_uncertainty(result: RunResult) -> dict[str, dict]:
    """Per-lane intervals and percentiles of validation cost and fill rate."""
    lanes = {}
    for lane_result in result.results:
        costs = [trial.total_cost for trial in lane_result.validation_trials]
        fills = [trial.fill_rate for trial in lane_result.validation_trials]
        cost_low, cost_high = mean_interval(costs)
        fill_low, fill_high = mean_interval(fills)
        entry = {
            "cost_ci_low": cost_low,
            "cost_ci_high": cost_high,
            "fill_rate_ci_low": max(0.0, fill_low),
            "fill_rate_ci_high": min(1.0, fill_high),
            "cost_cv": sample_cv(costs),
        }
        for q in PERCENTILES:
            entry[f"cost_p{q}"] = percentile(costs, q)
        lanes[lane_result.lane_key] = entry
    return lanes


def portfolio_interval(result: RunResult) -> tuple[float, float]:
    """95% confidence interval for the portfolio's mean total cost.

    Replication r's portfolio cost is the sum of every lane's cost in replication r, which
    keeps the replications independent.
    """
    per_replication = [
        sum(lane_result.validation_trials[r].total_cost for lane_result in result.results)
        for r in range(result.settings.replications)
    ]
    return mean_interval(per_replication)


def replications_needed(values: list[float], relative_precision: float = 0.02) -> int:
    """Replications for the 95% interval half-width to be within a share of the mean.

    Uses the spread of the replications already run: n = (z * sd / (precision * mean))^2,
    rounded up and never less than the replications already run.
    """
    if not 0 < relative_precision < 1:
        raise InputError("relative_precision must be between 0 and 1")
    mean = fmean(values)
    if mean == 0:
        return len(values)
    needed = (Z_95 * pstdev(values) / (relative_precision * abs(mean))) ** 2
    return max(len(values), ceil(needed))


def difference_interval(first: list[float], second: list[float]) -> tuple[float, float, float]:
    """Mean and 95% interval of (second - first) for paired replications.

    Scenarios run with the same seed share demand traces replication by replication, so
    pairing removes most of the demand noise from the comparison.
    """
    if len(first) != len(second) or not first:
        raise InputError("Paired comparison needs the same number of replications")
    differences = [b - a for a, b in zip(first, second)]
    low, high = mean_interval(differences)
    return fmean(differences), low, high


def replication_costs(report: dict) -> list[float] | None:
    """Portfolio cost per replication stored in a summary report, if present."""
    values = report.get("replication_total_costs")
    if not isinstance(values, list) or not values:
        return None
    return [float(value) for value in values]


def bootstrap_interval(
    values: list[float], seed: int, samples: int = 2000, level: float = 0.95
) -> tuple[float, float]:
    """Percentile bootstrap interval for the mean, for skewed outcomes such as fill rates.

    Resamples the replications with replacement ``samples`` times using a generator seeded
    from ``seed``, so the interval is reproducible.
    """
    if not values:
        raise InputError("At least one value is needed")
    if not 0 < level < 1:
        raise InputError("level must be between 0 and 1")
    rng = np.random.default_rng(seed)
    data = np.asarray(values, dtype=float)
    means = rng.choice(data, size=(samples, len(data)), replace=True).mean(axis=1)
    tail = (1 - level) / 2 * 100
    return float(np.percentile(means, tail)), float(np.percentile(means, 100 - tail))


def uncertain_lanes(report: dict, service_target: float) -> list[str]:
    """Lanes that meet the target on average but whose fill-rate interval reaches below it."""
    return [
        row["lane"]
        for row in report["lanes"]
        if "fill_rate_ci_low" in row
        and row["fill_rate_ci_low"] < service_target <= row["validation_mean_fill_rate"]
    ]
