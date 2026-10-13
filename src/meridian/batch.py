"""Run several scenario files against one input CSV and index the completed bundles."""

import csv
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from meridian.bundles import verify_bundle
from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError

RESULT_PREFIX = "Results saved to "


@dataclass(frozen=True)
class BatchEntry:
    """One scenario run inside a batch, with the bundle it produced."""

    config: Path
    scenario_id: str
    bundle: Path
    total_mean_cost: float
    portfolio_fill_rate: float


def discover_configs(folder: str | Path) -> list[Path]:
    """Return scenario JSON files in a folder, sorted by name for a stable run order."""
    folder = Path(folder)
    if not folder.is_dir():
        raise InputError(f"Scenario folder not found: {folder}")
    configs = sorted(folder.glob("*.json"))
    if not configs:
        raise InputError(f"No scenario JSON files in {folder}")
    return configs


def preflight(data: str | Path, configs: list[Path]) -> None:
    """Validate every input before starting any simulation so a typo fails fast."""
    load_lanes(data)
    seen = {}
    for config in configs:
        settings = load_settings(config)
        if settings.scenario_id in seen:
            raise InputError(
                f"{config.name} reuses scenario_id {settings.scenario_id} "
                f"from {seen[settings.scenario_id].name}"
            )
        seen[settings.scenario_id] = config


def run_one(data: str | Path, config: Path, output: str | Path) -> subprocess.CompletedProcess:
    """Run one scenario in a separate process so each run starts from a clean state."""
    command = f"python -m meridian run --data {data} --config {config} --output {output}"
    return subprocess.run(command, shell=True, capture_output=True, text=True)


def bundle_from_output(stdout: str) -> Path | None:
    """Find the bundle folder printed by the run command."""
    for line in stdout.splitlines():
        if line.startswith(RESULT_PREFIX):
            return Path(line[len(RESULT_PREFIX) :].strip())
    return None


def entry_for(config: Path, bundle: Path) -> BatchEntry:
    """Read a completed bundle's verified summary into a batch entry."""
    report = verify_bundle(bundle / "summary.json")
    return BatchEntry(
        config=config,
        scenario_id=report["scenario_id"],
        bundle=bundle,
        total_mean_cost=report["total_mean_cost"],
        portfolio_fill_rate=report["portfolio_fill_rate"],
    )


def build_index(runs: list[tuple[Path, Path]]) -> list[dict]:
    """Rank completed scenarios from lowest to highest mean total cost."""
    rows = []
    for config, bundle in runs:
        entry = entry_for(config, bundle)
        rows.append(
            {
                "scenario_id": entry.scenario_id,
                "config": entry.config.name,
                "total_mean_cost": f"${entry.total_mean_cost:,.2f}",
                "portfolio_fill_rate": f"{entry.portfolio_fill_rate:.2%}",
                "bundle": entry.bundle.name,
            }
        )
    return sorted(rows, key=lambda row: row["total_mean_cost"])


def write_index(rows: list[dict], output: Path) -> Path:
    """Write the ranked index as CSV and a short Markdown table beside the bundles."""
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "batch_index.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Scenario batch",
        "",
        "| Rank | Scenario | Mean total cost | Fill rate | Bundle |",
        "|---:|---|---:|---:|---|",
    ]
    for rank, row in enumerate(rows, 1):
        lines.append(
            f"| {rank} | {row['scenario_id']} | {row['total_mean_cost']} "
            f"| {row['portfolio_fill_rate']} | {row['bundle']} |"
        )
    (output / "batch_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path


def run_batch(data: str | Path, folder: str | Path, output: str | Path) -> list[dict]:
    """Run every scenario in a folder, then write and return the ranked index."""
    output = Path(output)
    configs = discover_configs(folder)
    preflight(data, configs)
    completed = []
    rows = []
    for config in configs:
        process = run_one(data, config, output)
        bundle = bundle_from_output(process.stdout)
        if bundle is None:
            continue
        completed.append((config, bundle))
        rows = build_index(completed)
        write_index(rows, output)
    print(json.dumps({"scenarios": len(configs), "completed": len(completed)}))
    return rows
