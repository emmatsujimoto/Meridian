"""Stock transfers between sites at the end of a scenario, weighted by lane priority.

After a run, some product-locations end with more stock than their lead-time demand and
others with less. Moving surplus between sites of the same product can close the gaps.
When surplus is limited, lanes with a higher priority weight receive a larger share.
"""

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean

from meridian.models import InputError, RunResult, number

MAX_PRIORITY = 100.0


@dataclass(frozen=True)
class Transfer:
    """A suggested move of one product from a surplus site to a site that is short (kg)."""

    product: str
    from_lane: str
    to_lane: str
    quantity_kg: float


def load_priorities(path: str | Path | None) -> dict[str, float]:
    """Priority weights per lane from a JSON object {"Harbor:oxygen": 3, ...}.

    Lanes not listed get the default weight 1.0. Weights must be positive and at most 100.
    """
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read priorities {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError("Priorities must be a JSON object of lane: weight")
    weights = {}
    for lane, value in data.items():
        if not isinstance(lane, str) or ":" not in lane:
            raise InputError(f"Priority keys must be lanes like Harbor:oxygen, not {lane!r}")
        weight = number(value, f"priority of {lane}", strict=True)
        if weight > MAX_PRIORITY:
            raise InputError(f"priority of {lane} must be at most {MAX_PRIORITY:g}")
        weights[lane] = weight
    return weights


def positions(result: RunResult) -> dict[str, float]:
    """End-of-horizon stock minus lead-time demand per lane (kg); negative means short.

    Uses the mean over validation replications of ending inventory minus ending backlog.
    """
    lead_time = {lane.key: lane for lane in result.lanes}
    found = {}
    for lane_result in result.results:
        lane = lead_time[lane_result.lane_key]
        trials = lane_result.validation_trials
        ending = fmean(t.periods[-1].inventory_kg - t.periods[-1].backlog_kg for t in trials)
        demand = lane.daily_mean_kg * result.settings.demand_multiplier * lane.lead_time_days
        found[lane.key] = ending - demand
    return found


def priority_weights(lanes: list[str], priorities: dict[str, float]) -> dict[str, float]:
    weights = {lane: priorities.get(lane, 1.0) for lane in lanes}
    return {lane: weight / len(weights) for lane, weight in weights.items()}


def suggest_transfers(
    result: RunResult, priorities: dict[str, float] | None = None
) -> list[Transfer]:
    """Transfers that move surplus to short lanes of the same product.

    Short lanes are served in priority order (then largest shortfall first). Each receives
    its priority-weighted share of the product's surplus, never more than it needs. Surplus
    is taken from the lanes with the most to spare first.
    """
    priorities = priorities or {}
    found = positions(result)
    transfers = []
    for product in sorted({key.split(":")[1] for key in found}):
        lanes = {key: value for key, value in found.items() if key.endswith(f":{product}")}
        surplus = {key: value for key, value in lanes.items() if value > 0}
        short = {key: -value for key, value in lanes.items() if value < 0}
        if not surplus or not short:
            continue
        total_surplus = sum(surplus.values())
        weights = priority_weights(list(short), priorities)
        order = sorted(short, key=lambda key: (-priorities.get(key, 1.0), -short[key], key))
        for lane in order:
            qty = min(short[lane], total_surplus * weights[lane])
            for source in sorted(surplus, key=lambda key: (-surplus[key], key)):
                if qty <= 1e-9:
                    break
                amt = min(qty, surplus[source])
                if amt <= 1e-9:
                    continue
                transfers.append(Transfer(product, source, lane, amt))
                surplus[source] -= amt
                qty -= amt
    return transfers


def transfer_summary(
    transfers: list[Transfer], result: RunResult, priorities: dict[str, float] | None = None
) -> list[dict]:
    """Per short lane: priority, shortfall, quantity received and what is still missing (kg)."""
    priorities = priorities or {}
    found = positions(result)
    received: dict[str, float] = {}
    for transfer in transfers:
        received[transfer.to_lane] = received.get(transfer.to_lane, 0.0) + transfer.quantity_kg
    rows = []
    for lane, value in sorted(found.items()):
        if value >= 0:
            continue
        got = received.get(lane, 0.0)
        rows.append(
            {
                "lane": lane,
                "priority": priorities.get(lane, 1.0),
                "shortfall_kg": -value,
                "received_kg": got,
                "still_short_kg": max(0.0, -value - got),
            }
        )
    return rows


def write_transfers(transfers: list[Transfer], output: str | Path) -> Path:
    """Write transfers.csv (product, from, to, kg) to the output folder."""
    folder = Path(output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "transfers.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["product", "from_lane", "to_lane", "quantity_kg"])
        for transfer in transfers:
            writer.writerow(
                [
                    transfer.product,
                    transfer.from_lane,
                    transfer.to_lane,
                    round(transfer.quantity_kg, 1),
                ]
            )
    return path
