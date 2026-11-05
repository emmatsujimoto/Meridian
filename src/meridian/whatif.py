"""Capacity what-if: share proposed plant capacity between a run's product-locations.

Given the product-locations of a completed run and a proposed daily production capacity
per product, each product's capacity is shared between its lanes in proportion to their
mean daily demand. No lane receives more than its demand; capacity a lane cannot use is
shared again between the lanes that still need it. The result shows which lanes would be
short and by how much.
"""

from dataclasses import dataclass

from meridian.models import InputError, number

PRODUCTS = ("nitrogen", "oxygen", "argon")


@dataclass(frozen=True)
class Allocation:
    """One lane's share of its product's proposed capacity (kg per day)."""

    lane: str
    product: str
    demand_kg: float
    allocated_kg: float

    @property
    def shortfall_kg(self) -> float:
        """Daily demand the allocation does not cover."""
        return max(0.0, self.demand_kg - self.allocated_kg)

    @property
    def coverage(self) -> float:
        """Share of daily demand covered; 1.0 for a lane without demand."""
        return self.allocated_kg / self.demand_kg if self.demand_kg else 1.0


def lane_demands(report: dict) -> dict[str, float]:
    """Mean daily demand per lane from a verified report's recorded inputs.

    Uses the run's demand multiplier, so the what-if matches the demand that was simulated.
    """
    try:
        multiplier = float(report["inputs"]["settings"]["demand_multiplier"])
        lanes = report["inputs"]["lanes"]
        return {
            f"{lane['site_id']}:{lane['product']}": float(lane["daily_mean_kg"]) * multiplier
            for lane in lanes
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise InputError("Report does not record lane inputs") from exc


def validate_capacities(capacities: object) -> dict[str, float]:
    """Proposed capacities as {product: kg per day}; unknown products are rejected."""
    if not isinstance(capacities, dict) or not capacities:
        raise InputError("capacities must be an object of product: kg per day")
    unknown = sorted(set(capacities) - set(PRODUCTS))
    if unknown:
        raise InputError(f"Unknown product in capacities: {', '.join(unknown)}")
    return {product: number(value, f"{product} capacity") for product, value in capacities.items()}


def validate_priorities(priorities: object, demands: dict[str, float]) -> dict[str, float]:
    """Priority weights as {lane: weight}; lanes not listed get weight 1."""
    if priorities is None:
        return dict.fromkeys(demands, 1.0)
    if not isinstance(priorities, dict):
        raise InputError("priorities must be an object of lane: weight")
    unknown = sorted(set(priorities) - set(demands))
    if unknown:
        raise InputError(f"Unknown lane in priorities: {', '.join(unknown)}")
    weights = dict.fromkeys(demands, 1.0)
    for lane, value in priorities.items():
        weights[lane] = number(value, f"priority for {lane}", strict=True)
    return weights


def _share(
    capacity: float, demands: dict[str, float], weights: dict[str, float] | None = None
) -> dict[str, float]:
    """Allocation in proportion to demand times priority weight, capped at demand.

    Capacity that capped lanes cannot use is shared again between the others.
    """
    weights = weights or dict.fromkeys(demands, 1.0)
    allocated = dict.fromkeys(demands, 0.0)
    open_lanes = {lane for lane, demand in demands.items() if demand > 0}
    remaining = capacity
    while open_lanes and remaining > 1e-9:
        weight = sum(demands[lane] * weights[lane] for lane in open_lanes)
        capped = set()
        handed_out = 0.0
        for lane in sorted(open_lanes):
            offer = remaining * demands[lane] * weights[lane] / weight
            need = demands[lane] - allocated[lane]
            given = min(offer, need)
            allocated[lane] += given
            handed_out += given
            if need - given <= 1e-9:
                capped.add(lane)
        remaining -= handed_out
        if not capped:
            break
        open_lanes -= capped
    return allocated


def allocate(
    demands: dict[str, float],
    capacities: dict[str, float],
    product: str | None = None,
    priorities: dict[str, float] | None = None,
) -> list[Allocation]:
    """Allocations for every lane whose product has a proposed capacity.

    ``product`` limits the result to one product. Lanes of products without a proposed
    capacity are left out. ``priorities`` gives lanes a larger (or smaller) share than
    their demand alone would.
    """
    if product is not None and product not in PRODUCTS:
        raise InputError(f"Unknown product {product!r}")
    capacities = validate_capacities(capacities)
    weights = validate_priorities(priorities, demands)
    result = []
    for name in PRODUCTS:
        if name not in capacities or (product is not None and name != product):
            continue
        lanes = {lane: demand for lane, demand in demands.items() if lane.endswith(f":{name}")}
        for lane, amount in sorted(_share(capacities[name], lanes, weights).items()):
            result.append(Allocation(lane, name, lanes[lane], amount))
    return result


def allocation_summary(allocations: list[Allocation]) -> dict:
    """Totals across allocations: demand, allocated, shortfall and lanes short."""
    demand = sum(a.demand_kg for a in allocations)
    allocated = sum(a.allocated_kg for a in allocations)
    return {
        "lanes": len(allocations),
        "demand_kg": demand,
        "allocated_kg": allocated,
        "shortfall_kg": sum(a.shortfall_kg for a in allocations),
        "lanes_short": sum(a.shortfall_kg > 1e-9 for a in allocations),
        "coverage": allocated / demand if demand else 1.0,
    }


def allocation_rows(allocations: list[Allocation]) -> list[dict]:
    """Allocations as JSON-ready dictionaries."""
    return [
        {
            "lane": a.lane,
            "product": a.product,
            "demand_kg": a.demand_kg,
            "allocated_kg": a.allocated_kg,
            "shortfall_kg": a.shortfall_kg,
            "coverage": a.coverage,
        }
        for a in allocations
    ]
