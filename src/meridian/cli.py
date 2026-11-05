"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import sys

from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.planning import deterministic_plan, eoq_benchmark, run_scenario
from meridian.reporting import compare_reports, export_run
from meridian.scenario_diff import MISSING as MISSING_VALUE
from meridian.scenario_diff import diff_settings, setting_changes


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
    scenario_diff = commands.add_parser(
        "scenario-diff", help="List settings that differ between two scenario files"
    )
    scenario_diff.add_argument("before", help="First scenario JSON")
    scenario_diff.add_argument("after", help="Second scenario JSON")
    scenario_diff.add_argument(
        "--ignore", action="append", default=[], help="Leave out this setting; repeatable"
    )
    scenario_diff.add_argument(
        "--json", action="store_true", help="Print the changes as a JSON list"
    )
    scenario_diff.add_argument(
        "--exit-code",
        action="store_true",
        help="Exit with status 1 when the scenarios differ, like diff",
    )
    return root


def _scenario_diff(args: argparse.Namespace) -> int:
    """Handle ``meridian scenario-diff``."""
    lines = diff_settings(args.before, args.after, tuple(args.ignore))
    if args.json:
        shown = {line.split(":")[0] for line in lines}
        rows = [
            {"setting": change.path, "kind": change.kind}
            | {
                side: None if value is MISSING_VALUE else value
                for side, value in (("before", change.before), ("after", change.after))
            }
            for change in setting_changes(args.before, args.after)
            if change.path in shown
        ]
        print(json.dumps(rows, indent=2))
    elif lines:
        print("\n".join(lines))
    else:
        print("No differences")
    return 1 if args.exit_code and lines else 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            print(json.dumps(compare_reports(args.reports), indent=2, allow_nan=False))
            return 0
        if args.command == "scenario-diff":
            return _scenario_diff(args)
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
