"""Excel export of a completed result bundle, for planners who work in spreadsheets.

The workbook is built from the bundle's verified files, so it always matches the bundle's
summary.json and CSV outputs. openpyxl is an optional dependency: install it with
``pip install meridian-gas-planner[xlsx]``.
"""

import csv
from pathlib import Path

from meridian.bundles import verify_bundle
from meridian.models import InputError

HEADER_FILL = "1F3864"
HEADER_FONT_COLOUR = "FFFFFF"
USD_FORMAT = "#,##0.00"
KG_FORMAT = "#,##0"
RATE_FORMAT = "0.0%"
LANE_COLUMNS = (
    ("lane", "Product-location", None),
    ("base_stock_kg", "Base stock (kg)", KG_FORMAT),
    ("training_target_met", "Target met in training", None),
    ("validation_mean_cost", "Mean cost (USD)", USD_FORMAT),
    ("validation_cost_sd", "Cost SD (USD)", USD_FORMAT),
    ("validation_mean_fill_rate", "Mean fill rate", RATE_FORMAT),
    ("validation_target_met", "Target met in validation", None),
    ("mean_holding_cost", "Holding cost (USD)", USD_FORMAT),
    ("mean_backlog_cost", "Backlog cost (USD)", USD_FORMAT),
    ("mean_delivery_cost", "Delivery cost (USD)", USD_FORMAT),
    ("mean_purchase_cost", "Purchase cost (USD)", USD_FORMAT),
    ("mean_terminal_inventory_kg", "Ending inventory (kg)", KG_FORMAT),
    ("mean_terminal_backlog_kg", "Ending backlog (kg)", KG_FORMAT),
)
COST_PARTS = (
    ("mean_holding_cost", "Holding"),
    ("mean_backlog_cost", "Backlog"),
    ("mean_delivery_cost", "Delivery"),
    ("mean_purchase_cost", "Purchase"),
)
DAILY_COLUMNS = (
    ("lane", "Product-location", None),
    ("replication", "Replication", KG_FORMAT),
    ("day", "Day", KG_FORMAT),
    ("demand_kg", "Demand (kg)", KG_FORMAT),
    ("inventory_kg", "Inventory (kg)", KG_FORMAT),
    ("backlog_kg", "Backlog (kg)", KG_FORMAT),
    ("ordered_kg", "Ordered (kg)", KG_FORMAT),
    ("served_immediately_kg", "Served from stock (kg)", KG_FORMAT),
    ("total_cost", "Total cost (USD)", USD_FORMAT),
)
INPUT_COLUMNS = (
    ("site_id", "Site", None),
    ("product", "Product", None),
    ("daily_mean_kg", "Mean daily demand (kg)", KG_FORMAT),
    ("daily_sd_kg", "Daily demand SD (kg)", KG_FORMAT),
    ("lead_time_days", "Lead time (days)", KG_FORMAT),
    ("initial_inventory_kg", "Starting inventory (kg)", KG_FORMAT),
    ("holding_cost_per_kg_day", "Holding cost (USD/kg/day)", "0.0000"),
    ("backlog_cost_per_kg_day", "Backlog cost (USD/kg/day)", "0.0000"),
    ("delivery_cost_per_order", "Delivery cost (USD/order)", USD_FORMAT),
    ("purchase_cost_per_kg", "Purchase cost (USD/kg)", "0.0000"),
)
MISSED_TARGET_FILL = "FBE2E2"
MAX_DAILY_ROWS = 200_000
CANDIDATE_COLUMNS = (
    ("lane", "Product-location", None),
    ("base_stock_kg", "Base stock (kg)", KG_FORMAT),
    ("mean_cost", "Mean training cost (USD)", USD_FORMAT),
    ("mean_fill_rate", "Mean training fill rate", RATE_FORMAT),
    ("meets_target", "Meets target", None),
)


def _openpyxl():
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError as exc:
        raise InputError(
            "Excel export needs openpyxl: pip install 'meridian-gas-planner[xlsx]'"
        ) from exc
    return openpyxl, Alignment, Font, PatternFill


def _read_csv(path: Path) -> list[dict]:
    try:
        with path.open(newline="", encoding="utf-8") as stream:
            return list(csv.DictReader(stream))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise InputError(f"Cannot read {path.name}: {exc}") from exc


