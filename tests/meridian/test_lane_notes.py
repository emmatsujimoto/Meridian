"""The optional notes column on product-location inputs."""

import csv
from dataclasses import replace

import pytest

from meridian.inputs import load_lanes
from meridian.models import InputError, Lane
from meridian.planning import run_scenario
from meridian.reporting import export_run

HEADER = (
    "site_id,product,daily_mean_kg,daily_sd_kg,lead_time_days,initial_inventory_kg,"
    "holding_cost_per_kg_day,backlog_cost_per_kg_day,delivery_cost_per_order,purchase_cost_per_kg"
)
ROW = "Harbor,nitrogen,800,160,2,2800,0.012,1.8,90,0.18"


def _write(tmp_path, text):
    path = tmp_path / "lanes.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_notes_column_optional(tmp_path):
    lanes = load_lanes(_write(tmp_path, f"{HEADER}\n{ROW}\n"))
    assert lanes[0].notes == ""


def test_notes_loaded(tmp_path):
    path = _write(tmp_path, f"{HEADER},notes\n{ROW},New tank from March\n")
    assert load_lanes(path)[0].notes == "New tank from March"


def test_notes_may_be_empty(tmp_path):
    path = _write(tmp_path, f"{HEADER},notes\n{ROW},\n")
    assert load_lanes(path)[0].notes == ""


def test_notes_trimmed(tmp_path):
    path = _write(tmp_path, f"{HEADER},notes\n{ROW},  Weekend deliveries only  \n")
    assert load_lanes(path)[0].notes == "Weekend deliveries only"


def test_notes_column_position_does_not_matter(tmp_path):
    path = _write(tmp_path, f"notes,{HEADER}\nShared trailer,{ROW}\n")
    assert load_lanes(path)[0].notes == "Shared trailer"


def test_notes_length_limit(tmp_path):
    path = _write(tmp_path, f"{HEADER},notes\n{ROW},{'x' * 201}\n")
    with pytest.raises(InputError, match="at most 200 characters"):
        load_lanes(path)


def test_notes_at_limit_accepted(tmp_path):
    path = _write(tmp_path, f"{HEADER},notes\n{ROW},{'x' * 200}\n")
    assert len(load_lanes(path)[0].notes) == 200


def test_notes_single_line(tmp_path):
    path = _write(tmp_path, f'{HEADER},notes\n{ROW},"first line\nsecond line"\n')
    with pytest.raises(InputError, match="one line"):
        load_lanes(path)


def test_required_values_still_checked(tmp_path):
    path = _write(tmp_path, f"{HEADER},notes\nHarbor,nitrogen,,160,2,2800,0.012,1.8,90,0.18,ok\n")
    with pytest.raises(InputError, match="missing or extra values"):
        load_lanes(path)


def test_unknown_column_still_rejected(tmp_path):
    path = _write(tmp_path, f"{HEADER},comment\n{ROW},hello\n")
    with pytest.raises(InputError, match="extra=\\['comment'\\]"):
        load_lanes(path)


def test_lane_rejects_non_text_notes(lane):
    with pytest.raises(InputError, match="notes must be text"):
        replace(lane, notes=5)


def test_example_data_still_loads():
    assert all(lane.notes == "" for lane in load_lanes("data/synthetic_sites.csv"))


def _lanes_csv(tmp_path, lane, settings):
    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    with (bundle / "lanes.csv").open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def test_lanes_csv_carries_notes(tmp_path, lane, settings):
    rows = _lanes_csv(tmp_path, replace(lane, notes="Tank inspection in May"), settings)
    assert rows[0]["notes"] == "Tank inspection in May"
    assert rows[0]["lane"] == "Example:nitrogen"


def test_lanes_csv_notes_last_column(tmp_path, lane, settings):
    rows = _lanes_csv(tmp_path, lane, settings)
    assert list(rows[0])[-1] == "notes"
    assert rows[0]["notes"] == ""


def test_lanes_csv_statistics_unchanged(tmp_path, lane, settings):
    rows = _lanes_csv(tmp_path, replace(lane, notes="Checked"), settings)
    assert float(rows[0]["base_stock_kg"]) > 0
    assert rows[0]["validation_target_met"] in {"True", "False"}


def test_notes_part_of_lane_equality():
    first = Lane("Example", "nitrogen", 10, 2, 1, 20, 0.1, 2, 5, 0.5)
    assert first != replace(first, notes="different")
