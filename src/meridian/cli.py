"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import sys

from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.planning import deterministic_plan, eoq_benchmark, run_scenario
from meridian.plugins import describe_models, getModel, preview_models, preview_table
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
    models = commands.add_parser("models", help="List built-in and plugin demand models")
    models.add_argument("--json", action="store_true", help="Print the list as JSON")
    models.add_argument(
        "--preview",
        nargs="*",
        metavar="MODEL",
        help="Show draw statistics for these models, or for all models when none are named",
    )
    models.add_argument("--mean", type=float, default=100.0, help="Daily mean kg for --preview")
    models.add_argument("--sd", type=float, default=20.0, help="Daily deviation kg for --preview")
    models.add_argument("--days", type=int, default=365, help="Days to draw for --preview")
    return root


def _models_text(rows: list[dict]) -> str:
    """Aligned name, source and description columns for the models command."""
    width = max(len(row["name"]) for row in rows)
    source_width = max(len(row["source"]) for row in rows)
    return "\n".join(
        f"{row['name']:<{width}}  {row['source']:<{source_width}}  {row['description']}"
        for row in rows
    )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            print(json.dumps(compare_reports(args.reports), indent=2, allow_nan=False))
            return 0
        if args.command == "models" and args.preview is not None:
            rows = preview_models(args.preview, args.mean, args.sd, days=args.days)
            print(json.dumps(rows, indent=2) if args.json else preview_table(rows))
            return 0
        if args.command == "models":
            rows = describe_models()
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                print(_models_text(rows))
            return 0
        lanes = load_lanes(args.data)
        settings = load_settings(args.config)
        model = getModel(settings.demand_model)
        if args.command == "validate":
            print(
                f"Valid: {len(lanes)} product-location rows; scenario={settings.scenario_id}; "
                f"demand model={model.name} ({model.source})"
            )
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
