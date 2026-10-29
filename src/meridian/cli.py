"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import sys

from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.planning import deterministic_plan, eoq_benchmark, run_scenario
from meridian.reporting import compare_reports, export_run


def format_table(rows: list[dict]) -> str:
    """Aligned plain-text table of compared scenarios, lowest total cost first."""
    header = ("Scenario", "Total mean cost (USD)", "Fill rate")
    body = [
        (row["scenario_id"], f"{row['total_mean_cost']:,.2f}", f"{row['portfolio_fill_rate']:.2%}")
        for row in rows
    ]
    widths = [max(len(line[i]) for line in (header, *body)) for i in range(len(header))]
    lines = [
        "  ".join(
            cell.ljust(width) if i == 0 else cell.rjust(width)
            for i, (cell, width) in enumerate(zip(line, widths))
        )
        for line in (header, *body)
    ]
    lines.insert(1, "  ".join("-" * width for width in widths))
    return "\n".join(lines)


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
    compare.add_argument(
        "--format", choices=("json", "table"), default="json", help="Output format"
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            rows = compare_reports(args.reports)
            if args.format == "table":
                print(format_table(rows))
            else:
                print(json.dumps(rows, indent=2, allow_nan=False))
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
