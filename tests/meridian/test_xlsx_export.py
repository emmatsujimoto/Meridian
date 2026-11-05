"""Excel export of completed result bundles."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from meridian.cli import main
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run

openpyxl = pytest.importorskip("openpyxl")

from meridian.xlsx_export import export_workbook  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def bundle(tmp_path, lane, settings):
    other = replace(lane, site_id="Other", daily_mean_kg=20)
    return export_run(run_scenario((lane, other), settings), tmp_path)


def test_default_path_beside_bundle(bundle):
    path = export_workbook(bundle / "summary.json")
    assert path == bundle.parent / f"{bundle.name}.xlsx"
    assert path.is_file()
    assert not (bundle / f"{bundle.name}.xlsx").exists()


def test_sheets(bundle, tmp_path):
    path = export_workbook(bundle / "summary.json", tmp_path / "out.xlsx")
    workbook = openpyxl.load_workbook(path)
    assert workbook.sheetnames == ["Summary", "Lanes", "Candidates", "Costs", "Inputs"]


def test_summary_sheet_values(bundle, tmp_path):
    report = json.loads((bundle / "summary.json").read_text())
    sheet = openpyxl.load_workbook(export_workbook(bundle / "summary.json", tmp_path / "s.xlsx"))[
        "Summary"
    ]
    values = {
        sheet.cell(row=r, column=1).value: sheet.cell(row=r, column=2).value for r in range(3, 12)
    }
    assert values["Scenario"] == report["scenario_id"]
    assert values["Mean total cost (USD)"] == pytest.approx(report["total_mean_cost"])
    assert values["Product-locations"] == 2


def test_lane_rows_match_summary(bundle, tmp_path):
    report = json.loads((bundle / "summary.json").read_text())
    sheet = openpyxl.load_workbook(export_workbook(bundle / "summary.json", tmp_path / "l.xlsx"))[
        "Lanes"
    ]
    assert sheet.cell(row=1, column=1).value == "Product-location"
    for row_number, lane in enumerate(report["lanes"], 2):
        assert sheet.cell(row=row_number, column=1).value == lane["lane"]
        assert sheet.cell(row=row_number, column=4).value == pytest.approx(
            lane["validation_mean_cost"]
        )
        assert isinstance(sheet.cell(row=row_number, column=3).value, bool)


def test_candidates_are_numbers(bundle, tmp_path):
    sheet = openpyxl.load_workbook(export_workbook(bundle / "summary.json", tmp_path / "c.xlsx"))[
        "Candidates"
    ]
    assert sheet.max_row > 2
    assert isinstance(sheet.cell(row=2, column=2).value, (int, float))
    assert sheet.cell(row=2, column=4).number_format == "0.0%"


def test_cost_sheet_formulas(bundle, tmp_path):
    sheet = openpyxl.load_workbook(export_workbook(bundle / "summary.json", tmp_path / "f.xlsx"))[
        "Costs"
    ]
    assert sheet.cell(row=2, column=6).value == "=SUM(B2:E2)"
    assert sheet.cell(row=4, column=1).value == "All product-locations"
    assert sheet.cell(row=4, column=6).value == "=SUM(F2:F3)"


def test_daily_sheet_optional(bundle, tmp_path):
    path = export_workbook(bundle / "summary.json", tmp_path / "d.xlsx", include_daily=True)
    workbook = openpyxl.load_workbook(path)
    assert workbook.sheetnames[-1] == "Daily"
    assert workbook["Daily"].max_row > 2


def test_tampered_bundle_rejected(bundle):
    (bundle / "lanes.csv").write_text("changed")
    with pytest.raises(InputError, match="integrity"):
        export_workbook(bundle / "summary.json")


def test_output_must_be_xlsx(bundle, tmp_path):
    with pytest.raises(InputError, match=".xlsx"):
        export_workbook(bundle / "summary.json", tmp_path / "out.csv")


def test_missing_openpyxl_is_input_error(bundle, monkeypatch):
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    with pytest.raises(InputError, match="pip install"):
        export_workbook(bundle / "summary.json")


def test_export_command(bundle, tmp_path, capsys):
    target = tmp_path / "cli.xlsx"
    assert main(["export", str(bundle / "summary.json"), "--xlsx", "--output", str(target)]) == 0
    assert "Workbook saved" in capsys.readouterr().out
    assert target.is_file()


def test_export_command_requires_format(bundle):
    with pytest.raises(SystemExit):
        main(["export", str(bundle / "summary.json")])


def test_inputs_sheet(bundle, tmp_path):
    report = json.loads((bundle / "summary.json").read_text())
    sheet = openpyxl.load_workbook(export_workbook(bundle / "summary.json", tmp_path / "i.xlsx"))[
        "Inputs"
    ]
    settings = report["inputs"]["settings"]
    assert sheet.cell(row=1, column=1).value == "Scenario settings"
    assert sheet.cell(row=2, column=1).value == "scenario_id"
    assert sheet.cell(row=2, column=2).value == settings["scenario_id"]
    header_row = len(settings) + 4
    assert sheet.cell(row=header_row, column=1).value == "Site"
    sites = {sheet.cell(row=header_row + i, column=1).value for i in (1, 2)}
    assert sites == {"Example", "Other"}


def test_missed_targets_highlighted(tmp_path, lane, settings):
    strict = replace(settings, service_target=1.0, stock_multipliers=(0.5,))
    bundle = export_run(run_scenario((lane,), strict), tmp_path)
    assert (
        json.loads((bundle / "summary.json").read_text())["lanes"][0]["validation_target_met"]
        is False
    )
    sheet = openpyxl.load_workbook(export_workbook(bundle / "summary.json", tmp_path / "h.xlsx"))[
        "Lanes"
    ]
    assert sheet.cell(row=2, column=1).fill.fgColor.rgb == "00FBE2E2"


def test_target_met_lanes_not_highlighted(tmp_path, lane, settings):
    easy = replace(settings, service_target=0.01)
    bundle = export_run(run_scenario((lane,), easy), tmp_path)
    sheet = openpyxl.load_workbook(export_workbook(bundle / "summary.json", tmp_path / "e.xlsx"))[
        "Lanes"
    ]
    assert sheet.cell(row=2, column=7).value is True
    assert sheet.cell(row=2, column=1).fill.fgColor.rgb != "00FBE2E2"
