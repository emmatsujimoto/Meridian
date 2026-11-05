"""Demand sensing from recent sales."""

import json
from dataclasses import replace
from datetime import date

import pytest

from meridian.cli import main
from meridian.inputs import load_lanes
from meridian.models import InputError
from meridian.sensing import (
    SALES_COLUMNS,
    SensedLane,
    adjusted_lanes,
    largest_changes,
    sense_demand,
    sensed_rows,
    sensing_table,
    smooth,
    write_lanes,
)

HEADER = ",".join(SALES_COLUMNS)


@pytest.fixture
def lanes():
    return load_lanes("data/synthetic_sites.csv")


def _sales(tmp_path, *rows, header=HEADER):
    path = tmp_path / "sales.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


# Smoothing


def test_smooth_without_observations():
    assert smooth(100.0, [], 0.3) == 100.0


def test_smooth_constant_observations_equal_to_start():
    assert smooth(100.0, [100.0] * 5, 0.3) == pytest.approx(100.0)


def test_smooth_moves_towards_observations():
    result = smooth(100.0, [200.0] * 3, 0.3)
    assert 100.0 < result < 200.0


def test_smooth_alpha_one_or_zero_extremes():
    assert smooth(100.0, [150.0, 160.0], 1.0) in {100.0, 160.0}
    assert smooth(100.0, [150.0, 160.0], 0.0) in {100.0, 160.0}


# Reading sales


def test_no_sales_keeps_plan(tmp_path, lanes):
    sensed = sense_demand(lanes, _sales(tmp_path))
    assert [item.lane for item in sensed] == sorted(lane.key for lane in lanes)
    assert all(item.sensed_kg == item.planned_kg for item in sensed)
    assert all(item.observations == 0 and item.last_sale is None for item in sensed)


def test_sales_at_plan_keep_plan(tmp_path, lanes):
    rows = [f"2026-10-0{day},Harbor,nitrogen,800" for day in range(1, 6)]
    sensed = {item.lane: item for item in sense_demand(lanes, _sales(tmp_path, *rows))}
    harbor = sensed["Harbor:nitrogen"]
    assert harbor.sensed_kg == pytest.approx(800.0)
    assert harbor.observations == 5
    assert harbor.last_sale == date(2026, 10, 5)


def test_higher_sales_raise_forecast(tmp_path, lanes):
    rows = [f"2026-10-0{day},Summit,argon,180" for day in range(1, 8)]
    item = {i.lane: i for i in sense_demand(lanes, _sales(tmp_path, *rows))}["Summit:argon"]
    assert 120.0 < item.sensed_kg < 180.0
    assert item.change > 0


def test_rows_sorted_by_date(tmp_path, lanes):
    rows = ["2026-10-03,Meadow,oxygen,300", "2026-10-01,Meadow,oxygen,300"]
    item = {i.lane: i for i in sense_demand(lanes, _sales(tmp_path, *rows))}["Meadow:oxygen"]
    assert item.last_sale == date(2026, 10, 3)


def test_other_lanes_unaffected(tmp_path, lanes):
    rows = ["2026-10-01,Harbor,oxygen,900"]
    sensed = {i.lane: i for i in sense_demand(lanes, _sales(tmp_path, *rows))}
    assert sensed["Summit:nitrogen"].sensed_kg == 400.0


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("2026-10-01,Nowhere,nitrogen,10", "unknown product-location"),
        ("2026-13-01,Harbor,nitrogen,10", "Sales row 2"),
        ("2026-10-01,Harbor,nitrogen,-5", "Sales row 2"),
        ("2026-10-01,Harbor,nitrogen,abc", "Sales row 2"),
        ("2026-10-01,Harbor,nitrogen", "missing or extra values"),
    ],
)
def test_invalid_sales_rows(tmp_path, lanes, row, message):
    with pytest.raises(InputError, match=message):
        sense_demand(lanes, _sales(tmp_path, row))


def test_duplicate_date(tmp_path, lanes):
    rows = ["2026-10-01,Harbor,nitrogen,10", "2026-10-01,Harbor,nitrogen,12"]
    with pytest.raises(InputError, match="duplicate date"):
        sense_demand(lanes, _sales(tmp_path, *rows))


def test_wrong_columns(tmp_path, lanes):
    with pytest.raises(InputError, match="Sales CSV must have columns"):
        sense_demand(lanes, _sales(tmp_path, header="day,site,product,kg"))


def test_missing_file(tmp_path, lanes):
    with pytest.raises(InputError, match="Cannot read sales"):
        sense_demand(lanes, tmp_path / "missing.csv")


