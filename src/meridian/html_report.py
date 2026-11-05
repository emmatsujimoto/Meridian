"""A self-contained HTML report for one completed run, with a cost breakdown chart.

The page has no external scripts, fonts or images, so it can be attached to an email or
opened offline. The chart is inline SVG: one stacked horizontal bar per product-location,
split into holding, ordering and backlog cost.
"""

import csv
from html import escape
from pathlib import Path

from meridian.bundles import verify_bundle
from meridian.models import InputError

COMPONENTS = ("holding", "ordering", "backlog")
BAR_HEIGHT = 22
BAR_GAP = 10
LABEL_WIDTH = 170
CHART_WIDTH = 720


def _cost_components(summary_path: Path) -> dict[str, dict[str, float]]:
    """Mean holding, ordering and backlog cost per lane over the validation replications."""
    totals: dict[str, dict[int, dict[str, float]]] = {}
    try:
        with (summary_path.parent / "daily_results.csv").open(
            newline="", encoding="utf-8"
        ) as stream:
            for row in csv.DictReader(stream):
                replication = totals.setdefault(row["lane"], {}).setdefault(
                    int(row["replication"]), dict.fromkeys(COMPONENTS, 0.0)
                )
                replication["holding"] += float(row["holding_cost"])
                replication["ordering"] += float(row["delivery_cost"]) + float(row["purchase_cost"])
                replication["backlog"] += float(row["backlog_cost"])
    except (OSError, UnicodeError, csv.Error, KeyError, ValueError) as exc:
        raise InputError(f"Cannot read daily results: {exc}") from exc
    components = {}
    for lane, replications in totals.items():
        count = len(replications)
        components[lane] = {
            name: sum(values[name] for values in replications.values()) / count
            for name in COMPONENTS
        }
    return components


def _svg_text(x: float, y: float, text: str, anchor: str = "start") -> str:
    """An SVG text element with escaped content."""
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">{escape(text)}</text>'


