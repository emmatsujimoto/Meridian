"""Compare end-of-horizon inventory between two completed result bundles.

A snapshot is each product-location's mean ending inventory and backlog over the
validation replications, read from a verified bundle's daily_results.csv. Comparing two
snapshots shows where a change of settings or inputs leaves more or less stock behind.
"""

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean

from meridian.bundles import verify_bundle
from meridian.models import InputError


@dataclass(frozen=True)
class LaneSnapshot:
    """One product-location's position at the end of the horizon (kg)."""

    lane: str
    base_stock_kg: float
    ending_inventory_kg: float
    ending_backlog_kg: float

    @property
    def net_position_kg(self) -> float:
        """Ending inventory minus ending backlog."""
        return self.ending_inventory_kg - self.ending_backlog_kg


@dataclass(frozen=True)
class Snapshot:
    """End-of-horizon positions of every lane in one bundle."""

    scenario_id: str
    horizon_days: int
    input_sha256: str
    lanes: tuple[LaneSnapshot, ...]


def _ending_positions(daily_path: Path, horizon_days: int) -> dict[str, tuple[float, float]]:
    try:
        with daily_path.open(newline="", encoding="utf-8") as stream:
            rows = [row for row in csv.DictReader(stream) if int(row["day"]) == horizon_days]
    except (OSError, UnicodeError, csv.Error, KeyError, ValueError) as exc:
        raise InputError(f"Cannot read {daily_path.name}: {exc}") from exc
    by_lane: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        try:
            values = (float(row["inventory_kg"]), float(row["backlog_kg"]))
        except (KeyError, ValueError) as exc:
            raise InputError(f"Invalid ending position in {daily_path.name}") from exc
        by_lane.setdefault(row["lane"], []).append(values)
    return {
        lane: (fmean(v[0] for v in values), fmean(v[1] for v in values))
        for lane, values in by_lane.items()
    }


def load_snapshot(summary_path: str | Path) -> Snapshot:
    path = Path(summary_path)
    try:
        report = verify_bundle(path)
        signature = (
            report["schema_version"],
            report["horizon_days"],
            report["currency"],
            tuple(sorted(row["lane"] for row in report["lanes"])),
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise InputError(f"Cannot read snapshot {path}: {exc}") from exc
    if signature[2] != "USD":
        raise InputError("Snapshots must use USD reports")
    positions = _ending_positions(
        path.resolve().parent / "daily_results.csv", report["horizon_days"]
    )
    lanes = []
    for row in report["lanes"]:
        if row["lane"] not in positions:
            raise InputError(f"daily_results.csv has no final day for {row['lane']}")
        inventory, backlog = positions[row["lane"]]
        lanes.append(LaneSnapshot(row["lane"], float(row["base_stock_kg"]), inventory, backlog))
    return Snapshot(
        report["scenario_id"], report["horizon_days"], report["input_sha256"], tuple(lanes)
    )


def diff_snapshots(before: Snapshot, after: Snapshot) -> list[dict]:
    if before.horizon_days != after.horizon_days:
        raise InputError("Snapshots must cover the same horizon to be compared")
    rows = []
    for old in before.lanes:
        new = None
        for candidate in after.lanes:
            if candidate.lane == old.lane:
                new = candidate
        if new is None:
            rows.append(_row(old.lane, old, None, "removed"))
            continue
        for field in ("ending_inventory_kg", "ending_backlog_kg", "base_stock_kg"):
            old_value = getattr(old, field)
            new_value = getattr(new, field)
            if abs(new_value - old_value) > 0.01:
                if field == "ending_inventory_kg":
                    if new_value > old_value:
                        status = "more stock"
                    else:
                        status = "less stock"
                    break
                status = "changed"
                break
        else:
            status = "unchanged"
        rows.append(_row(old.lane, old, new, status))
    for new in after.lanes:
        found = False
        for old in before.lanes:
            if old.lane == new.lane:
                found = True
        if not found:
            rows.append(_row(new.lane, None, new, "added"))
    return sorted(rows, key=lambda row: row["lane"])


def _row(lane: str, old: LaneSnapshot | None, new: LaneSnapshot | None, status: str) -> dict:
    """One comparison row; missing sides are reported as None."""

    def value(item, field):
        return None if item is None else getattr(item, field)

    before_inventory = value(old, "ending_inventory_kg")
    after_inventory = value(new, "ending_inventory_kg")
    change = (
        None
        if before_inventory is None or after_inventory is None
        else after_inventory - before_inventory
    )
    return {
        "lane": lane,
        "status": status,
        "base_stock_before_kg": value(old, "base_stock_kg"),
        "base_stock_after_kg": value(new, "base_stock_kg"),
        "inventory_before_kg": before_inventory,
        "inventory_after_kg": after_inventory,
        "inventory_change_kg": change,
        "backlog_before_kg": value(old, "ending_backlog_kg"),
        "backlog_after_kg": value(new, "ending_backlog_kg"),
    }


def diff_totals(rows: list[dict]) -> dict:
    return {
        "lanes": len(rows),
        "more_stock": sum(row["status"] == "more stock" for row in rows),
        "less_stock": sum(row["status"] == "less stock" for row in rows),
        "changed": sum(row["status"] == "changed" for row in rows),
        "unchanged": sum(row["status"] == "unchanged" for row in rows),
        "added": sum(row["status"] == "added" for row in rows),
        "removed": sum(row["status"] == "removed" for row in rows),
        "inventory_change_kg": sum(row["inventory_change_kg"] or 0.0 for row in rows),
    }


STATUS_ORDER = ("less stock", "more stock", "changed", "added", "removed", "unchanged")

COLUMNS = (
    "lane",
    "status",
    "base_stock_before_kg",
    "base_stock_after_kg",
    "inventory_before_kg",
    "inventory_after_kg",
    "inventory_change_kg",
    "backlog_before_kg",
    "backlog_after_kg",
)


def filter_rows(rows: list[dict], statuses: tuple[str, ...] | None = None) -> list[dict]:
    """Keep only rows whose status is listed; ``None`` keeps every row."""
    if statuses is None:
        return list(rows)
    unknown = sorted(set(statuses) - set(STATUS_ORDER))
    if unknown:
        raise InputError(f"Unknown snapshot status: {', '.join(unknown)}")
    return [row for row in rows if row["status"] in statuses]


def largest_changes(rows: list[dict], count: int) -> list[dict]:
    """Rows with the largest absolute inventory change first; added and removed lanes last."""
    if count < 1:
        raise InputError("count must be at least 1")
    known = [row for row in rows if row["inventory_change_kg"] is not None]
    known.sort(key=lambda row: (-abs(row["inventory_change_kg"]), row["lane"]))
    return known[:count]


def _format_kg(value: float | None) -> str:
    """Whole kilograms with thousands separators, or a dash when a side is missing."""
    return "-" if value is None else f"{value:,.0f}"


def _format_change(value: float | None) -> str:
    """Signed whole kilograms, or a dash when either side is missing."""
    return "-" if value is None else f"{value:+,.0f}"


def diff_table(before: Snapshot, after: Snapshot, rows: list[dict]) -> str:
    """A Markdown table of the comparison, ready to paste into a planning note."""
    totals = diff_totals(rows)
    lines = [
        f"# Inventory snapshot comparison: {before.scenario_id} -> {after.scenario_id}",
        "",
        f"Horizon: {before.horizon_days} days. Lanes compared: {totals['lanes']}.",
        f"Net change in ending inventory: {_format_change(totals['inventory_change_kg'])} kg.",
        "",
        "| Product-location | Status | Base stock before | Base stock after "
        "| Ending inventory before | Ending inventory after | Change (kg) "
        "| Backlog before | Backlog after |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row["lane"],
                    row["status"],
                    _format_kg(row["base_stock_before_kg"]),
                    _format_kg(row["base_stock_after_kg"]),
                    _format_kg(row["inventory_before_kg"]),
                    _format_kg(row["inventory_after_kg"]),
                    _format_change(row["inventory_change_kg"]),
                    _format_kg(row["backlog_before_kg"]),
                    _format_kg(row["backlog_after_kg"]),
                ]
            )
            + " |"
        )
    lines.extend(["", "| Status | Lanes |", "|---|---:|"])
    for status in STATUS_ORDER:
        key = status.replace(" ", "_")
        lines.append(f"| {status} | {totals[key]} |")
    return "\n".join(lines) + "\n"


