"""Stockout alerts for a completed run, read from its validation daily results."""

import csv
from pathlib import Path

from meridian.bundles import verify_bundle
from meridian.models import InputError


def _daily_rows(summary_path: str | Path) -> list[dict]:
    """Daily validation rows of a verified bundle."""
    path = Path(summary_path).resolve()
    verify_bundle(path)
    try:
        with (path.parent / "daily_results.csv").open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise InputError(f"Cannot read daily results: {exc}") from exc


def alert_summary(summary_path: str | Path) -> list[dict]:
    """Per lane: days with backlog across all replications and the largest backlog (kg)."""
    lanes: dict[str, dict] = {}
    for row in _daily_rows(summary_path):
        try:
            backlog = float(row["backlog_kg"])
            lane = row["lane"]
        except (KeyError, ValueError) as exc:
            raise InputError(f"Invalid daily result row: {exc}") from exc
        entry = lanes.setdefault(lane, {"lane": lane, "stockout_days": 0, "max_backlog_kg": 0.0})
        if backlog > 0:
            entry["stockout_days"] += 1
            entry["max_backlog_kg"] = max(entry["max_backlog_kg"], backlog)
    return [lanes[lane] for lane in sorted(lanes)]


def alert_history(summary_path: str | Path) -> list[dict]:
    """Every stockout alert raised during the run, one row per lane, replication and day."""
    history = []
    for row in _daily_rows(summary_path):
        try:
            backlog = float(row["backlog_kg"])
            lane = row["lane"]
        except (KeyError, ValueError) as exc:
            raise InputError(f"Invalid daily result row: {exc}") from exc
        if backlog > 0:
            history.append(
                {
                    "lane": lane,
                    "replication": int(row["replication"]),
                    "day": int(row["day"]),
                    "backlog_kg": backlog,
                    "demand_kg": float(row["demand_kg"]),
                }
            )
    return sorted(history, key=lambda item: (item["lane"], item["replication"], item["day"]))


def write_history(history: list[dict], folder: str | Path) -> Path:
    if not Path(folder).is_dir():
        raise InputError(f"Folder {folder} does not exist")
    path = Path(folder) / "alerts_history.csv"
    columns = ["lane", "replication", "day", "backlog_kg", "demand_kg"]
    try:
        with path.open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns)
            writer.writeheader()
            writer.writerows(history)
    except FileExistsError:
        raise InputError(f"alerts_history.csv already exists in {folder}") from None
    return path


def summary_lines(rows: list[dict]) -> list[str]:
    """A fixed-width table of the per-lane alert summary."""
    lines = [f"{'Product-location':<28}{'Stockout days':>14}{'Max backlog (kg)':>18}"]
    for row in rows:
        lines.append(f"{row['lane']:<28}{row['stockout_days']:>14}{row['max_backlog_kg']:>18,.0f}")
    return lines
