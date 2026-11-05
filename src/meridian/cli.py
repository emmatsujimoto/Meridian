"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import sys

from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.planning import deterministic_plan, eoq_benchmark, run_scenario
from meridian.reporting import compare_reports, export_run
from meridian.templates import describe_templates, template_names, write_scenario


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
    new = commands.add_parser("new-scenario", help="Write starter scenario files to edit")
    new.add_argument("scenario_id", nargs="?", help="Name of the new scenario")
    new.add_argument(
        "--template",
        default="quickstart",
        choices=template_names(),
        help="Starting point (default: quickstart)",
    )
    new.add_argument("--folder", default=".", help="Where to write the files (default: .)")
    new.add_argument("--horizon", type=int, help="Override the template's horizon_days")
    new.add_argument("--replications", type=int, help="Override the template's replications")
    new.add_argument("--force", action="store_true", help="Replace files that already exist")
    new.add_argument("--list", action="store_true", help="List the available templates")
    return root


def _new_scenario(args: argparse.Namespace) -> int:
    """Handle ``meridian new-scenario``."""
    if args.list:
        for row in describe_templates():
            print(
                f"{row['name']:<12} {row['lanes']} lanes, {row['horizon_days']} days. "
                f"{row['description']}"
            )
        return 0
    if not args.scenario_id:
        print("Provide a scenario name, or --list to see templates", file=sys.stderr)
        return 2
    overrides = {
        key: value
        for key, value in (("horizon_days", args.horizon), ("replications", args.replications))
        if value is not None
    }
    written = write_scenario(args.scenario_id, args.folder, args.template, args.force, overrides)
    for path in written["replaced"]:
        print(f"Replaced {path}")
    print(f"Settings: {written['settings']}")
    print(f"Lanes:    {written['lanes']}")
    print(f"Next: meridian validate --data {written['lanes']} --config {written['settings']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            print(json.dumps(compare_reports(args.reports), indent=2, allow_nan=False))
            return 0
        if args.command == "new-scenario":
            return _new_scenario(args)
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
