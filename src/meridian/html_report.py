"""Side-by-side HTML comparison of completed scenario results for sharing with planners."""

import json
from pathlib import Path

from meridian.models import InputError

STYLE = """
body { font-family: Arial, sans-serif; margin: 2rem; color: #1f2933; }
h1 { font-size: 1.4rem; margin-bottom: 0.25rem; }
p.note { color: #52606d; margin-top: 0; }
table { border-collapse: collapse; margin: 1rem 0 2rem; min-width: 40rem; }
th, td { border-bottom: 1px solid #d9e2ec; padding: 0.4rem 0.8rem; text-align: right; }
th:first-child, td:first-child { text-align: left; }
tr.best td { font-weight: bold; background: #f0f4f8; }
"""


def load_summaries(paths: list[str | Path]) -> list[dict]:
    """Read each scenario's summary.json, in the order given."""
    if len(paths) < 2:
        raise InputError("Provide at least two summary.json files to compare")
    summaries = []
    for path in paths:
        try:
            summaries.append(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise InputError(f"Cannot read {path}: {exc}") from exc
    return summaries


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _percent(value: float) -> str:
    return f"{value:.1%}"


def scenario_rows(summaries: list[dict]) -> list[dict]:
    """One row per scenario with totals and the change against the first scenario."""
    base = summaries[0]["total_mean_cost"]
    rows = []
    for report in summaries:
        cost = report["total_mean_cost"]
        rows.append(
            {
                "scenario": report["scenario_id"],
                "horizon_days": report["horizon_days"],
                "total_cost": cost,
                "change_pct": (cost - base) / base * 100,
                "fill_rate": report["portfolio_fill_rate"],
            }
        )
    return rows


def lane_matrix(summaries: list[dict]) -> tuple[list[str], dict]:
    """Mean validation cost per lane (rows) and scenario (columns)."""
    lanes = sorted({row["lane"] for report in summaries for row in report["lanes"]})
    matrix = {}
    for lane in lanes:
        matrix[lane] = {}
        for report in summaries:
            for row in report["lanes"]:
                if row["lane"] == lane:
                    matrix[lane][report["scenario_id"]] = row["validation_mean_cost"]
    return lanes, matrix


def render(summaries: list[dict], title: str) -> str:
    """Build the full HTML page. The lowest-cost scenario is highlighted."""
    rows = scenario_rows(summaries)
    best = max(rows, key=lambda row: row["total_cost"])
    lanes, matrix = lane_matrix(summaries)
    names = [row["scenario"] for row in rows]
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{title}</title>",
        f"<style>{STYLE}</style></head><body>",
        f"<h1>{title}</h1>",
        '<p class="note">Synthetic planning study. Costs are mean validation costs over each '
        "scenario's horizon. The highlighted row has the lowest total cost.</p>",
        "<h2>Scenarios</h2>",
        "<table><tr><th>Scenario</th><th>Horizon (days)</th><th>Total cost</th>"
        "<th>Change vs first</th><th>Fill rate</th></tr>",
    ]
    for row in rows:
        css = ' class="best"' if row is best else ""
        parts.append(
            f"<tr{css}><td>{row['scenario']}</td><td>{row['horizon_days']}</td>"
            f"<td>{_money(row['total_cost'])}</td><td>{row['change_pct']:+.1f}%</td>"
            f"<td>{_percent(row['fill_rate'])}</td></tr>"
        )
    parts.append("</table>")
    parts.append("<h2>Mean cost by product-location</h2>")
    header = "".join(f"<th>{name}</th>" for name in names)
    parts.append(f"<table><tr><th>Product-location</th>{header}</tr>")
    for lane in lanes:
        cells = "".join(
            f"<td>{_money(matrix[lane][name])}</td>" if name in matrix[lane] else "<td>-</td>"
            for name in names
        )
        parts.append(f"<tr><td>{lane}</td>{cells}</tr>")
    parts.append("</table></body></html>")
    return "\n".join(parts) + "\n"


def write_comparison(paths: list[str | Path], output: str | Path, title: str) -> Path:
    """Compare completed scenarios and write a standalone HTML page."""
    summaries = load_summaries(paths)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(summaries, title))
    return output
