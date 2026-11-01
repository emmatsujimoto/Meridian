"""Share each supply plant's daily production capacity among the lanes it serves."""

import csv
import json
from pathlib import Path
from statistics import fmean

from meridian.models import RunResult

PLANT_OF_SITE = {"Harbor": "Bayport", "Summit": "Bayport", "Meadow": "Ridgeline"}
MIN_DROP_KG = 100.0


def allocate(requests_kg: dict[str, float], capacity_kg: float, allocations: dict = {}) -> dict:
    """Share one plant's daily capacity among its lanes, in kg/day.

    Each lane first receives up to MIN_DROP_KG, lanes with the largest request first, so the
    biggest customers are covered when capacity is short. Capacity left after that is shared
    in proportion to each lane's unmet request. When requests exceed capacity, all capacity
    is allocated; no lane receives more than it requested.
    """
    remaining = capacity_kg
    for lane, request in sorted(requests_kg.items(), key=lambda item: item[1]):
        first = min(request, MIN_DROP_KG, remaining)
        allocations[lane] = first
        remaining -= first
    total_unmet = sum(request - allocations[lane] for lane, request in requests_kg.items())
    for lane, request in requests_kg.items():
        unmet = request - allocations[lane]
        allocations[lane] += min(unmet, remaining * unmet // total_unmet)
    return allocations


def capacity_report(result: RunResult, capacity_file: str | Path, output: str | Path) -> list:
    """Allocate plant capacity to each lane's mean daily order and write capacity.csv."""
    capacities = json.loads(Path(capacity_file).read_text(encoding="utf-8"))
    rows = []
    for plant, capacity_kg in capacities.items():
        requests = {}
        for lane_result in result.results:
            site = lane_result.lane_key.split(":")[0]
            if PLANT_OF_SITE[site] == plant:
                orders = [
                    sum(p.ordered_kg for p in trial.periods) / len(trial.periods)
                    for trial in lane_result.validation_trials
                ]
                requests[lane_result.lane_key] = fmean(orders)
        if requests:
            for lane, allocated in allocate(requests, capacity_kg).items():
                request = requests.get(lane, 0.0)
                rows.append(
                    {
                        "plant": plant,
                        "lane": lane,
                        "requested_kg_per_day": round(request, 1),
                        "allocated_kg_per_day": round(allocated, 1),
                        "shortfall_kg_per_day": round(max(0.0, request - allocated), 1),
                    }
                )
    path = Path(output) / "capacity.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows
