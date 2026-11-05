"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import logging
import sys

from meridian.backup import backup, remote_bundles, restore, write_log
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
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--data", required=True, help="Synthetic product-location CSV")
        command.add_argument("--config", required=True, help="Scenario JSON")
        if name == "run":
            command.add_argument(
                "--output", default="results", help="Parent folder for unique result bundles"
            )
    backup_command = commands.add_parser(
        "backup", help="Copy completed bundles to Azure Blob Storage"
    )
    backup_command.add_argument("--output", default="results", help="Folder holding result bundles")
    backup_command.add_argument(
        "--dry-run", action="store_true", help="List the bundles that would be uploaded"
    )
    backup_command.add_argument(
        "--list", action="store_true", help="List the bundles already in the backup container"
    )
    backup_command.add_argument(
        "--bundle", action="append", help="Back up only this bundle folder (repeatable)"
    )
    restore_command = commands.add_parser("restore", help="Download a bundle from the backup")
    restore_command.add_argument("bundle", help="Bundle folder name, e.g. baseline-0123456789ab")
    restore_command.add_argument("--output", default="results", help="Folder to restore into")
    compare = commands.add_parser("compare", help="Compare compatible summary.json files")
    compare.add_argument("reports", nargs="+")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            print(json.dumps(compare_reports(args.reports), indent=2, allow_nan=False))
            return 0
        if args.command == "backup":
            logging.basicConfig(level=logging.INFO, format="%(message)s")
            if args.list:
                for name in remote_bundles():
                    print(name)
                return 0
            report = backup(args.output, dry_run=args.dry_run, only=args.bundle)
            if not args.dry_run:
                write_log(args.output, report)
            verb = "Would upload" if args.dry_run else "Uploaded"
            print(f"{verb} {report.files} files from {len(report.bundles)} bundles")
            for name in report.skipped:
                print(f"Skipped {name}: failed verification", file=sys.stderr)
            return 0
        if args.command == "restore":
            print(f"Restored and verified {restore(args.bundle, args.output)}")
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
