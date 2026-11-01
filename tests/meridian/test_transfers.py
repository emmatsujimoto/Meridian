"""Suggested stock transfers between sites of the same product."""

from dataclasses import replace

from meridian.planning import run_scenario
from meridian.transfers import (
    load_distances,
    positions,
    suggest_transfers,
    write_transfer_report,
    write_transfers,
)


def _scenario(lane, settings):
    big = replace(lane, daily_mean_kg=200, daily_sd_kg=40)
    rich = replace(big, site_id="Harbor", initial_inventory_kg=5000)
    poor = replace(big, site_id="Summit", initial_inventory_kg=0)
    return run_scenario((rich, poor), settings)


def test_positions_sign(lane, settings):
    pos = positions(_scenario(lane, settings))
    assert pos["Harbor:nitrogen"] > 0 > pos["Summit:nitrogen"]


def test_surplus_moves_to_deficit(lane, settings):
    transfers = suggest_transfers(_scenario(lane, settings))
    assert [(t.source, t.destination) for t in transfers] == [("Harbor", "Summit")]
    assert transfers[0].quantity_kg >= 100


def test_files_written(tmp_path, lane, settings):
    transfers = suggest_transfers(_scenario(lane, settings))
    assert write_transfers(transfers, tmp_path).read_text().startswith("product,")
    report = write_transfer_report(transfers, tmp_path).read_text(encoding="utf-8")
    assert "## Nitrogen" in report


def test_distance_file(tmp_path):
    path = tmp_path / "distances.txt"
    path.write_text('{("North", "South"): 42}')
    assert load_distances(path) == {("North", "South"): 42.0}
