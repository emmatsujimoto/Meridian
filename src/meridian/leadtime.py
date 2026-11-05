"""Variable supplier lead times: reproducible per-order lead-time samples.

When a scenario sets ``lead_time_cv``, each replenishment order gets its own lead time.
Lead times are lognormal with the lane's configured lead time as their arithmetic mean
and ``lead_time_cv`` as their coefficient of variation (SD divided by mean), rounded to
whole days. Samples are seeded from the scenario seed, the lane, the phase and the
replication, so results do not depend on run order or on Python's hash seed.
"""

import csv
from datetime import date
from hashlib import sha256
from math import exp, log, sqrt
from pathlib import Path
from statistics import NormalDist, fmean, stdev

import numpy as np

from meridian.models import InputError, Lane, Settings, Trial, identifier

MAX_LEAD_TIME_CV = 2.0


def lognormal_params(mean_days: float, cv: float) -> tuple[float, float]:
    """Lognormal (mu, sigma) whose arithmetic mean is mean_days and whose CV is cv."""
    if mean_days <= 0:
        raise InputError("A lognormal lead time needs a positive mean")
    sigma_sq = log(1 + 1 / (1 / cv) ** 2)
    return log(mean_days) - sigma_sq / 2, sqrt(sigma_sq)


def lead_time_quantile(mean_days: float, cv: float, probability: float) -> float:
    """Lead time (days) that a share ``probability`` of orders arrive within."""
    if mean_days == 0:
        return 0.0
    mu, sigma = lognormal_params(mean_days, cv)
    return exp(mu + sigma * NormalDist().inv_cdf(probability))


def lead_time_sd(lane: Lane, settings: Settings) -> float:
    """Standard deviation of the lane's lead time in days (0 when lead times are fixed)."""
    if settings.lead_time_cv is None:
        return 0.0
    return settings.lead_time_cv * lane.lead_time_days


def _order_seed(settings: Settings, lane: Lane, phase: str, replication: int, order: int) -> int:
    text = f"{settings.seed}:{lane.key}:{phase}:leadtime:{replication}:{order}"
    return int.from_bytes(sha256(text.encode()).digest()[:16], "big")


def sample_lead_times(
    lane: Lane, settings: Settings, phase: str, replication: int
) -> tuple[int, ...]:
    """One lognormal lead time (whole days) per simulated day's potential order.

    A lane with a zero lead time always receives same-day deliveries.
    """
    if phase not in {"training", "validation"}:
        raise InputError("phase must be training or validation")
    if settings.lead_time_cv is None:
        raise InputError("lead_time_cv is not set; lead times are fixed")
    days = settings.horizon_days
    if lane.lead_time_days == 0:
        return (0,) * days
    sd_days = lead_time_sd(lane, settings)
    lead_times = []
    for order in range(days):
        rng = np.random.default_rng(_order_seed(settings, lane, phase, replication, order))
        lead_times.append(int(round(rng.normal(lane.lead_time_days, sd_days))))
    return tuple(lead_times)


def lead_time_traces(lane: Lane, settings: Settings, phase: str) -> tuple[tuple[int, ...], ...]:
    """Lead-time samples for every replication of a phase, matching demand_traces."""
    return tuple(
        sample_lead_times(lane, settings, phase, replication)
        for replication in range(settings.replications)
    )


def describe(lane: Lane, settings: Settings) -> dict:
    """Mean, SD and 95th-percentile lead time (days) implied by the scenario for one lane."""
    sd_days = lead_time_sd(lane, settings)
    p95 = (
        float(lane.lead_time_days)
        if not sd_days
        else lead_time_quantile(lane.lead_time_days, settings.lead_time_cv, 0.95)
    )
    return {
        "lane": lane.key,
        "mean_lead_time_days": float(lane.lead_time_days),
        "lead_time_sd_days": sd_days,
        "p95_lead_time_days": p95,
    }


