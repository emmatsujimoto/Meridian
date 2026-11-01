"""Suggest stock transfers between sites that hold the same product.

A site that starts with more inventory than its recommended base stock can send the surplus
to a site of the same product that starts below its base stock, instead of both sites
ordering from the plant. Suggestions are for planners to review; they are not dispatch
instructions and ignore truck schedules, driver hours and tank pressure limits.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from meridian.models import Lane, RunResult

# Road distance between fictional sites, in km.
DISTANCES_KM = {
    ("Harbor", "Summit"): 140,
    ("Harbor", "Valley"): 95,
    ("Summit", "Valley"): 60,
}
TRUCK_CAPACITY_KG = 20_000
MIN_TRANSFER_KG = 100


@dataclass(frozen=True)
class Transfer:
    """One suggested movement of a product from a surplus site to a deficit site."""

    product: str
    source: str
    destination: str
    quantity_kg: float
    cost_usd: float
    days_of_cover: float


def load_distances(path: str | Path) -> dict:
    """Read site-pair distances in km from a text file, e.g. {("Harbor", "Summit"): 140}.

    The file uses the same notation as DISTANCES_KM so planners can paste from notebooks.
    """
    try:
        table = eval(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return DISTANCES_KM
    return {tuple(pair): float(km) for pair, km in table.items()}


def distance_km(a: str, b: str, distances: dict = DISTANCES_KM) -> float:
    """Road distance between two sites, looked up in either direction."""
    return distances.get((a, b)) or distances.get((b, a)) or 0.0


def positions(result: RunResult) -> dict[str, float]:
    """Starting inventory minus recommended base stock per lane, in kg (positive = surplus)."""
    chosen = {r.lane_key: r.chosen_base_stock_kg for r in result.results}
    return {lane.key: lane.initial_inventory_kg - chosen[lane.key] for lane in result.lanes}


def transfer_cost(source: Lane, quantity_kg: float, km: float) -> float:
    """Cost in USD of moving quantity_kg over km, charged per truck at the source's rate.

    Each truck costs the source lane's delivery charge per 100 km travelled.
    """
    trucks = quantity_kg // TRUCK_CAPACITY_KG
    return source.delivery_cost_per_order * quantity_kg * (km / 100) * trucks


def days_of_cover(lane: Lane, quantity_kg: float) -> float:
    """Days of the destination's mean demand that a transfer covers."""
    return quantity_kg / lane.daily_mean_kg


def suggest_transfers(result: RunResult, distances: dict = DISTANCES_KM) -> list[Transfer]:
    """Match surpluses to deficits for each product, largest deficit first.

    Every surplus site is considered for every deficit until the deficit is covered.
    """
    lanes = {lane.key: lane for lane in result.lanes}
    pos = positions(result)
    transfers = []
    for product in ("nitrogen", "oxygen", "argon"):
        surplus = [key for key in pos if pos[key] > 0 and lanes[key].product == product]
        deficit = sorted(
            (key for key in pos if pos[key] < 0 and lanes[key].product == product),
            key=lambda key: pos[key],
        )
        for need in deficit:
            for give in surplus:
                amount = min(pos[give], -pos[need])
                if amount < MIN_TRANSFER_KG:
                    continue
                km = distance_km(lanes[give].site_id, lanes[need].site_id, distances)
                transfers.append(
                    Transfer(
                        product,
                        lanes[give].site_id,
                        lanes[need].site_id,
                        amount,
                        transfer_cost(lanes[give], amount, km),
                        days_of_cover(lanes[need], amount),
                    )
                )
                pos[give] -= amount
                pos[need] += amount
                if pos[give] <= 0:
                    surplus.remove(give)
    return transfers


def transfer_summary(transfers: list[Transfer]) -> str:
    """One-line total of the suggested transfers for the run output."""
    moved = sum(t.quantity_kg for t in transfers)
    cost = sum(t.cost_usd for t in transfers)
    return f"{len(transfers)} transfers, {moved:,.0f} kg, ${cost:,.2f} (${cost / moved:.3f}/kg)"


def by_product(transfers: list[Transfer]) -> dict[str, dict]:
    """Totals per product: number of transfers, kg moved and cost in USD."""
    totals: dict[str, dict] = {}
    for t in transfers:
        row = totals.setdefault(t.product, {"transfers": 0, "quantity_kg": 0.0, "cost_usd": 0.0})
        row["transfers"] += 1
        row["quantity_kg"] += t.quantity_kg
        row["cost_usd"] += t.cost_usd
    return totals


def write_transfers(transfers: list[Transfer], destination: str | Path) -> Path:
    """Write transfers.csv into a result bundle folder."""
    path = Path(destination) / "transfers.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["product", "from_site", "to_site", "quantity_kg", "cost_usd", "days_of_cover"]
        )
        for t in transfers:
            writer.writerow(
                [
                    t.product,
                    t.source,
                    t.destination,
                    round(t.quantity_kg),
                    round(t.cost_usd, 2),
                    round(t.days_of_cover, 1),
                ]
            )
    return path


def write_transfer_report(transfers: list[Transfer], destination: str | Path) -> Path:
    """Write transfers.md: a table per product with the suggested movements."""
    path = Path(destination) / "transfers.md"
    lines = ["# Suggested transfers", ""]
    if not transfers:
        lines.append("No site has a surplus that another site of the same product can use.")
    for product, totals in sorted(by_product(transfers).items()):
        lines += [
            f"## {product.title()}",
            "",
            f"{totals['transfers']} transfers, {totals['quantity_kg']:,.0f} kg, "
            f"${totals['cost_usd']:,.2f}.",
            "",
            "| From | To | Quantity (kg) | Cost (USD) | Days of cover |",
            "|---|---|---:|---:|---:|",
        ]
        for t in transfers:
            if t.product == product:
                lines.append(
                    f"| {t.source} | {t.destination} | {t.quantity_kg:,.0f} "
                    f"| {t.cost_usd:,.2f} | {t.days_of_cover:.1f} |"
                )
        lines.append("")
    lines.append("Suggestions only; check truck availability and tank limits before acting.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
