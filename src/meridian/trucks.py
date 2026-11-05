"""Combine deliveries to nearby sites into shared truck trips.

The inventory model charges one delivery per order. In practice, orders for the same
product to sites on the same route on the same day can share a truck, up to the truck's
capacity. This module plans those shared trips from a scenario's simulated orders and
reports how many trips, and how much delivery cost, combining would save.
"""

import csv
import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

from meridian.models import InputError, RunResult, identifier, number

PRODUCTS = ("nitrogen", "oxygen", "argon")
TRIP_FIELDS = (
    "trip",
    "day",
    "route",
    "product",
    "sites",
    "load_kg",
    "capacity_t",
    "utilisation",
    "deliveries",
)


@dataclass(frozen=True)
class Delivery:
    """One simulated order to deliver: day, product-location, quantity (kg) and its cost."""

    day: int
    lane: str
    site: str
    product: str
    quantity_kg: float
    delivery_cost: float


@dataclass(frozen=True)
class Routes:
    """Route groups of nearby sites, truck capacity per product (tonnes) and trip cost."""

    routes: dict[str, tuple[str, ...]]
    capacity_t: dict[str, float]
    trip_cost: float


@dataclass(frozen=True)
class Trip:
    """A truck trip: the deliveries it carries and its load against capacity."""

    day: int
    route: str
    product: str
    deliveries: tuple[Delivery, ...]
    capacity_t: float

    @property
    def load_kg(self) -> float:
        return sum(delivery.quantity_kg for delivery in self.deliveries)

    @property
    def utilisation(self) -> float:
        return self.load_kg / (self.capacity_t * 1000)


