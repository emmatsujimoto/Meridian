"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import sys

from meridian.inputs import load_lanes, load_settings
from meridian.logging_setup import LEVELS, configure_logging
from meridian.models import InputError
from meridian.planning import deterministic_plan, eoq_benchmark, run_scenario
from meridian.reporting import compare_reports, export_run


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Synthetic industrial-gas inventory planning")
    root.add_argument(
        "--log-level", choices=LEVELS, default="WARNING", help="Lowest level logged to stderr"
    )
    root.add_argument("--log-json", action="store_true", help="Write one JSON object per log event")
    root.add_argument(
        "--log-file", action="store_true", help="Also append log events to meridian.log"
    )
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
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    log = configure_logging(args.log_level, args.log_json, args.log_file)
    log.info("command started", extra={"command": args.command})
    try:
        if args.command == "compare":
            print(json.dumps(compare_reports(args.reports), indent=2, allow_nan=False))
            return 0
        lanes = load_lanes(args.data)
        settings = load_settings(args.config)
        log.info(
            "inputs loaded",
            extra={"lanes": len(lanes), "scenario_id": settings.scenario_id},
        )
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
            log.info("results saved", extra={"destination": str(destination)})
            print(f"Results saved to {destination}")
        return 0
    except (InputError, OSError) as exc:
        log.error("command failed", extra={"command": args.command, "error": str(exc)})
        print(f"Input/output error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
