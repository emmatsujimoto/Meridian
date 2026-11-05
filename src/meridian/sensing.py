"""Demand sensing: adjust each lane's planned daily demand using recent sales.

The planned mean in the lane CSV is the starting forecast. Recent daily sales are applied
in date order with simple exponential smoothing, where alpha weights the newest
observation:

    forecast = alpha * newest sale + (1 - alpha) * previous forecast

A lane with no recent sales keeps its planned mean. The result is a new set of lanes that
can be written to a CSV and used with ``meridian run`` like any other input.
"""

import csv
from dataclasses import dataclass, fields, replace
from datetime import date
from pathlib import Path

from meridian.models import InputError, Lane, number

SALES_COLUMNS = ("date", "site_id", "product", "sales_kg")
MAX_SALES_ROWS = 20_000


@dataclass(frozen=True)
class SensedLane:
    """Planned and sensed daily demand for one product-location."""

    lane: str
    planned_kg: float
    sensed_kg: float
    observations: int
    last_sale: date | None

    @property
    def change(self) -> float:
        """Relative change from plan; positive when recent sales run above plan."""
        return self.sensed_kg / self.planned_kg - 1


def smooth(start: float, observations: list[float], alpha: float) -> float:
    forecast = start
    for value in observations:
        forecast = alpha * forecast + (1 - alpha) * value
    return forecast


def sense_demand(lanes: tuple[Lane, ...], sales_path: str | Path) -> list[SensedLane]:
    """Read recent sales and return planned versus sensed demand for every lane."""
    path = Path(sales_path)
    alpha = 0.3
    keys = {lane.key for lane in lanes}
    history: dict[str, list[tuple[date, float]]] = {key: [] for key in keys}
    try:
        with path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != SALES_COLUMNS:
                raise InputError(f"Sales CSV must have columns {', '.join(SALES_COLUMNS)}")
            seen = set()
            for row_number, row in enumerate(reader, start=2):
                if row_number - 1 > MAX_SALES_ROWS:
                    raise InputError(f"At most {MAX_SALES_ROWS} sales rows are supported")
                if None in row or any(value is None for value in row.values()):
                    raise InputError(f"Sales row {row_number}: missing or extra values")
                key = f"{row['site_id'].strip()}:{row['product'].strip()}"
                if key not in keys:
                    raise InputError(f"Sales row {row_number}: unknown product-location {key}")
                try:
                    day = date.fromisoformat(row["date"].strip())
                    sales = number(row["sales_kg"].strip(), "sales_kg")
                except ValueError as exc:
                    raise InputError(f"Sales row {row_number}: {exc}") from exc
                if (key, day) in seen:
                    raise InputError(f"Sales row {row_number}: duplicate date for {key}")
                seen.add((key, day))
                history[key].append((day, sales))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise InputError(f"Cannot read sales {path}: {exc}") from exc
    results = []
    for lane in sorted(lanes, key=lambda item: item.key):
        observations = sorted(history[lane.key])
        sensed = smooth(lane.daily_mean_kg, [value for _, value in observations], alpha)
        results.append(
            SensedLane(
                lane=lane.key,
                planned_kg=lane.daily_mean_kg,
                sensed_kg=sensed,
                observations=len(observations),
                last_sale=observations[-1][0] if observations else None,
            )
        )
    return results


def adjusted_lanes(lanes: tuple[Lane, ...], sensed: list[SensedLane]) -> tuple[Lane, ...]:
    by_key = {item.lane: item for item in sensed}
    adjusted = []
    for lane in lanes:
        item = by_key.get(lane.key)
        if item is None or item.observations == 0:
            adjusted.append(lane)
            continue
        scale = item.sensed_kg / lane.daily_mean_kg
        adjusted.append(
            replace(
                lane,
                daily_mean_kg=item.sensed_kg,
                daily_sd_kg=lane.daily_sd_kg * scale,
            )
        )
    return tuple(adjusted)


def write_lanes(lanes: tuple[Lane, ...], destination: str | Path) -> Path:
    path = Path(destination)
    columns = [field.name for field in fields(Lane)]
    try:
        with path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(columns)
            for lane in lanes:
                writer.writerow([_csv_value(getattr(lane, column)) for column in columns])
    except FileExistsError:
        raise InputError(f"{path} already exists; choose a new file name") from None
    return path


def _csv_value(value: object) -> str:
    """Numbers without a trailing ``.0`` when whole, so files match hand-written inputs."""
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value)


def sensing_table(sensed: list[SensedLane]) -> str:
    lines = [
        "| Product-location | Planned (kg/day) | Sensed (kg/day) | Change | Days of sales "
        "| Last sale |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in sensed:
        last = item.last_sale.isoformat() if item.last_sale else "-"
        lines.append(
            f"| {item.lane} | {item.planned_kg:,.1f} | {item.sensed_kg:,.1f} "
            f"| {item.change:+.1%} | {item.observations} | {last} |"
        )
    return "\n".join(lines) + "\n"


def sensed_rows(sensed: list[SensedLane]) -> list[dict]:
    return [
        {
            "lane": item.lane,
            "planned_kg": item.planned_kg,
            "sensed_kg": item.sensed_kg,
            "change": item.change,
            "observations": item.observations,
            "last_sale": item.last_sale.isoformat() if item.last_sale else None,
        }
        for item in sensed
    ]


def largest_changes(sensed: list[SensedLane], count: int = 5) -> list[SensedLane]:
    if count < 1:
        raise InputError("count must be at least 1")
    moved = [item for item in sensed if item.observations]
    return sorted(moved, key=lambda item: (-abs(item.change), item.lane))[:count]
