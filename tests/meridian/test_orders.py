"""Order event export."""

import csv
import json
from dataclasses import replace

import pytest

from meridian.planning import run_scenario
from meridian.reporting import export_run, order_events


def test_one_event_per_order(lane, settings):
    result = run_scenario((lane,), settings)
    events = order_events(result)
    ordered = [
        p.ordered_kg for t in result.results[0].validation_trials for p in t.periods if p.ordered_kg
    ]
    assert len(events) == len(ordered)
    assert sum(e["quantity_kg"] for e in events) == pytest.approx(sum(ordered))


def test_arrival_day_adds_lead_time(lane, settings):
    slow = replace(lane, lead_time_days=3)
    events = order_events(run_scenario((slow,), settings))
    assert events
    for event in events:
        assert event["arrival_day"] == event["order_day"] + 3
        assert event["arrives_within_horizon"] == (event["arrival_day"] <= settings.horizon_days)


def test_orders_file_in_bundle(tmp_path, lane, settings):
    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    manifest = json.loads((bundle / "COMPLETE.json").read_text())
    assert "orders.csv" in manifest["files"]
    with (bundle / "orders.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows and rows[0]["lane"] == lane.key
    assert float(rows[0]["quantity_kg"]) > 0
