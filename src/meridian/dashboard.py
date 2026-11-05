"""Static HTML dashboard comparing cost and service across completed result bundles.

The page is a single self-contained file (inline CSS, SVG charts and a small sorting
script), so it can be e-mailed or opened from a shared drive without a web server.
Every figure comes from a bundle's verified summary.json.
"""

import base64
import csv
import io
from datetime import datetime, timezone
from html import escape
from importlib import resources
from pathlib import Path
from string import Template

from meridian import __version__
from meridian.bundles import verify_bundle
from meridian.models import InputError

MAX_BUNDLES = 50
COST_COMPONENTS = (
    ("mean_holding_cost", "Holding"),
    ("mean_backlog_cost", "Backlog"),
    ("mean_delivery_cost", "Delivery"),
    ("mean_purchase_cost", "Purchase"),
)
CHART_WIDTH = 960
BAR_HEIGHT = 26
BAR_GAP = 14
LABEL_WIDTH = 190


def load_bundles(sources: list[str | Path]) -> list[dict]:
    paths = []
    for source in sources:
        source = Path(source)
        if source.is_dir() and not (source / "summary.json").is_file():
            paths.extend(sorted(source.glob("*/summary.json")))
        elif source.is_dir():
            paths.append(source / "summary.json")
        else:
            paths.append(source)
    if not paths:
        raise InputError("No completed result bundles found")
    if len(paths) > MAX_BUNDLES:
        raise InputError(f"A dashboard compares at most {MAX_BUNDLES} bundles; got {len(paths)}")
    reports = []
    seen = set()
    for path in paths:
        report = verify_bundle(path)
        key = (report["scenario_id"], report["input_sha256"])
        if key in seen:
            continue
        seen.add(key)
        reports.append(report)
    return sorted(reports, key=lambda report: report["total_mean_cost"])


def _settings(report: dict) -> dict:
    return report.get("inputs", {}).get("settings", {})


def _money(value: float) -> str:
    return f"${value:,.0f}"


def expected_demand_kg(report: dict) -> float:
    """Mean demand (kg) over the horizon implied by the report's inputs, across all lanes."""
    settings = _settings(report)
    multiplier = settings.get("demand_multiplier", 1.0)
    lanes = report.get("inputs", {}).get("lanes", [])
    return sum(lane["daily_mean_kg"] for lane in lanes) * multiplier * report["horizon_days"]


def cost_per_kg(report: dict) -> float | None:
    """Mean total cost per kg of expected demand (USD/kg), or None without lane inputs."""
    demand_kg = expected_demand_kg(report)
    return report["total_mean_cost"] / demand_kg if demand_kg else None


def baseline_changes(reports: list[dict], baseline_id: str) -> dict[int, tuple[float, float]]:
    """Change in mean cost (USD) and fill rate (points) of each report against the baseline.

    Keys are positions in ``reports``. The baseline is the first report with that scenario id.
    """
    matches = [report for report in reports if report["scenario_id"] == baseline_id]
    if not matches:
        raise InputError(f"Baseline scenario {baseline_id!r} is not among the bundles")
    base = matches[0]
    return {
        index: (
            report["total_mean_cost"] - base["total_mean_cost"],
            (report["portfolio_fill_rate"] - base["portfolio_fill_rate"]) * 100,
        )
        for index, report in enumerate(reports)
    }


def scenario_overview(reports: list[dict]) -> list[tuple[str, str, str]]:
    best = reports[0]
    worst = reports[-1]
    fills = [report["portfolio_fill_rate"] for report in reports]
    return [
        ("Scenarios compared", str(len(reports)), "Completed bundles with verified files"),
        ("Lowest mean cost", _money(best["total_mean_cost"]), escape(best["scenario_id"])),
        (
            "Cost range",
            _money(worst["total_mean_cost"] - best["total_mean_cost"]),
            f"Highest: {escape(worst['scenario_id'])}",
        ),
        ("Fill rate range", f"{min(fills):.1%} – {max(fills):.1%}", "Volume-weighted, validation"),
        *_unit_cost_tile(reports),
    ]


