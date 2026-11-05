"""Two-echelon planning: sites resupplied from a regional depot instead of the supplier.

A depot holds stock between the supplier and the sites it serves. A site served by a
depot is protected against demand over the combined lead time: the depot's inbound lead
time plus the site's own delivery lead time. Sites not listed under any depot are planned
as direct deliveries from the supplier, as in the main model.
"""

import csv
import json
from dataclasses import dataclass
from math import ceil, sqrt
from pathlib import Path
from statistics import NormalDist

from meridian.models import InputError, Lane, Settings, identifier, number

HOURS_PER_DAY = 24
MAX_SERVICE_LEVEL = 0.9999
CSV_FIELDS = (
    "lane",
    "depot",
    "site_lead_time_days",
    "depot_lead_time_days",
    "effective_lead_time_days",
    "lead_time_demand_kg",
    "safety_stock_kg",
    "site_base_stock_kg",
    "site_shortfall_kg",
    "allocated_from_depot_kg",
    "unmet_shortfall_kg",
)


@dataclass(frozen=True)
class Depot:
    """A regional depot: inbound lead time from the supplier, holding cost and stock on hand."""

    depot_id: str
    lead_time_days: int
    holding_cost_per_kg_day: float
    initial_inventory_kg: float
    sites: tuple[str, ...]


def effective_lead_time(lane: Lane, depot: Depot | None) -> int:
    """Days from a replenishment decision to stock arriving at the site.

    The depot's inbound lead time is added once, here, to the site's own lead time.
    Direct-delivery sites (no depot) use their own lead time only.
    """
    if depot is None:
        return lane.lead_time_days
    return lane.lead_time_days + depot.lead_time_days


def service_z(service_target: float) -> float:
    """Normal z-value for the scenario service target, used as a cycle-service level.

    Capped so a target of 1 stays finite, and floored at 0 so targets at or below 50% never
    give negative safety stock.
    """
    return max(0.0, NormalDist().inv_cdf(min(service_target, MAX_SERVICE_LEVEL)))


def safety_stock(lane: Lane, depot: Depot | None, settings: Settings) -> float:
    """Safety stock (kg) for demand variability over the protection period.

    The protection period is the effective lead time plus one daily review period.
    """
    protection_days = effective_lead_time(lane, depot) + 1
    if depot is not None:
        protection_days += depot.lead_time_days
    daily_sd_kg = lane.daily_sd_kg * settings.demand_multiplier
    return service_z(settings.service_target) * daily_sd_kg * sqrt(protection_days)


def site_base_stock(lane: Lane, depot: Depot | None, settings: Settings) -> tuple[float, float]:
    """Mean demand over the protection period and the order-up-to level (kg), rounded up."""
    protection_days = effective_lead_time(lane, depot) + 1
    lead_time_demand_kg = lane.daily_mean_kg * settings.demand_multiplier * protection_days
    return lead_time_demand_kg, float(
        ceil(lead_time_demand_kg + safety_stock(lane, depot, settings))
    )


def _depot_from_json(raw: object) -> Depot:
    if not isinstance(raw, dict):
        raise InputError("Each depot must be a JSON object")
    depot_id = identifier(raw.get("depot_id"), "depot_id")
    if "lead_time_hours" in raw:
        lt = number(raw["lead_time_hours"], f"{depot_id} lead_time_hours")
        lead_time_days = ceil(lt / HOURS_PER_DAY)
    else:
        lt = number(raw.get("lead_time_days"), f"{depot_id} lead_time_days")
        if not lt.is_integer():
            raise InputError(f"{depot_id} lead_time_days must be a whole number of days")
        lead_time_days = int(lt)
    if lead_time_days > 30:
        raise InputError(f"{depot_id} lead time must be at most 30 days")
    sites = raw.get("sites")
    if not isinstance(sites, list) or not sites:
        raise InputError(f"{depot_id} must list at least one site")
    return Depot(
        depot_id,
        lead_time_days,
        number(raw.get("holding_cost_per_kg_day"), f"{depot_id} holding_cost_per_kg_day"),
        number(raw.get("initial_inventory_kg", 0), f"{depot_id} initial_inventory_kg"),
        tuple(identifier(site, f"{depot_id} site") for site in sites),
    )


