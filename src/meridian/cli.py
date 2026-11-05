"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import sys

from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.planning import deterministic_plan, eoq_benchmark, run_scenario
from meridian.reporting import compare_reports, export_run
from meridian.snapshots import (
    STATUS_ORDER,
    diff_csv,
    diff_json,
    diff_snapshots,
    diff_table,
    filter_rows,
    largest_changes,
    load_snapshot,
    product_table,
    product_totals,
    write_diff,
)


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
    snapshot = commands.add_parser(
        "snapshot-diff", help="Compare end-of-horizon inventory between two result bundles"
    )
    snapshot.add_argument("before", help="summary.json of the earlier run")
    snapshot.add_argument("after", help="summary.json of the later run")
    snapshot.add_argument(
        "--format",
        choices=("table", "json", "csv"),
        default="table",
        help="Output format (default: table)",
    )
    snapshot.add_argument(
        "--status",
        action="append",
        choices=STATUS_ORDER,
        help="Only show lanes with this status; repeat to show several",
    )
    snapshot.add_argument(
        "--top",
        type=_positive_int,
        help="Only show this many lanes with the largest inventory change",
    )
    snapshot.add_argument(
        "--by-product",
        action="store_true",
        help="Summarise ending inventory per product instead of per product-location",
    )
    snapshot.add_argument("--save", help="Also write the output to this new file")
    return root


def _positive_int(text: str) -> int:
    """An argparse type for counts that must be at least one."""
    try:
        value = int(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _snapshot_diff(args: argparse.Namespace) -> str:
    """Load both bundles, compare them and render the requested format."""
    before = load_snapshot(args.before)
    after = load_snapshot(args.after)
    rows = filter_rows(diff_snapshots(before, after), tuple(args.status) if args.status else None)
    if args.top is not None:
        rows = largest_changes(rows, args.top)
    if args.by_product:
        if args.format == "json":
            text = json.dumps(product_totals(rows), indent=2, allow_nan=False) + "\n"
        elif args.format == "csv":
            raise InputError("--by-product supports table or json output")
        else:
            text = product_table(rows)
    elif args.format == "json":
        text = diff_json(before, after, rows)
    elif args.format == "csv":
        text = diff_csv(rows)
    else:
        text = diff_table(before, after, rows)
    if args.save:
        write_diff(text, args.save)
    return text


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            print(json.dumps(compare_reports(args.reports), indent=2, allow_nan=False))
            return 0
        if args.command == "snapshot-diff":
            sys.stdout.write(_snapshot_diff(args))
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
