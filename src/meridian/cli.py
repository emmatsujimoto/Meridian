"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import sys

from meridian.alerts import SEVERITIES, compare_alerts, filter_alerts, load_alerts
from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.notify import build_message, render_markdown, render_text
from meridian.planning import deterministic_plan, eoq_benchmark, run_scenario
from meridian.reporting import compare_reports, export_run
from meridian.teams import WEBHOOK_ENV, build_card, send_alerts, webhook_url


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
    notify = commands.add_parser("notify", help="Show or send service alerts for a run")
    notify.add_argument("summary", help="summary.json of a completed run")
    notify.add_argument(
        "--min-severity",
        choices=SEVERITIES,
        default="minor",
        help="Leave out alerts below this severity (default: minor, all alerts)",
    )
    notify.add_argument(
        "--since", help="summary.json of an earlier run; also show how alerts changed"
    )
    notify.add_argument(
        "--markdown", action="store_true", help="Print Markdown instead of plain text"
    )
    notify.add_argument(
        "--teams", action="store_true", help=f"Post the alerts to Teams using {WEBHOOK_ENV}"
    )
    notify.add_argument(
        "--dry-run",
        action="store_true",
        help="With --teams, print the Teams card as JSON instead of posting it",
    )
    notify.add_argument(
        "--skip-empty",
        action="store_true",
        help="With --teams, do not post when there are no alerts",
    )
    return root


def _notify(args: argparse.Namespace) -> int:
    """Handle ``meridian notify``."""
    report, alerts = load_alerts(args.summary)
    alerts = filter_alerts(alerts, args.min_severity)
    changes = None
    if args.since:
        _, previous = load_alerts(args.since)
        changes = compare_alerts(filter_alerts(previous, args.min_severity), alerts)
    if not args.teams:
        render = render_markdown if args.markdown else render_text
        print(render(build_message(report, alerts), changes), end="")
        return 0
    if args.dry_run:
        print(json.dumps(build_card(report, alerts, changes), indent=2))
        return 0
    if args.skip_empty and not alerts:
        print("No alerts; nothing posted to Teams")
        return 0
    url = webhook_url()
    status = send_alerts(report, alerts, url, changes)
    print(f"Posted {len(alerts)} alerts to Teams (HTTP {status})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            print(json.dumps(compare_reports(args.reports), indent=2, allow_nan=False))
            return 0
        if args.command == "notify":
            return _notify(args)
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
