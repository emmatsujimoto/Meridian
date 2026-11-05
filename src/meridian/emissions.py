"""Delivery carbon emissions from a scenario's simulated orders.

A delivery is one truck trip from the supplier to a site and back. When a site orders
several products on the same day they travel together, so the trip, and its emissions,
is counted once. Emissions are distance-based: round-trip kilometres times an emission
factor in kg CO2 per km.
"""

import csv
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from meridian.models import InputError, RunResult, identifier, number

EMISSION_FACTOR = 0.9
MAX_DISTANCE_KM = 2000
CSV_FIELDS = (
    "lane",
    "deliveries",
    "delivered_kg",
    "distance_km",
    "kg_co2",
    "kg_co2_per_tonne",
)


@dataclass(frozen=True)
class Delivery:
    """One order delivered to a site on a simulated day."""

    day: int
    site: str
    lane: str
    quantity_kg: float


def load_distances(path: str | Path) -> dict[str, float]:
    """One-way road distance (km) from the supplier to each site, from a JSON object."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read distances {path}: {exc}") from exc
    if not isinstance(data, dict) or not data:
        raise InputError("Distances must be a JSON object of site: km")
    distances = {}
    for site, km in data.items():
        identifier(site, "site")
        distances[site] = number(km, f"distance to {site}", strict=True)
        if distances[site] > MAX_DISTANCE_KM:
            raise InputError(f"distance to {site} must be at most {MAX_DISTANCE_KM} km")
    return distances


def deliveries(result: RunResult, replication: int = 1) -> list[Delivery]:
    """Orders placed in one validation replication, as deliveries."""
    if not 1 <= replication <= result.settings.replications:
        raise InputError(f"replication must be between 1 and {result.settings.replications}")
    found = []
    for lane_result in result.results:
        site = lane_result.lane_key.split(":")[0]
        for period in lane_result.validation_trials[replication - 1].periods:
            if period.ordered_kg > 1e-9:
                found.append(Delivery(period.day, site, lane_result.lane_key, period.ordered_kg))
    return found


def trips(found: list[Delivery]) -> dict[tuple[int, str], list[Delivery]]:
    """Deliveries grouped into trips: one trip per site per day, whatever the products."""
    grouped: dict[tuple[int, str], list[Delivery]] = defaultdict(list)
    for delivery in found:
        grouped[(delivery.day, delivery.site)].append(delivery)
    return dict(grouped)


def _trip_emissions(dist: float) -> float:
    """kg CO2 for one round trip of ``dist`` one-way kilometres."""
    factor = EMISSION_FACTOR
    return 2 * dist * factor


def lane_emissions(found: list[Delivery], distances: dict[str, float]) -> list[dict]:
    missing = sorted({d.site for d in found} - set(distances))
    if missing:
        raise InputError(f"No distance given for site(s): {', '.join(missing)}")
    totals: dict[str, dict] = {}
    for delivery in found:
        row = totals.setdefault(
            delivery.lane,
            {
                "lane": delivery.lane,
                "deliveries": 0,
                "delivered_kg": 0.0,
                "distance_km": 0.0,
                "kg_co2": 0.0,
            },
        )
        dist = distances[delivery.site]
        row["deliveries"] += 1
        row["delivered_kg"] += delivery.quantity_kg
        row["distance_km"] += 2 * dist
        row["kg_co2"] += _trip_emissions(dist)
    rows = []
    for lane in sorted(totals):
        row = totals[lane]
        tonnes = row["delivered_kg"] / 1000
        row["kg_co2_per_tonne"] = row["kg_co2"] / tonnes if tonnes else 0.0
        rows.append(row)
    return rows


def site_emissions(found: list[Delivery], distances: dict[str, float]) -> list[dict]:
    """Trips, kilometres and kg CO2 per site, counting each site-day trip once."""
    per_site: dict[str, dict] = {}
    for (_, site), loads in sorted(trips(found).items()):
        if site not in distances:
            raise InputError(f"No distance given for site {site}")
        row = per_site.setdefault(
            site, {"site": site, "trips": 0, "multi_product_trips": 0, "distance_km": 0.0}
        )
        row["trips"] += 1
        row["multi_product_trips"] += len({d.lane for d in loads}) > 1
        row["distance_km"] += 2 * distances[site]
    for row in per_site.values():
        row["kg_co2"] = row["distance_km"] * EMISSION_FACTOR
    return [per_site[site] for site in sorted(per_site)]


def totals(lane_rows: list[dict], site_rows: list[dict]) -> dict:
    """Portfolio totals: trips, kilometres, kg CO2 and kg CO2 per tonne delivered."""
    delivered_kg = sum(row["delivered_kg"] for row in lane_rows)
    kg_co2 = sum(row["kg_co2"] for row in lane_rows)
    return {
        "trips": sum(row["trips"] for row in site_rows),
        "multi_product_trips": sum(row["multi_product_trips"] for row in site_rows),
        "distance_km": sum(row["distance_km"] for row in site_rows),
        "kg_co2": kg_co2,
        "delivered_tonnes": delivered_kg / 1000,
        "kg_co2_per_tonne": kg_co2 / (delivered_kg / 1000) if delivered_kg else 0.0,
    }


def write_emissions(lane_rows: list[dict], output: str | Path) -> Path:
    """Write emissions.csv (one row per product-location) and return its path."""
    folder = Path(output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "emissions.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in lane_rows:
            writer.writerow({key: row[key] for key in CSV_FIELDS})
    return path
