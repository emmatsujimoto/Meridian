"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import sys

from meridian.disruptions import (
    outage_schedule,
    outage_summary,
    schedule_statistics,
    write_schedules,
)
from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.planning import (
    deterministic_plan,
    disruption_impact,
    eoq_benchmark,
    impact_table,
    outage_stress_test,
    run_scenario,
    stock_for_outage,
    stress_table,
)
from meridian.reporting import compare_reports, export_run


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Synthetic industrial-gas inventory planning")
    commands = root.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate", "Validate input files without running models"),
        ("run", "Compare policies and export independent validation results"),
        ("benchmark", "Calculate EOQ and deterministic lot-sizing benchmarks"),
        ("outages", "Show the supplier outage schedules a scenario would simulate"),
        ("disruption-impact", "Compare results with and without supplier outages"),
        ("outage-stress", "Test one stock level against fixed outages of several lengths"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--data", required=True, help="Synthetic product-location CSV")
        command.add_argument("--config", required=True, help="Scenario JSON")
        if name == "outages":
            command.add_argument("--lane", required=True, help="Product-location to show")
            command.add_argument(
                "--phase", choices=("training", "validation"), default="validation"
            )
            command.add_argument(
                "--summary", action="store_true", help="Only show statistics across replications"
            )
            command.add_argument(
                "--csv", help="Write every lane's schedules to this new CSV instead"
            )
        if name in {"disruption-impact", "outage-stress"}:
            command.add_argument(
                "--format", choices=("json", "table"), default="json", help="Output format"
            )
        if name == "outage-stress":
            command.add_argument("--lane", required=True, help="Product-location to test")
            command.add_argument(
                "--base-stock", type=float, help="Stock level kg to test (or use --find-stock)"
            )
            command.add_argument(
                "--days", type=int, nargs="+", default=[1, 3, 5, 10], help="Outage lengths"
            )
            command.add_argument("--start-day", type=int, default=1, help="First outage day")
            command.add_argument(
                "--find-stock",
                action="store_true",
                help="Find the lowest stock level meeting the target for each outage length",
            )
        if name == "run":
            command.add_argument(
                "--output", default="results", help="Parent folder for unique result bundles"
            )
    compare = commands.add_parser("compare", help="Compare compatible summary.json files")
    compare.add_argument("reports", nargs="+")
    return root


def _find_lane(args: argparse.Namespace, lanes):
    """The lane named by ``--lane``, or a clear error."""
    matches = [lane for lane in lanes if lane.key == args.lane]
    if not matches:
        raise InputError(f"No product-location {args.lane!r} in {args.data}")
    return matches[0]


def _outages(args: argparse.Namespace, lanes, settings) -> list[dict]:
    """Outage schedule and summary for each replication of one lane."""
    lane = _find_lane(args, lanes)
    rows = []
    for replication in range(settings.replications):
        outages, _ = outage_schedule(settings, lane, args.phase, replication)
        rows.append(
            {
                "replication": replication + 1,
                "outages": [
                    {"first_day": o.start_day + 1, "days": o.duration_days} for o in outages
                ],
                "summary": outage_summary(outages, settings.horizon_days),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            print(json.dumps(compare_reports(args.reports), indent=2, allow_nan=False))
            return 0
        lanes = load_lanes(args.data)
        settings = load_settings(args.config)
        if args.command == "outages":
            if args.csv:
                path, count = write_schedules(settings, lanes, args.phase, args.csv)
                print(f"{count} outages written to {path}")
            elif args.summary:
                lane = _find_lane(args, lanes)
                print(json.dumps(schedule_statistics(settings, lane, args.phase), indent=2))
            else:
                print(json.dumps(_outages(args, lanes, settings), indent=2))
        elif args.command == "disruption-impact":
            rows = disruption_impact(lanes, settings)
            if args.format == "table":
                print(impact_table(rows), end="")
            else:
                print(json.dumps(rows, indent=2, allow_nan=False))
        elif args.command == "outage-stress":
            lane = _find_lane(args, lanes)
            if args.find_stock:
                rows = [
                    stock_for_outage(lane, settings, days, args.start_day)
                    for days in sorted(set(args.days))
                ]
                print(json.dumps(rows, indent=2, allow_nan=False))
                return 0
            if args.base_stock is None:
                raise InputError("Provide --base-stock, or --find-stock to search for one")
            rows = outage_stress_test(
                lane, settings, args.base_stock, tuple(args.days), args.start_day
            )
            if args.format == "table":
                print(stress_table(rows), end="")
            else:
                print(json.dumps(rows, indent=2, allow_nan=False))
        elif args.command == "validate":
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
