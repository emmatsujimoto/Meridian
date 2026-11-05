"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import sys

from meridian.demand import demand_traces
from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.planning import (
    compare_policies,
    deterministic_plan,
    eoq_benchmark,
    review_period_sweep,
    run_scenario,
)
from meridian.policies import (
    comparison_table,
    mean_order_kg,
    order_count,
    policy_diagnostics,
    simulate_periodic,
    sweep_table,
)
from meridian.reporting import compare_reports, export_run


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Synthetic industrial-gas inventory planning")
    commands = root.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("validate", "Validate input files without running models"),
        ("run", "Compare policies and export independent validation results"),
        ("benchmark", "Calculate EOQ and deterministic lot-sizing benchmarks"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--data", required=True, help="Synthetic product-location CSV")
        command.add_argument("--config", required=True, help="Scenario JSON")
        if name == "run":
            command.add_argument(
                "--output", default="results", help="Parent folder for unique result bundles"
            )
    compare = commands.add_parser("compare", help="Compare compatible summary.json files")
    compare.add_argument("reports", nargs="+")
    periodic = commands.add_parser(
        "periodic", help="Try one periodic-review (R, s, S) policy on a single lane"
    )
    periodic.add_argument("--data", required=True, help="Synthetic product-location CSV")
    periodic.add_argument("--config", required=True, help="Scenario JSON")
    periodic.add_argument("--lane", required=True, help="Product-location, e.g. Harbor:nitrogen")
    periodic.add_argument(
        "--review-days", type=int, help="Review period R (default: the scenario's)"
    )
    periodic.add_argument("--reorder-point", type=float, required=True, help="s in kg")
    periodic.add_argument("--order-up-to", type=float, required=True, help="S in kg")
    periodic.add_argument(
        "--pack-size", type=float, help="Order in whole packs of this size (default: scenario)"
    )
    for name, help_text in (
        ("compare-policies", "Compare chosen base-stock and periodic-review policies"),
        ("review-sweep", "Choose a periodic-review policy for several review periods"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--data", required=True, help="Synthetic product-location CSV")
        command.add_argument("--config", required=True, help="Scenario JSON")
        command.add_argument(
            "--format", choices=("json", "table"), default="json", help="Output format"
        )
        if name == "review-sweep":
            command.add_argument("--lane", required=True, help="Product-location to study")
            command.add_argument(
                "--periods",
                type=int,
                nargs="+",
                default=[1, 3, 7, 14],
                help="Review periods in days (default: 1 3 7 14)",
            )
    return root


def _periodic(args: argparse.Namespace, lanes, settings) -> dict:
    """Training-sample results of one (R, s, S) policy for one lane."""
    matches = [lane for lane in lanes if lane.key == args.lane]
    if not matches:
        raise InputError(f"No product-location {args.lane!r} in {args.data}")
    lane = matches[0]
    review = args.review_days if args.review_days is not None else settings.review_period_days
    pack = args.pack_size if args.pack_size is not None else settings.pack_size_kg
    trials = [
        simulate_periodic(lane, review, args.reorder_point, args.order_up_to, trace, pack)
        for trace in demand_traces(lane, settings, "training")
    ]
    count = len(trials)
    return {
        "lane": lane.key,
        "review_period_days": review,
        "reorder_point_kg": args.reorder_point,
        "order_up_to_kg": args.order_up_to,
        "pack_size_kg": pack,
        "replications": count,
        "mean_cost": sum(t.total_cost for t in trials) / count,
        "mean_fill_rate": sum(t.fill_rate for t in trials) / count,
        "meets_target": sum(t.fill_rate for t in trials) / count >= settings.service_target,
        "mean_orders": sum(order_count(t) for t in trials) / count,
        "mean_order_kg": sum(mean_order_kg(t) for t in trials) / count,
        "first_trial": policy_diagnostics(trials[0], review),
    }


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            print(json.dumps(compare_reports(args.reports), indent=2, allow_nan=False))
            return 0
        lanes = load_lanes(args.data)
        settings = load_settings(args.config)
        if args.command == "periodic":
            print(json.dumps(_periodic(args, lanes, settings), indent=2, allow_nan=False))
        elif args.command == "compare-policies":
            rows = compare_policies(lanes, settings)
            if args.format == "table":
                print(comparison_table(rows), end="")
            else:
                print(json.dumps(rows, indent=2, allow_nan=False))
        elif args.command == "review-sweep":
            matches = [lane for lane in lanes if lane.key == args.lane]
            if not matches:
                raise InputError(f"No product-location {args.lane!r} in {args.data}")
            rows = review_period_sweep(matches[0], settings, tuple(args.periods))
            if args.format == "table":
                print(sweep_table(rows), end="")
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
