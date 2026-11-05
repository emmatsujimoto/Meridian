"""A local command-line workflow; no accounts, services, or credentials required."""

import argparse
import json
import sys

from meridian.bundles import verify_bundle
from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.planning import deterministic_plan, eoq_benchmark, run_scenario
from meridian.reporting import compare_reports, export_run
from meridian.server import api_key_from_environment, make_server
from meridian.whatif import allocate, allocation_rows, allocation_summary, lane_demands


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
    serve = commands.add_parser("serve", help="Serve completed result bundles over HTTP")
    serve.add_argument("--results", default="results", help="Results folder (default: results)")
    serve.add_argument("--host", default="127.0.0.1", help="Address to listen on")
    serve.add_argument("--port", type=int, default=8765, help="Port to listen on")
    what_if = commands.add_parser(
        "what-if", help="Share proposed plant capacities between a run's product-locations"
    )
    what_if.add_argument("summary", help="summary.json of a completed run")
    what_if.add_argument(
        "--capacity",
        action="append",
        required=True,
        metavar="PRODUCT=KG",
        help="Proposed daily capacity, e.g. nitrogen=1200; repeat for several products",
    )
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "compare":
            print(json.dumps(compare_reports(args.reports), indent=2, allow_nan=False))
            return 0
        if args.command == "what-if":
            capacities = {}
            for item in args.capacity:
                product, _, amount = item.partition("=")
                try:
                    capacities[product] = float(amount)
                except ValueError:
                    raise InputError(
                        f"Capacity must look like nitrogen=1200, not {item!r}"
                    ) from None
            allocations = allocate(lane_demands(verify_bundle(args.summary)), capacities)
            output = {
                "allocations": allocation_rows(allocations),
                "summary": allocation_summary(allocations),
            }
            print(json.dumps(output, indent=2, allow_nan=False))
            return 0
        if args.command == "serve":
            server = make_server(args.results, api_key_from_environment(), args.host, args.port)
            host, port = server.server_address[:2]
            print(f"Serving {args.results} on http://{host}:{port} (Ctrl+C to stop)")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
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