def _unit_cost_tile(reports: list[dict]) -> list[tuple[str, str, str]]:
    unit_costs = [(cost_per_kg(report), report) for report in reports]
    unit_costs = [(value, report) for value, report in unit_costs if value is not None]
    if not unit_costs:
        return []
    value, report = min(unit_costs, key=lambda pair: pair[0])
    return [("Lowest cost per kg", f"${value:,.3f}", escape(report["scenario_id"]))]


def scenarioRows(reports: list[dict], changes: dict[int, tuple[float, float]] | None = None) -> str:
    """Table rows for the scenario list, one per bundle, with optional baseline changes."""
    rows = []
    for index, report in enumerate(reports):
        settings = _settings(report)
        target = settings.get("service_target", 0.95)
        met = sum(1 for row in report["lanes"] if row["validation_mean_fill_rate"] >= target)
        rows.append(
            "<tr>"
            f"<td>{escape(report['scenario_id'])}</td>"
            f'<td class="description">{settings.get("description", "")}</td>'
            f"<td>{report['horizon_days']}</td>"
            f"<td>{report['replications']}</td>"
            f'<td data-sort="{report["total_mean_cost"]}">{_money(report["total_mean_cost"])}</td>'
            f'<td data-sort="{report["portfolio_fill_rate"]}">{report["portfolio_fill_rate"]:.1%}</td>'
            f"<td>{met} of {len(report['lanes'])}</td>"
            f"<td><code>{escape(report['input_sha256'][:12])}</code></td>"
            f"{_unit_cost_cell(report)}"
            f"{_change_cells(changes, index)}"
            "</tr>"
        )
    return "\n".join(rows)


def _unit_cost_cell(report: dict) -> str:
    value = cost_per_kg(report)
    if value is None:
        return '<td data-sort="-1">–</td>'
    return f'<td data-sort="{value}">${value:,.3f}</td>'


def _change_cells(changes: dict[int, tuple[float, float]] | None, index: int) -> str:
    if changes is None:
        return ""
    cost, fill_points = changes[index]
    return (
        f'<td data-sort="{cost}">{"+" if cost >= 0 else "−"}{_money(abs(cost))}</td>'
        f'<td data-sort="{fill_points}">{fill_points:+.1f} pts</td>'
    )


def buildChart(labels: list[str], series: list[tuple[str, list[float]]], unit: str) -> str:
    """Horizontal stacked bar chart as inline SVG; each series is one stacked component."""
    colours = ["#1f5fa8", "#d1495b", "#edae49", "#66a182", "#7a5c99", "#2e4057"]
    totals = [sum(values[i] for _, values in series) for i in range(len(labels))]
    scale = (CHART_WIDTH - LABEL_WIDTH - 120) / max(max(totals, default=0), 1e-9)
    height = len(labels) * (BAR_HEIGHT + BAR_GAP) + BAR_GAP
    parts = [
        f'<svg class="chart" viewBox="0 0 {CHART_WIDTH} {height}" role="img" '
        f'aria-label="{escape(unit)} by scenario">'
    ]
    for index, label in enumerate(labels):
        y = BAR_GAP + index * (BAR_HEIGHT + BAR_GAP)
        parts.append(
            f'<text x="{LABEL_WIDTH - 10}" y="{y + BAR_HEIGHT * 0.68:.1f}" '
            f'text-anchor="end">{escape(label)}</text>'
        )
        x = LABEL_WIDTH
        for colour, (name, values) in zip(colours, series):
            width = values[index] * scale
            if width <= 0:
                continue
            parts.append(
                f'<rect x="{x:.1f}" y="{y}" width="{width:.1f}" height="{BAR_HEIGHT}" '
                f'fill="{colour}"><title>{escape(label)}: {escape(name)} '
                f"{values[index]:,.0f} {escape(unit)}</title></rect>"
            )
            x += width
        parts.append(
            f'<text x="{x + 8:.1f}" y="{y + BAR_HEIGHT * 0.68:.1f}">{totals[index]:,.0f}</text>'
        )
    parts.append("</svg>")
    legend = "".join(
        f'<span style="--swatch: {colour}">{escape(name)}</span>'
        for colour, (name, _) in zip(colours, series)
    )
    if len(series) > 1:
        parts.append(f'<div class="legend">{legend}</div>')
    return "\n".join(parts)