# Adjusted lanes and output


def test_adjusted_lanes_scale_mean_and_deviation(lanes):
    harbor = next(lane for lane in lanes if lane.key == "Harbor:nitrogen")
    sensed = [SensedLane("Harbor:nitrogen", 800.0, 1000.0, 3, date(2026, 10, 3))]
    adjusted = {lane.key: lane for lane in adjusted_lanes(lanes, sensed)}
    assert adjusted["Harbor:nitrogen"].daily_mean_kg == 1000.0
    assert adjusted["Harbor:nitrogen"].daily_sd_kg == pytest.approx(harbor.daily_sd_kg * 1.25)
    assert adjusted["Summit:argon"] == next(lane for lane in lanes if lane.key == "Summit:argon")


def test_adjusted_lanes_without_observations(lanes):
    sensed = [SensedLane("Harbor:nitrogen", 800.0, 800.0, 0, None)]
    assert adjusted_lanes(lanes, sensed) == lanes


def test_write_lanes_round_trip(tmp_path, lanes):
    changed = (replace(lanes[0], daily_mean_kg=812.5), *lanes[1:])
    path = write_lanes(changed, tmp_path / "sensed.csv")
    assert load_lanes(path) == tuple(sorted(changed, key=lambda lane: lane.key))


def test_write_lanes_never_replaces(tmp_path, lanes):
    path = write_lanes(lanes, tmp_path / "sensed.csv")
    with pytest.raises(InputError, match="already exists"):
        write_lanes(lanes, path)


def test_sensing_table():
    sensed = [
        SensedLane("Harbor:nitrogen", 800.0, 880.0, 4, date(2026, 10, 4)),
        SensedLane("Summit:argon", 120.0, 120.0, 0, None),
    ]
    lines = sensing_table(sensed).splitlines()
    assert lines[2] == "| Harbor:nitrogen | 800.0 | 880.0 | +10.0% | 4 | 2026-10-04 |"
    assert lines[3] == "| Summit:argon | 120.0 | 120.0 | +0.0% | 0 | - |"


def test_cli_sense(tmp_path, capsys):
    sales = _sales(tmp_path, "2026-10-01,Harbor,nitrogen,800")
    args = ["sense", "--data", "data/synthetic_sites.csv", "--sales", str(sales)]
    assert main(args) == 0
    assert "| Harbor:nitrogen | 800.0 | 800.0 |" in capsys.readouterr().out


def test_cli_sense_write(tmp_path, capsys):
    sales = _sales(tmp_path, "2026-10-01,Summit,argon,150")
    target = tmp_path / "sensed.csv"
    args = ["sense", "--data", "data/synthetic_sites.csv", "--sales", str(sales)]
    assert main([*args, "--write", str(target)]) == 0
    assert "Adjusted inputs written to" in capsys.readouterr().out
    assert len(load_lanes(target)) == 6


def test_cli_sense_bad_sales(tmp_path, capsys):
    sales = _sales(tmp_path, "2026-10-01,Nowhere,argon,150")
    args = ["sense", "--data", "data/synthetic_sites.csv", "--sales", str(sales)]
    assert main(args) == 2
    assert "unknown product-location" in capsys.readouterr().err


def test_sensed_rows():
    rows = sensed_rows([SensedLane("Harbor:nitrogen", 800.0, 880.0, 4, date(2026, 10, 4))])
    assert rows == [
        {
            "lane": "Harbor:nitrogen",
            "planned_kg": 800.0,
            "sensed_kg": 880.0,
            "change": pytest.approx(0.1),
            "observations": 4,
            "last_sale": "2026-10-04",
        }
    ]


def test_largest_changes():
    sensed = [
        SensedLane("A:nitrogen", 100.0, 110.0, 2, date(2026, 10, 2)),
        SensedLane("B:nitrogen", 100.0, 70.0, 2, date(2026, 10, 2)),
        SensedLane("C:nitrogen", 100.0, 150.0, 0, None),
    ]
    assert [item.lane for item in largest_changes(sensed, 2)] == ["B:nitrogen", "A:nitrogen"]
    with pytest.raises(InputError):
        largest_changes(sensed, 0)


def test_cli_sense_json(tmp_path, capsys):
    sales = _sales(tmp_path, "2026-10-01,Harbor,nitrogen,800")
    args = ["sense", "--data", "data/synthetic_sites.csv", "--sales", str(sales)]
    assert main([*args, "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 6
    assert {row["lane"]: row for row in rows}["Summit:argon"]["last_sale"] is None
