"""Input contracts, rejecting malformed values before running an optimizer."""

import csv
import json
from dataclasses import asdict, replace

import pytest

from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError, Settings, identifier, integer, number


@pytest.mark.parametrize("value", [True, False, None, "", "bad", "NaN", "Infinity", -1])
def test_invalid_number(value):
    with pytest.raises(InputError):
        number(value, "quantity")


@pytest.mark.parametrize("value", ["bad/name", "..", "=SUM(A1)", "a b", "", "a" * 65, None])
def test_invalid_identifier(value):
    with pytest.raises(InputError):
        identifier(value, "name")


@pytest.mark.parametrize("value", [1.2, 0, 11, True])
def test_invalid_integer(value):
    with pytest.raises(InputError):
        integer(value, "days", 1, 10)


def test_zero_allowed_unless_strict():
    assert number(0, "value") == 0
    with pytest.raises(InputError):
        number(0, "value", strict=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("daily_mean_kg", 0),
        ("daily_sd_kg", -1),
        ("lead_time_days", 1.5),
        ("initial_inventory_kg", -1),
        ("holding_cost_per_kg_day", 0),
        ("backlog_cost_per_kg_day", 0),
        ("delivery_cost_per_order", -1),
        ("purchase_cost_per_kg", float("nan")),
        ("product", "unknown"),
    ],
)
def test_invalid_lane(lane, field, value):
    with pytest.raises(InputError):
        replace(lane, **{field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("horizon_days", 0),
        ("horizon_days", 367),
        ("replications", 0),
        ("seed", -1),
        ("demand_multiplier", 0),
        ("service_target", 1.1),
        ("service_target", 0),
        ("stock_multipliers", []),
        ("stock_multipliers", [1, 1]),
        ("stock_multipliers", [1, -1]),
    ],
)
def test_invalid_settings(field, value):
    with pytest.raises(InputError):
        Settings(**{field: value})


def test_settings_sorts_candidates():
    assert Settings(stock_multipliers=[2, 1]).stock_multipliers == (1, 2)


def write_lanes(path, rows, header=None):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=header or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_load_lanes_roundtrip(tmp_path, lane):
    path = tmp_path / "lanes.csv"
    write_lanes(path, [asdict(lane)])
    assert load_lanes(path) == (lane,)


def test_load_lanes_sorts(tmp_path, lane):
    path = tmp_path / "lanes.csv"
    other = replace(lane, site_id="Alpha")
    write_lanes(path, [asdict(lane), asdict(other)])
    assert load_lanes(path) == (other, lane)


def test_duplicate_lane(tmp_path, lane):
    path = tmp_path / "lanes.csv"
    write_lanes(path, [asdict(lane), asdict(lane)])
    with pytest.raises(InputError, match="duplicate lane"):
        load_lanes(path)


def test_missing_column(tmp_path, lane):
    path = tmp_path / "lanes.csv"
    row = asdict(lane)
    del row["daily_mean_kg"]
    write_lanes(path, [row])
    with pytest.raises(InputError, match="schema mismatch"):
        load_lanes(path)


def test_missing_value(tmp_path, lane):
    path = tmp_path / "lanes.csv"
    row = asdict(lane)
    row["daily_mean_kg"] = ""
    write_lanes(path, [row])
    with pytest.raises(InputError, match="row 2"):
        load_lanes(path)


def test_duplicate_header(tmp_path):
    path = tmp_path / "lanes.csv"
    path.write_text("site_id,site_id\na,b\n")
    with pytest.raises(InputError, match="duplicate column"):
        load_lanes(path)


def test_empty_csv(tmp_path, lane):
    path = tmp_path / "lanes.csv"
    path.write_text(",".join(asdict(lane)) + "\n")
    with pytest.raises(InputError, match="at least one"):
        load_lanes(path)


def test_nonexistent_files(tmp_path):
    for loader in (load_lanes, load_settings):
        with pytest.raises(InputError, match="Cannot read"):
            loader(tmp_path / "absent")


@pytest.mark.parametrize("text", ["[]", '{"seed":1,"seed":2}', '{"unknown":1}', "{bad"])
def test_invalid_settings_file(tmp_path, text):
    path = tmp_path / "settings.json"
    path.write_text(text)
    with pytest.raises(InputError):
        load_settings(path)


def test_settings_roundtrip(tmp_path, settings):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(asdict(settings)))
    assert load_settings(path) == settings


def test_description_allows_plain_words_only():
    assert Settings(description="Q3 demand study, high case.").description.startswith("Q3")
    with pytest.raises(InputError, match="description"):
        Settings(description="<b>bold</b>")