def _cell_value(value):
    """Convert CSV text back to numbers and booleans so Excel can format and sum them."""
    if not isinstance(value, str):
        return value
    if value in {"True", "False"}:
        return value == "True"
    try:
        return float(value)
    except ValueError:
        return value


def _write_table(sheet, columns, rows, styles) -> None:
    alignment, font, fill = styles
    for column, (_, title, _) in enumerate(columns, 1):
        cell = sheet.cell(row=1, column=column, value=title)
        cell.font, cell.fill = font, fill
        cell.alignment = alignment
    for row_number, row in enumerate(rows, 2):
        for column, (key, _, number_format) in enumerate(columns, 1):
            cell = sheet.cell(row=row_number, column=column, value=_cell_value(row.get(key)))
            # print(row_number, key, row.get(key))
            if number_format:
                cell.number_format = number_format
    sheet.freeze_panes = "B2"


def _write_costs(sheet, lanes: list[dict], styles) -> None:
    """Cost breakdown per lane with live Excel totals, so edits to a component recalculate."""
    alignment, font, fill = styles
    titles = ["Product-location", *[f"{label} (USD)" for _, label in COST_PARTS], "Total (USD)"]
    for column, title in enumerate(titles, 1):
        cell = sheet.cell(row=1, column=column, value=title)
        cell.font, cell.fill, cell.alignment = font, fill, alignment
    last_part = chr(ord("A") + len(COST_PARTS))
    total_column = len(COST_PARTS) + 2
    for row_number, lane in enumerate(lanes, 2):
        sheet.cell(row=row_number, column=1, value=lane["lane"])
        for column, (key, _) in enumerate(COST_PARTS, 2):
            sheet.cell(row=row_number, column=column, value=lane[key]).number_format = USD_FORMAT
        total = sheet.cell(
            row=row_number,
            column=total_column,
            value=f"=SUM(B{row_number}:{last_part}{row_number})",
        )
        total.number_format = USD_FORMAT
    last_row = len(lanes) + 1
    totals_row = last_row + 1
    bold = _openpyxl()[2](bold=True)
    sheet.cell(row=totals_row, column=1, value="All product-locations").font = bold
    for column in range(2, total_column + 1):
        letter = chr(ord("A") + column - 1)
        cell = sheet.cell(
            row=totals_row, column=column, value=f"=SUM({letter}2:{letter}{last_row})"
        )
        cell.number_format, cell.font = USD_FORMAT, bold
    sheet.freeze_panes = "B2"


def _write_inputs(sheet, inputs: dict, styles) -> None:
    """Scenario settings above the lane input table, so results can be traced to inputs."""
    bold = _openpyxl()[2](bold=True)
    sheet.cell(row=1, column=1, value="Scenario settings").font = bold
    settings = inputs.get("settings", {})
    for row_number, (name, value) in enumerate(settings.items(), 2):
        sheet.cell(row=row_number, column=1, value=name)
        text = ", ".join(str(v) for v in value) if isinstance(value, list) else value
        sheet.cell(row=row_number, column=2, value=text)
    start = len(settings) + 3
    sheet.cell(row=start, column=1, value="Product-location inputs").font = bold
    alignment, font, fill = styles
    for column, (_, title, _) in enumerate(INPUT_COLUMNS, 1):
        cell = sheet.cell(row=start + 1, column=column, value=title)
        cell.font, cell.fill, cell.alignment = font, fill, alignment
    for row_number, lane in enumerate(inputs.get("lanes", []), start + 2):
        for column, (key, _, number_format) in enumerate(INPUT_COLUMNS, 1):
            cell = sheet.cell(row=row_number, column=column, value=lane.get(key))
            if number_format:
                cell.number_format = number_format


def _highlight_missed_targets(sheet, lane_count: int) -> None:
    """Shade lanes that missed the service target in validation."""
    fill = _openpyxl()[3]("solid", fgColor=MISSED_TARGET_FILL)
    target_column = [key for key, _, _ in LANE_COLUMNS].index("validation_target_met") + 1
    for row_number in range(2, lane_count + 2):
        if sheet.cell(row=row_number, column=target_column).value is False:
            for column in range(1, len(LANE_COLUMNS) + 1):
                sheet.cell(row=row_number, column=column).fill = fill


