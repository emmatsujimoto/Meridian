"""End-of-horizon transfers weighted by lane priority."""

import csv
import json
from dataclasses import replace
from pathlib import Path

import pytest

from meridian.cli import main
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.transfers import (
    Transfer,
    load_priorities,
    positions,
    suggest_transfers,
    transfer_summary,
    write_transfers,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def two_sites(lane, settings):
    big = replace(lane, daily_mean_kg=200, daily_sd_kg=40)
    lanes = (
        replace(big, site_id="North", initial_inventory_kg=6000),
        replace(big, site_id="South", initial_inventory_kg=0, lead_time_days=12),
    )
    return run_scenario(lanes, settings)


def _write(tmp_path, data):
    path = tmp_path / "priorities.json"
    path.write_text(json.dumps(data))
    return path


def test_load_priorities(tmp_path):
    assert load_priorities(_write(tmp_path, {"Harbor:oxygen": 3})) == {"Harbor:oxygen": 3.0}
    assert load_priorities(None) == {}


@pytest.mark.parametrize(
    "data, message",
    [
        ([], "JSON object"),
        ({"Harbor": 2}, "lanes like"),
        ({"Harbor:oxygen": 0}, "priority of Harbor:oxygen"),
        ({"Harbor:oxygen": 101}, "at most 100"),
    ],
)
def test_invalid_priorities(tmp_path, data, message):
    with pytest.raises(InputError, match=message):
        load_priorities(_write(tmp_path, data))


def test_positions(two_sites):
    found = positions(two_sites)
    assert found["North:nitrogen"] > 0
    assert found["South:nitrogen"] < 0


def test_two_lanes_surplus_moves_to_short_site(two_sites):
    transfers = suggest_transfers(two_sites)
    assert transfers
    assert {t.from_lane for t in transfers} == {"North:nitrogen"}
    assert {t.to_lane for t in transfers} == {"South:nitrogen"}
    assert all(t.quantity_kg > 0 for t in transfers)


def test_never_more_than_surplus(two_sites):
    found = positions(two_sites)
    moved = sum(t.quantity_kg for t in suggest_transfers(two_sites))
    assert moved <= found["North:nitrogen"] + 1e-6


def test_products_never_mix(lane, settings):
    big = replace(lane, daily_mean_kg=200, daily_sd_kg=40)
    lanes = (
        replace(big, site_id="North", initial_inventory_kg=6000),
        replace(big, site_id="South", product="oxygen", initial_inventory_kg=0),
    )
    assert suggest_transfers(run_scenario(lanes, settings)) == []


def test_summary_rows(two_sites):
    transfers = suggest_transfers(two_sites)
    (row,) = transfer_summary(transfers, two_sites)
    assert row["lane"] == "South:nitrogen"
    assert row["priority"] == 1.0
    assert row["received_kg"] == pytest.approx(sum(t.quantity_kg for t in transfers))
    assert row["still_short_kg"] == pytest.approx(
        max(0.0, row["shortfall_kg"] - row["received_kg"])
    )


def test_write_transfers(tmp_path):
    path = write_transfers([Transfer("nitrogen", "A:nitrogen", "B:nitrogen", 12.345)], tmp_path)
    with path.open(newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows == [
        ["product", "from_lane", "to_lane", "quantity_kg"],
        ["nitrogen", "A:nitrogen", "B:nitrogen", "12.3"],
    ]


def test_transfers_command(tmp_path, capsys):
    code = main(
        [
            "transfers",
            "--data",
            str(ROOT / "data/synthetic_sites.csv"),
            "--config",
            str(ROOT / "config/quickstart.json"),
            "--output",
            str(tmp_path),
        ]
    )
    assert code == 0
    assert "transfers saved to" in capsys.readouterr().out
    assert (tmp_path / "transfers.csv").is_file()


@pytest.fixture
def three_short(lane, settings):
    big = replace(lane, daily_mean_kg=200, daily_sd_kg=40)
    lanes = (
        replace(big, site_id="North", initial_inventory_kg=20000),
        replace(big, site_id="East", initial_inventory_kg=0, lead_time_days=12),
        replace(big, site_id="South", initial_inventory_kg=0, lead_time_days=12),
        replace(big, site_id="West", initial_inventory_kg=0, lead_time_days=12),
    )
    return run_scenario(lanes, settings)


def test_equal_weights_with_ample_surplus_cover_everyone(three_short):
    rows = transfer_summary(suggest_transfers(three_short), three_short)
    assert len(rows) == 3
    for row in rows:
        assert row["still_short_kg"] == pytest.approx(0.0, abs=1e-6)


def test_each_lane_receives_at_most_its_shortfall(three_short):
    found = positions(three_short)
    received = {}
    for transfer in suggest_transfers(three_short):
        received[transfer.to_lane] = received.get(transfer.to_lane, 0.0) + transfer.quantity_kg
    for lane, amount in received.items():
        assert amount <= -found[lane] + 1e-6


def test_no_transfers_without_surplus(lane, settings):
    big = replace(
        lane, daily_mean_kg=200, daily_sd_kg=40, initial_inventory_kg=0, lead_time_days=12
    )
    lanes = (replace(big, site_id="East"), replace(big, site_id="West"))
    assert suggest_transfers(run_scenario(lanes, settings)) == []


def test_transfers_command_with_priorities(tmp_path, capsys):
    priorities = _write(tmp_path, {"Harbor:oxygen": 2})
    code = main(
        [
            "transfers",
            "--data",
            str(ROOT / "data/synthetic_sites.csv"),
            "--config",
            str(ROOT / "config/quickstart.json"),
            "--priorities",
            str(priorities),
            "--output",
            str(tmp_path / "out"),
        ]
    )
    assert code == 0
    assert (tmp_path / "out" / "transfers.csv").is_file()