def diff_csv(rows: list[dict]) -> str:
    """The comparison rows as CSV text with a fixed column order."""
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: "" if row[key] is None else row[key] for key in COLUMNS})
    return stream.getvalue()


def diff_json(before: Snapshot, after: Snapshot, rows: list[dict]) -> str:
    """The comparison as JSON, including both bundles' input fingerprints."""
    document = {
        "before": {
            "scenario_id": before.scenario_id,
            "input_sha256": before.input_sha256,
        },
        "after": {
            "scenario_id": after.scenario_id,
            "input_sha256": after.input_sha256,
        },
        "horizon_days": before.horizon_days,
        "totals": diff_totals(rows),
        "lanes": rows,
    }
    return json.dumps(document, indent=2, allow_nan=False) + "\n"


def write_diff(text: str, destination: str | Path) -> Path:
    """Write a rendered comparison without replacing an existing file."""
    path = Path(destination)
    if path.exists():
        raise InputError(f"{path} already exists; choose a new file name")
    if not path.parent.is_dir():
        raise InputError(f"Folder {path.parent} does not exist")
    path.write_text(text, encoding="utf-8")
    return path


def product_totals(rows: list[dict]) -> list[dict]:
    """Sum ending inventory and backlog per product across all sites.

    Lanes present on only one side contribute to that side's totals, so added and removed
    sites show up as a change for their product.
    """
    totals: dict[str, dict] = {}
    for row in rows:
        product = row["lane"].rsplit(":", 1)[-1]
        entry = totals.setdefault(
            product,
            {
                "product": product,
                "lanes": 0,
                "inventory_before_kg": 0.0,
                "inventory_after_kg": 0.0,
                "backlog_before_kg": 0.0,
                "backlog_after_kg": 0.0,
            },
        )
        entry["lanes"] += 1
        for key in (
            "inventory_before_kg",
            "inventory_after_kg",
            "backlog_before_kg",
            "backlog_after_kg",
        ):
            entry[key] += row[key] or 0.0
    result = []
    for product in sorted(totals):
        entry = totals[product]
        entry["inventory_change_kg"] = entry["inventory_after_kg"] - entry["inventory_before_kg"]
        entry["backlog_change_kg"] = entry["backlog_after_kg"] - entry["backlog_before_kg"]
        result.append(entry)
    return result


def product_table(rows: list[dict]) -> str:
    """A Markdown table of per-product totals."""
    lines = [
        "| Product | Lanes | Ending inventory before | Ending inventory after | Change (kg) "
        "| Backlog change (kg) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for entry in product_totals(rows):
        lines.append(
            f"| {entry['product']} | {entry['lanes']} "
            f"| {_format_kg(entry['inventory_before_kg'])} "
            f"| {_format_kg(entry['inventory_after_kg'])} "
            f"| {_format_change(entry['inventory_change_kg'])} "
            f"| {_format_change(entry['backlog_change_kg'])} |"
        )
    return "\n".join(lines) + "\n"