def _summary_rows(report: dict) -> list[tuple[str, object, str | None]]:
    return [
        ("Company", report["company"], None),
        ("Scenario", report["scenario_id"], None),
        ("Horizon (days)", report["horizon_days"], KG_FORMAT),
        ("Replications", report["replications"], KG_FORMAT),
        ("Mean total cost (USD)", report["total_mean_cost"], USD_FORMAT),
        ("Volume-weighted fill rate", report["portfolio_fill_rate"], RATE_FORMAT),
        ("Product-locations", len(report["lanes"]), KG_FORMAT),
        (
            "Product-locations meeting the target",
            sum(1 for row in report["lanes"] if row["validation_target_met"]),
            KG_FORMAT,
        ),
        ("Input fingerprint (SHA-256)", report["input_sha256"], None),
    ]


def export_workbook(
    summary_path: str | Path, output: str | Path | None = None, include_daily: bool = False
) -> Path:
    openpyxl, Alignment, Font, PatternFill = _openpyxl()
    summary_path = Path(summary_path).resolve()
    report = verify_bundle(summary_path)
    bundle = summary_path.parent
    destination = Path(output).resolve() if output else bundle.parent / f"{bundle.name}.xlsx"
    if destination.suffix.lower() != ".xlsx":
        raise InputError("Excel output must end in .xlsx")
    styles = (
        Alignment(wrap_text=True, vertical="center"),
        Font(bold=True, color=HEADER_FONT_COLOUR),
        PatternFill("solid", fgColor=HEADER_FILL),
    )
    workbook = openpyxl.Workbook()

    sheet = workbook.active
    sheet.title = "Summary"
    sheet.cell(row=1, column=1, value="Meridian scenario results").font = Font(bold=True, size=14)
    for row_number, (label, value, number_format) in enumerate(_summary_rows(report), 3):
        sheet.cell(row=row_number, column=1, value=label).font = Font(bold=True)
        cell = sheet.cell(row=row_number, column=2, value=value)
        if number_format:
            cell.number_format = number_format
    notes_start = len(_summary_rows(report)) + 5
    sheet.cell(row=notes_start, column=1, value="Model notes").font = Font(bold=True)
    for offset, note in enumerate(report.get("model_notes", []), 1):
        sheet.cell(row=notes_start + offset, column=1, value=note)
    sheet.column_dimensions["A"].width = 38
    sheet.column_dimensions["B"].width = 66

    lanes = workbook.create_sheet("Lanes")
    _write_table(lanes, LANE_COLUMNS, report["lanes"], styles)
    _highlight_missed_targets(lanes, len(report["lanes"]))
    lanes.column_dimensions["A"].width = 22
    for letter in "BCDEFGHIJKLM":
        lanes.column_dimensions[letter].width = 16

    candidates = workbook.create_sheet("Candidates")
    _write_table(candidates, CANDIDATE_COLUMNS, _read_csv(bundle / "candidates.csv"), styles)
    candidates.column_dimensions["A"].width = 22
    for letter in "BCDE":
        candidates.column_dimensions[letter].width = 16

    costs = workbook.create_sheet("Costs")
    _write_costs(costs, report["lanes"], styles)
    costs.column_dimensions["A"].width = 22
    for letter in "BCDEF":
        costs.column_dimensions[letter].width = 16

    inputs = workbook.create_sheet("Inputs")
    _write_inputs(inputs, report.get("inputs", {}), styles)
    inputs.column_dimensions["A"].width = 22
    for letter in "BCDEFGHIJ":
        inputs.column_dimensions[letter].width = 16

    if include_daily:
        daily_rows = _read_csv(bundle / "daily_results.csv")
        if len(daily_rows) > MAX_DAILY_ROWS:
            raise InputError(
                f"daily_results.csv has {len(daily_rows):,} rows; the Excel export allows "
                f"{MAX_DAILY_ROWS:,}. Export without --daily, or use the CSV directly."
            )
        daily = workbook.create_sheet("Daily")
        _write_table(daily, DAILY_COLUMNS, daily_rows, styles)
        daily.column_dimensions["A"].width = 22
        for letter in "BCDEFGHI":
            daily.column_dimensions[letter].width = 16

    try:
        workbook.save(destination)
    except OSError as exc:
        raise InputError(f"Cannot write {destination}: {exc}") from exc
    return destination