def load_routes(path: str | Path) -> Routes:
    """Read routes, truck capacities (tonnes per product) and the cost of one trip (USD)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read routes {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError("Routes file must be a JSON object")
    capacity = data.get("truck_capacity_t")
    if not isinstance(capacity, dict) or set(capacity) != set(PRODUCTS):
        raise InputError("truck_capacity_t must give a capacity for nitrogen, oxygen and argon")
    capacity_t = {
        product: number(capacity[product], f"{product} truck capacity", strict=True)
        for product in PRODUCTS
    }
    raw_routes = data.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise InputError("routes must be a non-empty list")
    routes: dict[str, tuple[str, ...]] = {}
    seen: dict[str, str] = {}
    for raw in raw_routes:
        if not isinstance(raw, dict):
            raise InputError("Each route must be a JSON object")
        route_id = identifier(raw.get("route_id"), "route_id")
        if route_id in routes:
            raise InputError(f"Duplicate route {route_id}")
        sites = raw.get("sites")
        if not isinstance(sites, list) or not sites:
            raise InputError(f"Route {route_id} must list at least one site")
        for site in sites:
            identifier(site, f"{route_id} site")
            if site in seen:
                raise InputError(f"Site {site} is on routes {seen[site]} and {route_id}")
            seen[site] = route_id
        routes[route_id] = tuple(sites)
    return Routes(routes, capacity_t, number(data.get("trip_cost", 0), "trip_cost"))


def deliveries_from_result(result: RunResult, replication: int = 1) -> list[Delivery]:
    """Orders placed in one validation replication, as deliveries to plan."""
    if not 1 <= replication <= result.settings.replications:
        raise InputError(f"replication must be between 1 and {result.settings.replications}")
    deliveries = []
    for lane_result in result.results:
        site, product = lane_result.lane_key.split(":")
        trial = lane_result.validation_trials[replication - 1]
        for period in trial.periods:
            if period.ordered_kg > 1e-9:
                deliveries.append(
                    Delivery(
                        period.day,
                        lane_result.lane_key,
                        site,
                        product,
                        period.ordered_kg,
                        period.delivery_cost,
                    )
                )
    return deliveries


def _best_load(deliveries: list[Delivery], capacity_t: float) -> tuple[Delivery, ...]:
    """The combination of deliveries with the largest total load that fits one truck."""
    best: tuple[Delivery, ...] = ()
    best_load = 0.0
    for size in range(1, len(deliveries) + 1):
        for combination in combinations(deliveries, size):
            load = sum(delivery.quantity_kg for delivery in combination)
            if best_load < load <= capacity_t:
                best, best_load = combination, load
    return best


def _split_oversized(delivery: Delivery, capacity_kg: float) -> list[Delivery]:
    """Split a delivery larger than one truck into full-truck parts plus a remainder."""
    parts = []
    remaining = delivery.quantity_kg
    while remaining > capacity_kg:
        parts.append(
            Delivery(delivery.day, delivery.lane, delivery.site, delivery.product, capacity_kg, 0.0)
        )
        remaining -= capacity_kg
    parts.append(
        Delivery(
            delivery.day,
            delivery.lane,
            delivery.site,
            delivery.product,
            remaining,
            delivery.delivery_cost,
        )
    )
    return parts


def plan_trucks(deliveries: list[Delivery], routes: Routes) -> list[Trip]:
    """Group same-day deliveries of one product on one route into as few trucks as possible.

    Each truck takes the combination of remaining deliveries that fills it most, until all
    deliveries are assigned. Deliveries to sites on no route travel alone. A delivery larger
    than one truck is split into full trucks plus a remainder.
    """
    if not deliveries:
        return
    route_of_site = {site: route for route, sites in routes.routes.items() for site in sites}
    groups: dict[tuple[int, str, str], list[Delivery]] = {}
    for delivery in deliveries:
        route = route_of_site.get(delivery.site, f"direct-{delivery.site}")
        groups.setdefault((delivery.day, route, delivery.product), []).append(delivery)
    trips = []
    for (day, route, product), group in sorted(groups.items()):
        capacity_t = routes.capacity_t[product]
        pending = []
        for delivery in group:
            pending.extend(_split_oversized(delivery, capacity_t))
        while pending:
            load = _best_load(pending, capacity_t) or (pending[0],)
            trips.append(Trip(day, route, product, load, capacity_t))
            for delivery in load:
                pending.remove(delivery)
    return trips


def trip_rows(trips: list[Trip]) -> list[dict]:
    """One CSV row per trip, numbered in day order."""
    rows = []
    for index, trip in enumerate(trips, 1):
        rows.append(
            {
                "trip": index,
                "day": trip.day,
                "route": trip.route,
                "product": trip.product,
                "sites": "+".join(sorted({delivery.site for delivery in trip.deliveries})),
                "load_kg": round(trip.load_kg, 1),
                "capacity_t": trip.capacity_t,
                "utilisation": round(trip.utilisation, 3),
                "deliveries": len(trip.deliveries),
            }
        )
    return rows


def savings(deliveries: list[Delivery], trips: list[Trip], routes: Routes) -> dict:
    """Trips and delivery cost with and without combining (USD)."""
    utilisation = 0.0
    for t in trips:
        utilisation += t.utilisation
    trips_per_day = {}
    for t in sorted({delivery.day for delivery in deliveries}):
        trips_per_day[t] = sum(1 for trip in trips if trip.day == t)
    separate_cost = sum(delivery.delivery_cost for delivery in deliveries)
    combined_cost = len(trips) * routes.trip_cost
    return {
        "deliveries": len(deliveries),
        "trips": len(trips),
        "busiest_day_trips": max(trips_per_day.values(), default=0),
        "mean_utilisation": utilisation / len(trips) if trips else 0.0,
        "separate_delivery_cost": separate_cost,
        "combined_trip_cost": combined_cost,
        "saving": separate_cost - combined_cost,
    }


def write_trips(trips: list[Trip], output: str | Path) -> Path:
    """Write trucks.csv to the output folder and return its path."""
    folder = Path(output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "trucks.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=TRIP_FIELDS)
        writer.writeheader()
        writer.writerows(trip_rows(trips))
    return path
