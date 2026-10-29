"""Portable result bundles with separate scenario directories and input fingerprints."""

import csv
import hashlib
import json
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from statistics import fmean, stdev
from uuid import uuid4

from meridian import __version__
from meridian.bundles import verify_bundle
from meridian.models import InputError, RunResult


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile, matching numpy.percentile's default method."""
    ranked = sorted(values, reverse=True)
    index = int(q / 100 * len(ranked))
    return ranked[min(index, len(ranked) - 1)]


def summary(result: RunResult) -> dict:
    """Summaries use mean replicate costs and volume-weighted portfolio service."""
    rows = []
    for lane_result in result.results:
        trials = lane_result.validation_trials
        costs = [t.total_cost for t in trials]
        rows.append(
            {
                "lane": lane_result.lane_key,
                "base_stock_kg": lane_result.chosen_base_stock_kg,
                "training_target_met": lane_result.training_target_met,
                "validation_mean_cost": fmean(costs),
                "validation_cost_sd": stdev(costs) if len(costs) > 1 else 0.0,
                "validation_cost_p50": percentile(costs, 50),
                "validation_cost_p90": percentile(costs, 90),
                "validation_mean_fill_rate": fmean(t.fill_rate for t in trials),
                "validation_target_met": fmean(t.fill_rate for t in trials)
                >= result.settings.service_target,
                "mean_holding_cost": fmean(sum(p.holding_cost for p in t.periods) for t in trials),
                "mean_backlog_cost": fmean(sum(p.backlog_cost for p in t.periods) for t in trials),
                "mean_delivery_cost": fmean(
                    sum(p.delivery_cost for p in t.periods) for t in trials
                ),
                "mean_purchase_cost": fmean(
                    sum(p.purchase_cost for p in t.periods) for t in trials
                ),
                "mean_terminal_inventory_kg": fmean(t.periods[-1].inventory_kg for t in trials),
                "mean_terminal_backlog_kg": fmean(t.periods[-1].backlog_kg for t in trials),
            }
        )
    periods = [p for lr in result.results for t in lr.validation_trials for p in t.periods]
    total_demand = sum(p.demand_kg for p in periods)
    service = sum(p.served_immediately_kg for p in periods) / total_demand if total_demand else 1.0
    inputs = {"settings": asdict(result.settings), "lanes": [asdict(lane) for lane in result.lanes]}
    fingerprint = hashlib.sha256(
        json.dumps(inputs, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "company": "Meridian Industrial Gases (fictional)",
        "scenario_id": result.settings.scenario_id,
        "horizon_days": result.settings.horizon_days,
        "replications": result.settings.replications,
        "currency": "USD",
        "quantity_unit": "kg",
        "total_mean_cost": sum(row["validation_mean_cost"] for row in rows),
        "portfolio_fill_rate": service,
        "input_sha256": fingerprint,
        "lanes": rows,
        "inputs": inputs,
        "model_notes": [
            "Independent product-location inventory streams; no shared fleet constraints.",
            "Backlogged demand; no emergency supply or lost-sales model.",
            "Orders charged when placed, including orders arriving after the horizon.",
            "Existing starting inventory is treated as sunk cost; no terminal salvage credit.",
            "Synthetic costs and demand; results are not operational instructions.",
        ],
    }


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise InputError("Cannot export an empty result table")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def export_run(result: RunResult, output_root: str | Path) -> Path:
    """Create a unique bundle. COMPLETE.json is written only after all exports succeed."""
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    name = f"{result.settings.scenario_id}-{uuid4().hex[:12]}"
    destination = root / name
    destination.mkdir(exist_ok=False)
    report = summary(result)
    (destination / "summary.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    _write_csv(destination / "lanes.csv", report["lanes"])
    candidates = []
    traces = []
    for lane_result in result.results:
        for candidate in lane_result.candidates:
            candidates.append({"lane": lane_result.lane_key, **asdict(candidate)})
        for replication, trial in enumerate(lane_result.validation_trials, 1):
            for period in trial.periods:
                traces.append(
                    {
                        "lane": trial.lane_key,
                        "replication": replication,
                        **asdict(period),
                        "total_cost": period.total_cost,
                    }
                )
    _write_csv(destination / "candidates.csv", candidates)
    _write_csv(destination / "daily_results.csv", traces)
    lines = [
        f"# Scenario: {result.settings.scenario_id}",
        "",
        "Meridian Industrial Gases — fictional internal planning study.",
        "",
        f"Horizon: {result.settings.horizon_days} days. Replications: {result.settings.replications}.",
        f"Mean total cost: ${report['total_mean_cost']:,.2f}.",
        f"Volume-weighted immediate fill rate: {report['portfolio_fill_rate']:.2%}.",
        "",
        "| Product-location | Base stock (kg) | Mean cost (USD) | Mean fill rate | Target met on validation |",
        "|---|---:|---:|---:|---|",
    ]
    for row in report["lanes"]:
        lines.append(
            f"| {row['lane']} | {row['base_stock_kg']:,.0f} | {row['validation_mean_cost']:,.2f} | {row['validation_mean_fill_rate']:.2%} | {row['validation_target_met']} |"
        )
    lines.extend(["", *[f"- {note}" for note in report["model_notes"]], ""])
    (destination / "report.md").write_text("\n".join(lines), encoding="utf-8")
    manifest = {
        "completed_utc": datetime.now(timezone.utc).isoformat(),
        "application_version": __version__,
        "python_version": platform.python_version(),
        "dependency_versions": {
            name: version(name)
            for name in ("numpy", "scipy", "networkx", "jsonpickle", "tabulate", "tqdm")
        },
        "input_sha256": report["input_sha256"],
        "files": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(destination.iterdir())
            if p.is_file()
        },
    }
    (destination / "COMPLETE.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def compare_reports(paths: list[str | Path]) -> list[dict]:
    """Compare only reports with the same cost horizon, currency and lane portfolio."""
    reports = []
    for path in paths:
        try:
            report = verify_bundle(path)
            signature = (
                report["schema_version"],
                report["horizon_days"],
                report["currency"],
                tuple(sorted(row["lane"] for row in report["lanes"])),
            )
            if reports and signature != reports[0][0]:
                raise InputError(
                    "Reports must have matching horizons, currencies and lane portfolios"
                )
            reports.append((signature, report))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise InputError(f"Cannot compare report {path}: {exc}") from exc
    if len(reports) < 2:
        raise InputError("Provide at least two reports")
    return [
        {
            "scenario_id": r["scenario_id"],
            "total_mean_cost": r["total_mean_cost"],
            "portfolio_fill_rate": r["portfolio_fill_rate"],
            "input_sha256": r["input_sha256"],
        }
        for _, r in sorted(reports, key=lambda pair: pair[1]["total_mean_cost"])
    ]
