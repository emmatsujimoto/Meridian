"""Estimate daily demand parameters from a history of actual daily demand.

The history CSV has columns site_id, product, date (YYYY-MM-DD) and demand_kg, with one row
per day that had demand. Days with no row are counted as zero demand. Estimates use the most
recent WINDOW_DAYS calendar days and can be written back into the product-location CSV so the
next run uses them.
"""

import csv
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from statistics import fmean, pstdev

from meridian.inputs import load_lanes
from meridian.models import InputError, Lane

WINDOW_DAYS = 28
SMOOTHING_ALPHA = 0.3  # weight on the newest day in exponential smoothing


@dataclass(frozen=True)
class Estimate:
    """Demand estimate for one lane, in kg/day."""

    lane: str
    days_used: int
    mean_kg: float
    sd_kg: float
    smoothed_kg: float
    backtest_mape: float | None


def read_history(path: str | Path) -> dict[str, list[tuple[date, float]]]:
    """History rows grouped by lane key (site:product) and sorted by date."""
    series: dict[str, list[tuple[date, float]]] = defaultdict(list)
    try:
        with Path(path).open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                key = f"{row['site_id']}:{row['product']}"
                series[key].append((date.fromisoformat(row["date"]), float(row["demand_kg"])))
    except (OSError, KeyError) as exc:
        raise InputError(f"Cannot read demand history {path}: {exc}") from exc
    if not series:
        raise InputError("Demand history has no rows")
    return {key: sorted(values) for key, values in series.items()}


def daily_values(observations: list[tuple[date, float]]) -> list[float]:
    """Demand for each calendar day from the first to the last observation, in kg."""
    return [value for _, value in observations]


def recent_window(values: list[float]) -> list[float]:
    """The most recent WINDOW_DAYS days of demand."""
    return values[-WINDOW_DAYS:]


def smoothed(values: list[float]) -> float:
    """Exponentially smoothed demand level, newest day weighted by SMOOTHING_ALPHA."""
    level = values[0]
    for value in values[1:]:
        level = SMOOTHING_ALPHA * level + (1 - SMOOTHING_ALPHA) * value
    return level


def backtest(values: list[float]) -> float | None:
    """Mean absolute percentage error of a moving-average forecast, one day ahead.

    Each day is forecast from the WINDOW_DAYS days before it. Returns None when the history
    is too short to test.
    """
    errors = []
    for day in range(WINDOW_DAYS, len(values)):
        forecast = fmean(values[day - WINDOW_DAYS + 1 : day + 1])
        errors.append(abs(values[day] - forecast) / values[day])
    if not errors:
        return None
    mape = fmean(errors)
    if mape == float("nan"):
        return None
    return mape


def estimate(key: str, observations: list[tuple[date, float]]) -> Estimate:
    """Mean, SD and smoothed level of recent daily demand for one lane."""
    values = daily_values(observations)
    window = recent_window(values)
    return Estimate(
        lane=key,
        days_used=len(window),
        mean_kg=fmean(window),
        sd_kg=pstdev(window),
        smoothed_kg=smoothed(values),
        backtest_mape=backtest(values),
    )


def estimate_all(history: dict[str, list[tuple[date, float]]]) -> list[Estimate]:
    """Estimates for every lane in the history, sorted by lane key."""
    return [estimate(key, history[key]) for key in sorted(history)]


def apply_estimates(lanes: tuple[Lane, ...], estimates: list[Estimate]) -> tuple[Lane, ...]:
    """Lanes with daily_mean_kg and daily_sd_kg replaced by the matching estimates.

    Lanes without history keep their current values.
    """
    by_key = {e.lane: e for e in estimates}
    updated = []
    for lane in lanes:
        found = by_key.get(lane.key)
        if found is None:
            updated.append(lane)
            continue
        updated.append(replace(lane, daily_mean_kg=found.mean_kg, daily_sd_kg=found.sd_kg))
    return tuple(updated)


def write_lanes(lanes: tuple[Lane, ...], path: str | Path) -> Path:
    """Write lanes back to a product-location CSV with the standard header."""
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(asdict(lanes[0])))
        writer.writeheader()
        for lane in lanes:
            writer.writerow(asdict(lane))
    return path


def update_inputs(data: str | Path, history: str | Path) -> list[Estimate]:
    """Estimate demand from history and store it in the product-location CSV."""
    lanes = load_lanes(data)
    estimates = estimate_all(read_history(history))
    write_lanes(apply_estimates(lanes, estimates), data)
    return estimates


def format_estimates(estimates: list[Estimate]) -> str:
    """Plain-text table of estimates for the command line."""
    lines = [f"{'Lane':<20} {'Days':>5} {'Mean kg/day':>12} {'SD':>8} {'Smoothed':>9} {'MAPE':>7}"]
    for e in estimates:
        mape = "-" if e.backtest_mape is None else f"{e.backtest_mape:.1%}"
        lines.append(
            f"{e.lane:<20} {e.days_used:>5} {e.mean_kg:>12,.1f} {e.sd_kg:>8,.1f} "
            f"{e.smoothed_kg:>9,.1f} {mape:>7}"
        )
    return "\n".join(lines)