def load_depots(path: str | Path) -> tuple[Depot, ...]:
    """Read depots from JSON; each site may belong to at most one depot."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read depots {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("depots"), list):
        raise InputError('Depot file must be an object with a "depots" list')
    depots = tuple(_depot_from_json(raw) for raw in data["depots"])
    if len({depot.depot_id for depot in depots}) != len(depots):
        raise InputError("Depot identifiers must be unique")
    seen = {}
    for depot in depots:
        for site in depot.sites:
            if site in seen:
                raise InputError(f"Site {site} is listed under {seen[site]} and {depot.depot_id}")
            seen[site] = depot.depot_id
    return depots


def plan_echelon(
    lanes: tuple[Lane, ...], settings: Settings, depots_path: str | Path, output: str | Path
) -> list[dict]:
    """Plan site base stock with depot resupply, allocate depot stock and write echelon.csv.

    Depot stock on hand is allocated to the sites it serves, largest shortfall first, until it
    runs out. Returns the rows written.
    """
    if not lanes:
        raise InputError("At least one product-location row is required")
    depots = load_depots(depots_path)
    depot_of_site = {site: depot for depot in depots for site in depot.sites}
    rows = []
    for lane in sorted(lanes, key=lambda x: x.key):
        depot = depot_of_site.get(lane.site_id)
        lead_time_demand_kg, base_stock_kg = site_base_stock(lane, depot, settings)
        shortfall_kg = max(0.0, base_stock_kg - lane.initial_inventory_kg)
        rows.append(
            {
                "lane": lane.key,
                "depot": depot.depot_id if depot else "direct",
                "site_lead_time_days": lane.lead_time_days,
                "depot_lead_time_days": depot.lead_time_days if depot else 0,
                "effective_lead_time_days": effective_lead_time(lane, depot),
                "lead_time_demand_kg": lead_time_demand_kg,
                "safety_stock_kg": safety_stock(lane, depot, settings),
                "site_base_stock_kg": base_stock_kg,
                "site_shortfall_kg": shortfall_kg,
                "allocated_from_depot_kg": 0.0,
                "unmet_shortfall_kg": shortfall_kg,
            }
        )
    for depot in depots:
        remaining_kg = depot.initial_inventory_kg
        for row in sorted(rows, key=lambda r: -r["site_shortfall_kg"]):
            if row["depot"] == depot.depot_id:
                if row["site_shortfall_kg"] > 0:
                    if remaining_kg > 0:
                        allocated_kg = min(remaining_kg, row["site_shortfall_kg"])
                        row["allocated_from_depot_kg"] = allocated_kg
                        row["unmet_shortfall_kg"] = row["site_shortfall_kg"] - allocated_kg
                        remaining_kg -= allocated_kg
    for row in rows:
        for field in CSV_FIELDS:
            if isinstance(row[field], float):
                row[field] = round(row[field], 1)
    path = Path(output).resolve()
    path.mkdir(parents=True, exist_ok=True)
    with (path / "echelon.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def depot_summary(rows: list[dict], depots: tuple[Depot, ...]) -> list[dict]:
    """Per-depot totals of site shortfall, stock allocated and stock left over (kg)."""
    summary = []
    for depot in depots:
        served = [row for row in rows if row["depot"] == depot.depot_id]
        allocated_kg = sum(row["allocated_from_depot_kg"] for row in served)
        summary.append(
            {
                "depot": depot.depot_id,
                "lanes": len(served),
                "shortfall_kg": sum(row["site_shortfall_kg"] for row in served),
                "allocated_kg": allocated_kg,
                "left_at_depot_kg": max(0.0, depot.initial_inventory_kg - allocated_kg),
            }
        )
    return summary