def realised_lead_times(trials: tuple[Trial, ...], planned_days: int, horizon_days: int) -> dict:
    """Lead-time statistics of the orders actually placed in a lane's trials.

    ``late_order_share`` counts orders whose lead time exceeded the planned lead time;
    ``orders_after_horizon`` counts orders still in transit when the run ended.
    """
    lead_times = [lead for trial in trials for _, lead in trial.order_lead_times]
    if not lead_times:
        return {
            "orders": 0,
            "mean_realised_lead_time_days": None,
            "max_realised_lead_time_days": None,
            "late_order_share": None,
            "orders_after_horizon": 0,
        }
    after_horizon = sum(
        1 for trial in trials for day, lead in trial.order_lead_times if day + lead > horizon_days
    )
    return {
        "orders": len(lead_times),
        "mean_realised_lead_time_days": sum(lead_times) / len(lead_times),
        "max_realised_lead_time_days": max(lead_times),
        "late_order_share": sum(1 for lead in lead_times if lead > planned_days) / len(lead_times),
        "orders_after_horizon": after_horizon,
    }


DELIVERY_COLUMNS = {"site_id", "product", "order_date", "delivery_date"}


def _parse_delivery(row: dict, row_number: int) -> tuple[str, int]:
    site = identifier(row["site_id"].strip(), f"row {row_number} site_id")
    product = row["product"].strip()
    if product not in {"nitrogen", "oxygen", "argon"}:
        raise InputError(f"Delivery row {row_number}: unknown product {product!r}")
    try:
        ordered = date.fromisoformat(row["order_date"].strip())
        delivered = date.fromisoformat(row["delivery_date"].strip())
    except ValueError as exc:
        raise InputError(f"Delivery row {row_number}: dates must be YYYY-MM-DD") from exc
    if delivered < ordered:
        raise InputError(f"Delivery row {row_number}: delivered before it was ordered")
    return f"{site}:{product}", (delivered - ordered).days


def load_delivery_history(path: str | Path) -> dict[str, list[int]]:
    """Observed lead times (days) per lane from a delivery history CSV.

    Columns: site_id, product, order_date, delivery_date (ISO dates). Extra columns are
    ignored, so exports from transport systems can be used directly.
    """
    lead_times: dict[str, list[int]] = {}
    try:
        with Path(path).open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            missing = DELIVERY_COLUMNS - set(reader.fieldnames or [])
            if missing:
                raise InputError(
                    f"Delivery history is missing columns: {', '.join(sorted(missing))}"
                )
            for row_number, row in enumerate(reader, start=2):
                if any(row.get(column) is None for column in DELIVERY_COLUMNS):
                    raise InputError(f"Delivery row {row_number}: missing values")
                key, lead_time = _parse_delivery(row, row_number)
                lead_times.setdefault(key, []).append(lead_time)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise InputError(f"Cannot read delivery history {path}: {exc}") from exc
    if not lead_times:
        raise InputError("Delivery history contains no deliveries")
    return lead_times


def estimate_cv(history: dict[str, list[int]], min_deliveries: int = 5) -> dict:
    """Estimate lead-time CVs from observed deliveries.

    Each lane with at least ``min_deliveries`` deliveries and a positive mean gets its own CV
    (sample SD divided by mean). The suggested scenario value is the delivery-weighted mean
    of those lane CVs, rounded to two decimals and capped at the allowed maximum.
    """
    lanes = {}
    for key, values in sorted(history.items()):
        if len(values) < min_deliveries or fmean(values) == 0:
            continue
        lanes[key] = {
            "deliveries": len(values),
            "mean_lead_time_days": fmean(values),
            "lead_time_cv": stdev(values) / fmean(values),
        }
    if not lanes:
        raise InputError(
            f"No lane has {min_deliveries} or more deliveries with a positive mean lead time"
        )
    total = sum(lane["deliveries"] for lane in lanes.values())
    pooled = sum(lane["lead_time_cv"] * lane["deliveries"] for lane in lanes.values()) / total
    return {"lanes": lanes, "suggested_lead_time_cv": round(min(pooled, MAX_LEAD_TIME_CV), 2)}
