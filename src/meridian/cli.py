"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import csv
import json
import sys
from pathlib import Path

from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.planning import (
    compare_rolling,
    deterministic_plan,
    eoq_benchmark,
    level_changes,
    rolling_schedule,
    run_scenario,
)
from meridian.reporting import compare_reports, export_run


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Synthetic industrial-gas inventory planning")
    commands = root.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate", "Validate input files without running models"),
        ("run", "Compare policies and export independent validation results"),
        ("benchmark", "Calculate EOQ and deterministic lot-sizing benchmarks"),
        ("rolling", "Compare static base stock with rolling re-planning"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--data", required=True, help="Synthetic product-location CSV")
        command.add_argument("--config", required=True, help="Scenario JSON")
        if name == "rolling":
            command.add_argument(
                "--review-days", type=int, default=7, help="Days between re-plans (default 7)"
            )
            command.add_argument("--output", default="results", help="Folder for rolling.csv")
        if name == "run":
            command.add_argument(
                "--output", default="results", help="Parent folder for unique result bundles"
            )
    compare = commands.add_parser("compare", help="Compare compatible summary.json files")
    compare.add_argument("reports", nargs="+")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            print(json.dumps(compare_reports(args.reports), indent=2, allow_nan=False))
            return 0
        lanes = load_lanes(args.data)
        settings = load_settings(args.config)
        if args.command == "validate":
            print(f"Valid: {len(lanes)} product-location rows; scenario={settings.scenario_id}")
        elif args.command == "benchmark":
            rows = []
            for lane in lanes:
                demands = (lane.daily_mean_kg * settings.demand_multiplier,) * settings.horizon_days
                rows.append(
                    {
                        "eoq": eoq_benchmark(lane, settings.demand_multiplier),
                        "deterministic": deterministic_plan(lane, demands),
                    }
                )
            print(json.dumps(rows, indent=2, allow_nan=False))
        elif args.command == "rolling":
            rows = compare_rolling(lanes, settings, args.review_days)
            folder = Path(args.output).resolve()
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / "rolling.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            for row in rows:
                print(
                    f"{row['lane']}: static ${row['static_mean_cost']:,.0f} "
                    f"({row['static_fill_rate']:.1%}), rolling ${row['rolling_mean_cost']:,.0f} "
                    f"({row['rolling_fill_rate']:.1%})"
                )
            changes = level_changes(rolling_schedule(lanes, settings, args.review_days))
            with (folder / "rolling_plan.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(changes[0]))
                writer.writeheader()
                writer.writerows(changes)
            print(f"Comparison saved to {folder / 'rolling.csv'}")
            print(f"Base-stock changes (replication 1) saved to {folder / 'rolling_plan.csv'}")
        else:
            result = run_scenario(lanes, settings)
            destination = export_run(result, args.output)
            print(f"Results saved to {destination}")
        return 0
    except (InputError, OSError) as exc:
        print(f"Input/output error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
