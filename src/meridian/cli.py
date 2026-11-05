"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import sys

from meridian.batching import (
    best_windows,
    compare_windows,
    consolidate_orders,
    orders_from_result,
    totals,
    write_batching,
)
from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.planning import deterministic_plan, eoq_benchmark, run_scenario
from meridian.reporting import compare_reports, export_run


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Synthetic industrial-gas inventory planning")
    commands = root.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate", "Validate input files without running models"),
        ("run", "Compare policies and export independent validation results"),
        ("benchmark", "Calculate EOQ and deterministic lot-sizing benchmarks"),
        ("batching", "Estimate savings from combining orders within a window"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--data", required=True, help="Synthetic product-location CSV")
        command.add_argument("--config", required=True, help="Scenario JSON")
        if name == "batching":
            command.add_argument("--window", type=int, default=3, help="Batching window in days")
            command.add_argument("--replication", type=int, default=1, help="Replication to use")
            command.add_argument("--output", default="results", help="Folder for batching.csv")
            command.add_argument(
                "--compare", type=int, nargs="+", help="Also compare these windows, e.g. 1 3 7"
            )
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
        elif args.command == "batching":
            found = orders_from_result(run_scenario(lanes, settings), args.replication)
            rows = consolidate_orders(found, args.window)
            total = totals(rows)
            path = write_batching(rows, args.output)
            print(
                f"{total['orders']} orders become {total['deliveries']} deliveries; delivery cost "
                f"${total['delivery_cost_before']:,.0f} -> ${total['delivery_cost_after']:,.0f}; "
                f"net saving ${total['net_saving']:,.0f}"
            )
            print(f"Batching estimate saved to {path}")
            if args.compare:
                for row in compare_windows(found, args.compare):
                    print(
                        f"window {row['window_days']} days: {row['deliveries']} deliveries, "
                        f"net saving ${row['net_saving']:,.0f}"
                    )
                for lane, days in best_windows(found, args.compare).items():
                    print(f"best window for {lane}: {days} days")
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