def _service_chart(reports: list[dict]) -> str:
    labels = [report["scenario_id"] for report in reports]
    fills = [report["portfolio_fill_rate"] * 100 for report in reports]
    chart = buildChart(labels, [("Fill rate", fills)], "% fill rate")
    target_x = LABEL_WIDTH + 0.95 * (CHART_WIDTH - LABEL_WIDTH - 120) * 100 / max(max(fills), 1e-9)
    height = len(labels) * (BAR_HEIGHT + BAR_GAP) + BAR_GAP
    marker = (
        f'<line x1="{target_x:.1f}" x2="{target_x:.1f}" y1="0" y2="{height}" '
        'stroke="#1d2733" stroke-dasharray="4 4"><title>95% service target</title></line>'
    )
    return chart.replace("</svg>", marker + "</svg>", 1)


def _lane_matrix(reports: list[dict]) -> tuple[str, str]:
    lanes = sorted({row["lane"] for report in reports for row in report["lanes"]})
    header = '<th scope="col">Product-location</th>' + "".join(
        f'<th scope="col">{escape(report["scenario_id"])}</th>' for report in reports
    )
    fill = {
        (index, row["lane"]): row["validation_mean_fill_rate"]
        for index, report in enumerate(reports)
        for row in report["lanes"]
    }
    rows = []
    for lane in lanes:
        cells = [f"<td>{escape(lane)}</td>"]
        for index in range(len(reports)):
            value = fill.get((index, lane))
            if value is None:
                cells.append('<td data-sort="-1">–</td>')
                continue
            status = "below" if value < 0.95 else "meets"
            cells.append(f'<td class="{status}" data-sort="{value}">{value:.1%}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return header, "\n".join(rows)


def _differing_settings(reports: list[dict]) -> tuple[str, str]:
    """Header and rows listing only the settings whose values differ between scenarios."""
    names = sorted(
        {name for report in reports for name in _settings(report)} - {"scenario_id", "description"}
    )
    differing = [
        name for name in names if len({repr(_settings(report).get(name)) for report in reports}) > 1
    ]
    header = '<th scope="col">Setting</th>' + "".join(
        f'<th scope="col">{escape(report["scenario_id"])}</th>' for report in reports
    )
    if not differing:
        colspan = len(reports) + 1
        return header, f'<tr><td colspan="{colspan}">All scenarios use the same settings.</td></tr>'
    rows = []
    for name in differing:
        cells = "".join(
            f"<td>{escape(_format_setting(_settings(report).get(name)))}</td>" for report in reports
        )
        rows.append(f"<tr><td>{escape(name)}</td>{cells}</tr>")
    return header, "\n".join(rows)


def _format_setting(value) -> str:
    if value is None:
        return "–"
    if isinstance(value, list):
        return ", ".join(f"{item:g}" if isinstance(item, float) else str(item) for item in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _lane_cost_matrix(reports: list[dict]) -> tuple[str, str]:
    """Mean validation cost of each lane in each scenario (USD)."""
    lanes = sorted({row["lane"] for report in reports for row in report["lanes"]})
    header = '<th scope="col">Product-location</th>' + "".join(
        f'<th scope="col">{escape(report["scenario_id"])}</th>' for report in reports
    )
    cost = {
        (index, row["lane"]): row["validation_mean_cost"]
        for index, report in enumerate(reports)
        for row in report["lanes"]
    }
    rows = []
    for lane in lanes:
        cells = [f"<td>{escape(lane)}</td>"]
        for index in range(len(reports)):
            value = cost.get((index, lane))
            if value is None:
                cells.append('<td data-sort="-1">–</td>')
            else:
                cells.append(f'<td data-sort="{value}">{_money(value)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return header, "\n".join(rows)


def _details(reports: list[dict]) -> str:
    """Collapsible per-scenario tables with each lane's base stock, cost and service."""
    blocks = []
    for report in reports:
        rows = "".join(
            "<tr>"
            f"<td>{escape(row['lane'])}</td>"
            f"<td>{row['base_stock_kg']:,.0f}</td>"
            f"<td>{_money(row['validation_mean_cost'])}</td>"
            f"<td>{row['validation_mean_fill_rate']:.1%}</td>"
            f"<td>{'Yes' if row['validation_target_met'] else 'No'}</td>"
            f"<td>{row['mean_terminal_inventory_kg']:,.0f}</td>"
            "</tr>"
            for row in report["lanes"]
        )
        blocks.append(
            f"<details><summary>{escape(report['scenario_id'])}: "
            f"{_money(report['total_mean_cost'])}, {report['portfolio_fill_rate']:.1%} fill rate"
            "</summary><table><thead><tr><th>Product-location</th><th>Base stock (kg)</th>"
            "<th>Mean cost</th><th>Fill rate</th><th>Target met</th>"
            "<th>Ending inventory (kg)</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></details>"
        )
    return "\n".join(blocks)


def _csv_link(reports: list[dict]) -> str:
    """A download link carrying the scenario table as CSV, so the page needs no server."""
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(
        ["scenario_id", "total_mean_cost", "portfolio_fill_rate", *[n for _, n in COST_COMPONENTS]]
    )
    for report in reports:
        writer.writerow(
            [
                report["scenario_id"],
                f"{report['total_mean_cost']:.2f}",
                f"{report['portfolio_fill_rate']:.4f}",
                *[f"{sum(row[key] for row in report['lanes']):.2f}" for key, _ in COST_COMPONENTS],
            ]
        )
    data = base64.b64encode(stream.getvalue().encode("utf-8")).decode("ascii")
    return (
        f'<a class="download" download="scenarios.csv" href="data:text/csv;base64,{data}">'
        "Download scenario table (CSV)</a>"
    )


def _legacy_table(reports: list[dict]) -> str:
    rows = "".join(
        f"<tr><td>{escape(r['scenario_id'])}</td><td>{r['total_mean_cost']:,.2f}</td></tr>"
        for r in reports
    )
    return f"<table><tr><th>Scenario</th><th>Cost</th></tr>{rows}</table>"


def render_dashboard(
    reports: list[dict], generated: datetime | None = None, baseline: str | None = None
) -> str:
    if not reports:
        raise InputError("At least one report is required")
    changes = baseline_changes(reports, baseline) if baseline else None
    change_headers = (
        '<th scope="col">Cost vs baseline</th><th scope="col">Fill rate vs baseline</th>'
        if changes
        else ""
    )
    generated = generated or datetime.now(timezone.utc)
    labels = [report["scenario_id"] for report in reports]
    cost_series = [
        (name, [sum(row[key] for row in report["lanes"]) for report in reports])
        for key, name in COST_COMPONENTS
    ]
    tiles = "".join(
        f'<div class="tile"><div class="label">{label}</div><div class="value">{value}</div>'
        f'<div class="note">{note}</div></div>'
        for label, value, note in scenario_overview(reports)
    )
    lane_header, lane_rows = _lane_matrix(reports)
    settings_header, settings_rows = _differing_settings(reports)
    cost_header, cost_rows = _lane_cost_matrix(reports)
    template = Template(
        resources.files("meridian").joinpath("templates/dashboard.html").read_text("utf-8")
    )
    return template.substitute(
        subtitle=f"{len(reports)} scenarios, sorted by mean validation cost (lowest first)."
        + (f" Changes are against {escape(baseline)}." if baseline else ""),
        tiles=tiles,
        scenario_rows=scenarioRows(reports, changes),
        change_headers=change_headers,
        cost_chart=buildChart(labels, cost_series, "USD"),
        service_chart=_service_chart(reports),
        lane_header=lane_header,
        lane_rows=lane_rows,
        settings_header=settings_header,
        settings_rows=settings_rows,
        cost_header=cost_header,
        cost_rows=cost_rows,
        details=_details(reports),
        csv_link=_csv_link(reports),
        version=escape(__version__),
        generated=generated.strftime("%Y-%m-%d %H:%M UTC"),
    )


def write_dashboard(
    sources: list[str | Path], output: str | Path, baseline: str | None = None
) -> Path:
    output = Path(output).resolve()
    if output.suffix.lower() not in {".html", ".htm"}:
        raise InputError("Dashboard output must end in .html")
    page = render_dashboard(load_bundles(sources), baseline=baseline)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(page, encoding="utf-8")
    except OSError as exc:
        raise InputError(f"Cannot write dashboard {output}: {exc}") from exc
    return output
