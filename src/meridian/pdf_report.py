"""A PDF report summarising several completed result bundles.

The first page compares the scenarios side by side. Each scenario then gets its own
section with run facts, a cost chart and a table of product-locations; long tables
continue on further pages. Every bundle is verified before it is used.
"""

from datetime import datetime, timezone
from pathlib import Path

from meridian.bundles import verify_bundle
from meridian.models import InputError
from meridian.pdf import Document, Page, wrap_text

MAX_BUNDLES = 12
ROWS_PER_PAGE = 16
MARGIN = 50
COLUMNS = (
    ("Product-location", "lane", 0, "left"),
    ("Base stock (kg)", "base_stock_kg", 190, "right"),
    ("Mean cost (USD)", "validation_mean_cost", 290, "right"),
    ("Fill rate", "validation_mean_fill_rate", 370, "right"),
    ("Target met", "validation_target_met", 450, "right"),
)
BAR_RGB = (0.23, 0.43, 0.65)
COMPONENT_RGB = {
    "Holding": (0.23, 0.43, 0.65),
    "Ordering": (0.90, 0.61, 0.24),
    "Backlog": (0.75, 0.22, 0.17),
}
GRID_RGB = (0.8, 0.82, 0.85)


SORT_ORDERS = ("given", "name", "cost", "fill-rate")


def sort_reports(reports: list[dict], order: str = "given") -> list[dict]:
    """Reports in the requested order: as given, by name, by cost or by fill rate.

    ``cost`` puts the cheapest scenario first and ``fill-rate`` the best-served first.
    """
    if order not in SORT_ORDERS:
        raise InputError(f"order must be one of {', '.join(SORT_ORDERS)}")
    if order == "name":
        return sorted(reports, key=lambda r: r["scenario_id"])
    if order == "cost":
        return sorted(reports, key=lambda r: r["total_mean_cost"])
    if order == "fill-rate":
        return sorted(reports, key=lambda r: -r["portfolio_fill_rate"])
    return list(reports)


