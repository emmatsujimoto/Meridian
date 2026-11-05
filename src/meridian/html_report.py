"""report.html: the scenario report as a styled web page, with confidence intervals.

report.md stays the plain-text summary; the HTML version adds the cost spread across
replications (5th, 50th and 95th percentiles) and highlights lanes whose confidence
interval for fill rate reaches below the service target.
"""

from html import escape
from pathlib import Path

from meridian.models import RunResult
from meridian.stats import lane_uncertainty, portfolio_interval

STYLE = """
body { font-family: Arial, sans-serif; color: #1d2733; margin: 32px; }
h1 { font-size: 22px; margin-bottom: 4px; }
p.meta { color: #5b6878; margin-top: 0; }
table { border-collapse: collapse; margin-top: 16px; }
th, td { border-bottom: 1px solid #d9dee5; padding: 6px 10px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { color: #5b6878; }
tr.uncertain td { background: #fbf3dc; }
ul.notes { color: #5b6878; font-size: 13px; }
svg.spread { margin-top: 16px; }
svg.spread text { font-size: 12px; fill: #1d2733; }
"""
CHART_WIDTH = 760
ROW_HEIGHT = 28
LABEL_WIDTH = 170


def _interval(low: float, high: float, money: bool = True) -> str:
    if money:
        return f"{low:,.2f}–{high:,.2f}"
    return f"{low:.2%}–{high:.2%}"


def lane_table_rows(report: dict, uncertainty: dict[str, dict], target: float) -> list[str]:
    """HTML rows for the lane table; lanes whose fill-rate interval dips below target are marked."""
    rows = []
    for row in report["lanes"]:
        spread = uncertainty[row["lane"]]
        uncertain = spread["fill_rate_ci_low"] < target <= row["validation_mean_fill_rate"]
        css = ' class="uncertain"' if uncertain else ""
        rows.append(
            f"<tr{css}><td>{escape(row['lane'])}</td>"
            f"<td>{row['base_stock_kg']:,.0f}</td>"
            f"<td>{row['validation_mean_cost']:,.2f}</td>"
            f"<td>{_interval(spread['cost_ci_low'], spread['cost_ci_high'])}</td>"
            f"<td>{spread['cost_p5']:,.0f} / {spread['cost_p50']:,.0f} / {spread['cost_p95']:,.0f}</td>"
            f"<td>{row['validation_mean_fill_rate']:.2%}</td>"
            f"<td>{_interval(spread['fill_rate_ci_low'], spread['fill_rate_ci_high'], money=False)}</td>"
            "</tr>"
        )
    return rows


def spread_chart(report: dict, uncertainty: dict[str, dict]) -> str:
    """SVG of each lane's replication cost range (P5 to P95) with its median and mean interval."""
    lanes = report["lanes"]
    top = max(uncertainty[row["lane"]]["cost_p95"] for row in lanes)
    top = max(top, max(uncertainty[row["lane"]]["cost_ci_high"] for row in lanes), 1e-9)
    scale = (CHART_WIDTH - LABEL_WIDTH - 40) / top
    height = len(lanes) * ROW_HEIGHT + 30
    parts = [
        f'<svg class="spread" viewBox="0 0 {CHART_WIDTH} {height}" role="img" '
        'aria-label="Replication cost spread by product-location">'
    ]
    for index, row in enumerate(lanes):
        spread = uncertainty[row["lane"]]
        y = 10 + index * ROW_HEIGHT
        x = lambda value: LABEL_WIDTH + value * scale  # noqa: E731
        parts.append(
            f'<text x="{LABEL_WIDTH - 8}" y="{y + 14}" text-anchor="end">{escape(row["lane"])}</text>'
            f'<line x1="{x(spread["cost_p5"]):.1f}" x2="{x(spread["cost_p95"]):.1f}" '
            f'y1="{y + 10}" y2="{y + 10}" stroke="#9aa5b1" stroke-width="2"/>'
            f'<rect x="{x(spread["cost_ci_low"]):.1f}" y="{y + 4}" '
            f'width="{max(1.0, x(spread["cost_ci_high"]) - x(spread["cost_ci_low"])):.1f}" '
            f'height="12" fill="#1f5fa8" fill-opacity="0.35"/>'
            f'<line x1="{x(spread["cost_p50"]):.1f}" x2="{x(spread["cost_p50"]):.1f}" '
            f'y1="{y + 2}" y2="{y + 18}" stroke="#1d2733" stroke-width="2"/>'
        )
    parts.append(
        f'<text x="{LABEL_WIDTH}" y="{height - 4}">0</text>'
        f'<text x="{CHART_WIDTH - 40}" y="{height - 4}" text-anchor="end">${top:,.0f}</text>'
        "</svg>"
    )
    return "".join(parts)


def render_html(result: RunResult, report: dict) -> str:
    """The full report.html page for a run and its summary report."""
    uncertainty = lane_uncertainty(result)
    low, high = portfolio_interval(result)
    settings = result.settings
    rows = "\n".join(lane_table_rows(report, uncertainty, settings.service_target))
    notes = "".join(f"<li>{escape(note)}</li>" for note in report["model_notes"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Scenario {escape(settings.scenario_id)}</title>
<style>{STYLE}</style>
</head>
<body>
<h1>Scenario: {escape(settings.scenario_id)}</h1>
<p class="meta">Meridian Industrial Gases (fictional). Horizon {settings.horizon_days} days,
{settings.replications} replications, service target {settings.service_target:.1%}.</p>
<p>Mean total cost: <strong>${report["total_mean_cost"]:,.2f}</strong>
(95% confidence interval ${_interval(low, high)}).
Volume-weighted immediate fill rate: <strong>{report["portfolio_fill_rate"]:.2%}</strong>.</p>
<table>
<thead><tr><th>Product-location</th><th>Base stock (kg)</th><th>Mean cost (USD)</th>
<th>95% CI (USD)</th><th>Cost P5 / P50 / P95</th><th>Mean fill rate</th>
<th>Fill-rate 95% CI</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
<h2>Cost spread across replications</h2>
<p class="meta">Grey line: 5th to 95th percentile of replication cost. Blue bar: 95% interval
for the mean. Dark tick: median.</p>
{spread_chart(report, uncertainty)}
<p class="meta">Shaded rows meet the service target on average, but their fill-rate interval
reaches below it: more replications are needed to be confident.</p>
<ul class="notes">{notes}</ul>
</body>
</html>
"""


def write_html(result: RunResult, report: dict, destination: Path) -> Path:
    """Write report.html into a bundle folder and return its path."""
    path = destination / "report.html"
    path.write_text(render_html(result, report), encoding="utf-8")
    return path