def cost_chart(components: dict[str, dict[str, float]]) -> str:
    """Inline SVG stacked bar chart of cost components per lane."""
    if not components:
        raise InputError("No lanes to chart")
    lanes = sorted(components)
    largest = max(sum(components[lane].values()) for lane in lanes) or 1.0
    scale = (CHART_WIDTH - LABEL_WIDTH - 90) / largest
    colours = {"holding": "#3B6EA5", "ordering": "#E59C3C", "backlog": "#C0392B"}
    height = len(lanes) * (BAR_HEIGHT + BAR_GAP) + 50
    parts = [
        f'<svg class="chart" viewBox="0 0 {CHART_WIDTH} {height}" role="img" '
        f'aria-label="Cost breakdown by product-location">'
    ]
    for index, lane in enumerate(lanes):
        y = 10 + index * (BAR_HEIGHT + BAR_GAP)
        parts.append(
            f'<text x="{LABEL_WIDTH - 8}" y="{y + BAR_HEIGHT * 0.7:.1f}" '
            f'text-anchor="end">{escape(lane)}</text>'
        )
        x = float(LABEL_WIDTH)
        for name in COMPONENTS:
            width = components[lane][name] * scale
            parts.append(
                f'<rect x="{x:.1f}" y="{y}" width="{width:.1f}" height="{BAR_HEIGHT}" '
                f'fill="{colours[name]}"><title>{escape(lane)} {name}: '
                f"${components[lane][name]:,.2f}</title></rect>"
            )
            x += width
        parts.append(
            f'<text x="{x + 6:.1f}" y="{y + BAR_HEIGHT * 0.7:.1f}">'
            f"${sum(components[lane].values()):,.0f}</text>"
        )
    legend_y = height - 20
    for index, name in enumerate(COMPONENTS):
        x = LABEL_WIDTH + index * 120
        parts.append(
            f'<rect x="{x}" y="{legend_y - 10}" width="12" height="12" fill="{colours[name]}"/>'
            f'<text x="{x + 18}" y="{legend_y}">{name.capitalize()}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def cost_shares(components: dict[str, dict[str, float]]) -> dict[str, float]:
    """Each component's share of the total cost across all lanes; zeros if nothing cost."""
    totals = {name: sum(parts[name] for parts in components.values()) for name in COMPONENTS}
    overall = sum(totals.values())
    if overall == 0:
        return dict.fromkeys(COMPONENTS, 0.0)
    return {name: totals[name] / overall for name in COMPONENTS}


def _share_table(components: dict[str, dict[str, float]]) -> list[str]:
    """HTML rows summarising cost by component across the whole run."""
    shares = cost_shares(components)
    rows = ["<table><thead><tr><th>Component</th><th>Cost</th><th>Share</th></tr></thead><tbody>"]
    for name in COMPONENTS:
        amount = sum(parts[name] for parts in components.values())
        rows.append(
            f"<tr><td>{name.capitalize()}</td><td>${amount:,.2f}</td>"
            f"<td>{shares[name]:.1%}</td></tr>"
        )
    rows.append("</tbody></table>")
    return rows


STYLE = """
body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 52rem;
       padding: 0 1rem; color: #1d2733; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { border-bottom: 1px solid #d8dee6; padding: 0.35rem 0.5rem; text-align: right; }
th:first-child, td:first-child { text-align: left; }
.chart { width: 100%; height: auto; font-size: 12px; }
figcaption { color: #5b6878; font-size: 0.9rem; }
"""


def render_html(summary_path: str | Path) -> str:
    """The HTML report for a verified bundle."""
    path = Path(summary_path).resolve()
    report = verify_bundle(path)
    components = _cost_components(path)
    rows = []
    for lane in report["lanes"]:
        parts = components.get(lane["lane"], dict.fromkeys(COMPONENTS, 0.0))
        rows.append(
            "<tr>"
            f"<td>{escape(lane['lane'])}</td>"
            f"<td>{lane['base_stock_kg']:,.0f}</td>"
            f"<td>{lane['validation_mean_fill_rate']:.1%}</td>"
            f"<td>${parts['holding']:,.2f}</td>"
            f"<td>${parts['ordering']:,.2f}</td>"
            f"<td>${parts['backlog']:,.2f}</td>"
            f"<td>${lane['validation_mean_cost']:,.2f}</td>"
            "</tr>"
        )
    title = f"Meridian scenario: {report['scenario_id']}"
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{escape(title)}</title><style>{STYLE}</style></head><body>",
            f"<h1>{escape(title)}</h1>",
            "<p>Meridian Industrial Gases — fictional internal planning study.</p>",
            "<table><tbody>",
            f"<tr><td>Horizon</td><td>{report['horizon_days']} days</td></tr>",
            f"<tr><td>Replications</td><td>{report['replications']}</td></tr>",
            f"<tr><td>Mean total cost</td><td>${report['total_mean_cost']:,.2f}</td></tr>",
            "<tr><td>Volume-weighted fill rate</td>"
            f"<td>{report['portfolio_fill_rate']:.1%}</td></tr>",
            "</tbody></table>",
            "<h2>Cost breakdown</h2>",
            "<figure>",
            cost_chart(components),
            "<figcaption>Mean monthly cost per product-location, split into holding, "
            "ordering (delivery and purchase) and backlog cost.</figcaption>",
            "</figure>",
            *_share_table(components),
            "<table><thead><tr><th>Product-location</th><th>Base stock (kg)</th>"
            "<th>Fill rate</th><th>Holding</th><th>Ordering</th><th>Backlog</th>"
            "<th>Total</th></tr></thead><tbody>",
            *rows,
            "</tbody></table>",
            "<ul>",
            *[f"<li>{escape(note)}</li>" for note in report["model_notes"]],
            "</ul>",
            "</body></html>",
            "",
        ]
    )


def write_html(summary_path: str | Path, destination: str | Path | None = None) -> Path:
    """Write the report next to the bundle (report.html) or to ``destination``.

    An existing file is never replaced.
    """
    target = (
        Path(summary_path).resolve().parent / "report.html"
        if destination is None
        else Path(destination)
    )
    text = render_html(summary_path)
    try:
        with target.open("x", encoding="utf-8") as stream:
            stream.write(text)
    except FileExistsError:
        raise InputError(f"{target} already exists; choose a new file name") from None
    return target