def section_pages(reports: list[dict]) -> list[tuple[str, int]]:
    """Each section's title and first page number, matching the order pages are written."""
    sections = []
    page = 2
    for report in reports:
        sections.append((f"Scenario: {report['scenario_id']}", page))
        page += max(1, -(-len(report["lanes"]) // ROWS_PER_PAGE))
    if len(reports) > 1 and common_lanes(reports):
        sections.append(("Product-locations across scenarios", page))
        page += 1
    sections.append(("Model assumptions", page))
    return sections


def missed_targets(report: dict) -> list[str]:
    """Product-locations that missed the service target on validation."""
    return [row["lane"] for row in report["lanes"] if not row["validation_target_met"]]


def comparison_rows(reports: list[dict]) -> list[dict]:
    return [
        {
            "scenario_id": report["scenario_id"],
            "horizon_days": report["horizon_days"],
            "lanes": len(report["lanes"]),
            "total_mean_cost": report["total_mean_cost"],
            "portfolio_fill_rate": report["portfolio_fill_rate"],
        }
        for report in reports
    ]


def _format(key: str, value: object) -> str:
    """A table cell for one lane field."""
    if key == "lane":
        return str(value)
    if key == "validation_mean_fill_rate":
        return f"{value:.1%}"
    if key == "validation_target_met":
        return "yes" if value else "no"
    return f"{value:,.0f}" if key == "base_stock_kg" else f"{value:,.2f}"


def _bar_chart(
    page: Page, x: float, y: float, width: float, height: float, items: list[tuple[str, float]]
) -> None:
    """Horizontal bars with labels on the left and values on the right."""
    if not items:
        return
    largest = max(value for _, value in items) or 1.0
    label_width = 150
    bar_area = width - label_width - 70
    step = height / len(items)
    bar = min(14.0, step * 0.7)
    page.line(x + label_width, y, x + label_width, y + height, rgb=GRID_RGB)
    for index, (label, value) in enumerate(items):
        top = y + height - (index + 1) * step + (step - bar) / 2
        page.text(x + label_width - 6, top + bar * 0.25, label, size=8, align="right")
        length = value / largest * bar_area
        page.rect(x + label_width, top, length, bar, rgb=BAR_RGB)
        page.text(x + label_width + length + 4, top + bar * 0.25, f"${value:,.0f}", size=8)


def _comparison_chart(page: Page, reports: list[dict], y: float, max_height: float = 240.0) -> None:
    """Total mean cost per scenario, drawn below ``y`` and at most ``max_height`` tall."""
    items = [(r["scenario_id"], r["total_mean_cost"]) for r in reports]
    page.text(MARGIN, y + 8, "Total mean cost by scenario", size=11, style="bold")
    height = min(max_height, max(40.0, 18.0 * len(items)))
    _bar_chart(page, MARGIN, y - height, 595 - 2 * MARGIN, height, items)


def _lane_chart(page: Page, report: dict, y: float) -> float:
    """Mean cost per product-location; returns the y position below the chart."""
    items = [(row["lane"], row["validation_mean_cost"]) for row in report["lanes"]]
    page.text(MARGIN, y, "Mean cost by product-location", size=11, style="bold")
    height = min(220.0, max(40.0, 16.0 * len(items)))
    _bar_chart(page, MARGIN, y - 10 - height, 595 - 2 * MARGIN, height, items)
    return y - 30 - height


def component_totals(report: dict) -> dict[str, float]:
    """Holding, ordering (delivery and purchase) and backlog cost summed over lanes."""
    lanes = report["lanes"]
    return {
        "Holding": sum(row["mean_holding_cost"] for row in lanes),
        "Ordering": sum(row["mean_delivery_cost"] + row["mean_purchase_cost"] for row in lanes),
        "Backlog": sum(row["mean_backlog_cost"] for row in lanes),
    }


def _component_bar(page: Page, report: dict, y: float) -> None:
    """One stacked bar splitting the scenario's total cost into its components."""
    totals = component_totals(report)
    overall = sum(totals.values())
    width = 595 - 2 * MARGIN
    page.text(MARGIN, y + 6, "Cost components", size=9, style="bold")
    x = float(MARGIN)
    for name, value in totals.items():
        share = value / overall if overall else 0.0
        page.rect(x, y - 14, width * share, 12, rgb=COMPONENT_RGB[name])
        x += width * share
    legend_x = float(MARGIN)
    for name, value in totals.items():
        share = value / overall if overall else 0.0
        page.rect(legend_x, y - 30, 8, 8, rgb=COMPONENT_RGB[name])
        page.text(legend_x + 12, y - 29, f"{name} {share:.0%}", size=8)
        legend_x += 120


def common_lanes(reports: list[dict]) -> list[str]:
    """Product-locations present in every report, in name order."""
    sets = [{row["lane"] for row in report["lanes"]} for report in reports]
    return sorted(set.intersection(*sets)) if sets else []


def lane_comparison(reports: list[dict]) -> list[dict]:
    """Mean cost and fill rate of each common product-location in every scenario."""
    by_report = [{row["lane"]: row for row in report["lanes"]} for report in reports]
    rows = []
    for lane in common_lanes(reports):
        rows.append(
            {
                "lane": lane,
                "costs": [lanes[lane]["validation_mean_cost"] for lanes in by_report],
                "fill_rates": [lanes[lane]["validation_mean_fill_rate"] for lanes in by_report],
            }
        )
    return rows


def _lane_comparison_page(document: Document, reports: list[dict], title: str) -> None:
    """A page comparing each common product-location's cost across scenarios."""
    rows = lane_comparison(reports)
    if not rows or len(reports) < 2:
        return
    shown = reports[:5]
    page = document.add_page(595, 842)
    page.text(MARGIN, 790, "Product-locations across scenarios", size=16, style="bold")
    page.text(
        MARGIN,
        772,
        "Mean cost (USD) and fill rate of each product-location present in every scenario."
        + (" First five scenarios shown." if len(reports) > 5 else ""),
        size=9,
    )
    column = (595 - 2 * MARGIN - 130) / len(shown)
    y = 740
    page.text(MARGIN, y, "Product-location", size=8, style="bold")
    for index, report in enumerate(shown):
        x = MARGIN + 130 + column * (index + 1) - 4
        page.text(x, y, report["scenario_id"][:18], size=8, style="bold", align="right")
    page.line(MARGIN, y - 5, 595 - MARGIN, y - 5)
    for row in rows[:40]:
        y -= 15
        page.text(MARGIN, y, row["lane"], size=8)
        for index in range(len(shown)):
            x = MARGIN + 130 + column * (index + 1) - 4
            value = f"{row['costs'][index]:,.0f} ({row['fill_rates'][index]:.0%})"
            page.text(x, y, value, size=8, align="right")
    if len(rows) > 40:
        page.text(MARGIN, y - 20, f"{len(rows) - 40} more product-locations not shown.", size=8)
    _footer(page, len(document.pages), title)


def _notes_page(document: Document, reports: list[dict], title: str) -> None:
    """A closing page listing the model assumptions recorded in the bundles."""
    notes: list[str] = []
    for report in reports:
        for note in report.get("model_notes", []):
            if note not in notes:
                notes.append(note)
    page = document.add_page(595, 842)
    page.text(MARGIN, 790, "Model assumptions", size=16, style="bold")
    y = 760
    for note in notes:
        for index, line in enumerate(wrap_text(note, 10, 595 - 2 * MARGIN - 14)):
            if index == 0:
                page.text(MARGIN, y, "-", size=10)
            page.text(MARGIN + 14, y, line, size=10)
            y -= 14
        y -= 4
    _footer(page, len(document.pages), title)


def draw_border(page: Page) -> None:
    """A thin frame inside the page margins."""
    left, bottom = MARGIN / 2, MARGIN / 2
    right, top = page.width - MARGIN / 2, page.height - MARGIN / 2
    for x1, y1, x2, y2 in (
        (left, bottom, right, bottom),
        (right, bottom, right, top),
        (right, top, left, top),
        (left, top, left, bottom),
    ):
        page.line(x1, y1, x2, y2, rgb=GRID_RGB)


def _footer(page: Page, number: int, title: str) -> None:
    """Report title and page number at the bottom of a page."""
    page.line(MARGIN, 40, page.width - MARGIN, 40, rgb=GRID_RGB)
    page.text(MARGIN, 28, title, size=8)
    page.text(page.width - MARGIN, 28, f"Page {number}", size=8, align="right")


def _cover(document: Document, reports: list[dict], title: str, generated: str) -> None:
    """The first page: title, scenario comparison table and comparison chart."""
    page = document.add_page(595, 842)
    page.text(MARGIN, 780, title, size=20, style="bold")
    page.text(MARGIN, 758, "Meridian Industrial Gases - fictional internal planning study", size=10)
    page.text(MARGIN, 744, f"Generated {generated}. {len(reports)} scenarios.", size=9)
    y = 700
    headers = (
        ("Scenario", 0, "left"),
        ("Horizon", 200, "right"),
        ("Lanes", 260, "right"),
        ("Mean total cost", 380, "right"),
        ("Fill rate", 470, "right"),
    )
    for label, offset, align in headers:
        x = MARGIN + offset + (25 if align == "right" else 0)
        page.text(x, y, label, size=9, style="bold", align=align)
    page.line(MARGIN, y - 5, 595 - MARGIN, y - 5)
    for row in comparison_rows(reports):
        y -= 16
        values = (
            row["scenario_id"],
            f"{row['horizon_days']} days",
            str(row["lanes"]),
            f"${row['total_mean_cost']:,.2f}",
            f"{row['portfolio_fill_rate']:.1%}",
        )
        for (_, offset, align), value in zip(headers, values, strict=True):
            x = MARGIN + offset + (25 if align == "right" else 0)
            page.text(x, y, value, size=9, align=align)
    chart_height = min(240.0, max(40.0, 18.0 * len(reports)))
    _comparison_chart(page, reports, y - 50)
    y = y - 50 - chart_height - 40
    page.text(MARGIN, y, "Contents", size=11, style="bold")
    for name, number in section_pages(reports):
        y -= 14
        page.text(MARGIN, y, name, size=9)
        page.text(595 - MARGIN, y, str(number), size=9, align="right")
    _footer(page, 1, title)


def build_report(
    summary_paths: list[str | Path], title: str = "Scenario comparison", order: str = "given"
) -> bytes:
    if not summary_paths:
        raise InputError("Provide at least one summary.json")
    if len(summary_paths) > MAX_BUNDLES:
        raise InputError(f"At most {MAX_BUNDLES} bundles fit in one report")
    reports = sort_reports([verify_bundle(path) for path in summary_paths], order)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    document = Document(title, author="Meridian", subject="Inventory scenario comparison")
    _cover(document, reports, title, generated)
    for report in reports:
        lanes = report["lanes"]
        chunks = [lanes[i : i + ROWS_PER_PAGE] for i in range(0, len(lanes), ROWS_PER_PAGE)]
        for part, chunk in enumerate(chunks):
            page = document.add_page(595, 842)
            heading = f"Scenario: {report['scenario_id']}"
            if part:
                heading += f" (continued, part {part + 1})"
            page.text(MARGIN, 790, heading, size=16, style="bold")
            page.text(
                MARGIN,
                770,
                f"Horizon {report['horizon_days']} days, {report['replications']} "
                f"replications. Mean total cost ${report['total_mean_cost']:,.2f}. "
                f"Fill rate {report['portfolio_fill_rate']:.1%}.",
                size=9,
            )
            missed = missed_targets(report)
            if missed and not part:
                page.paragraph(
                    MARGIN,
                    758,
                    f"Missed the service target on validation: {', '.join(missed)}.",
                    595 - 2 * MARGIN,
                    size=8,
                )
            _component_bar(page, report, 728)
            y = _lane_chart(page, report, 680)
            for label, _, offset, align in COLUMNS:
                x = MARGIN + offset + (40 if align == "right" else 0)
                page.text(x, y, label, size=9, style="bold", align=align)
            page.line(MARGIN, y - 5, 595 - MARGIN, y - 5)
            for row in chunk:
                y -= 15
                for _, key, offset, align in COLUMNS:
                    if align == "right":
                        x = MARGIN + offset + 40
                        page.text(x, y, _format(key, row[key]), size=9, align="right")
                    else:
                        page.text(MARGIN + offset, y, _format(key, row[key]), size=9)
            _comparison_chart(page, reports, 150, max_height=100)
            _footer(page, len(document.pages), title)
    _lane_comparison_page(document, reports, title)
    _notes_page(document, reports, title)
    return document.to_bytes()


def write_report(
    summary_paths: list[str | Path],
    destination: str | Path,
    title: str = "Scenario comparison",
    order: str = "given",
) -> Path:
    path = Path(destination)
    data = build_report(summary_paths, title, order)
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError:
        raise InputError(f"{path} already exists; choose a new file name") from None
    return path
