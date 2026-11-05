"""Snapshot comparison between two completed result bundles."""

import csv
import io
import json
from dataclasses import replace

import pytest

from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run
from meridian.snapshots import (
    COLUMNS,
    LaneSnapshot,
    Snapshot,
    diff_csv,
    diff_json,
    diff_snapshots,
    diff_table,
    diff_totals,
    filter_rows,
    largest_changes,
    load_snapshot,
    product_table,
    product_totals,
    write_diff,
)


def _snapshot(scenario, *lanes, horizon=8):
    return Snapshot(scenario, horizon, scenario * 2, tuple(lanes))


def _lane(name, base=100.0, inventory=50.0, backlog=0.0):
    return LaneSnapshot(name, base, inventory, backlog)


@pytest.fixture
def bundle(tmp_path, lane, settings):
    return export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"


def test_net_position():
    assert _lane("A", inventory=30.0, backlog=12.5).net_position_kg == 17.5


def test_load_snapshot_reads_final_day(bundle, settings):
    snapshot = load_snapshot(bundle)
    assert snapshot.horizon_days == settings.horizon_days
    assert snapshot.scenario_id == settings.scenario_id
    assert len(snapshot.lanes) == 1
    with (bundle.parent / "daily_results.csv").open(newline="", encoding="utf-8") as stream:
        final = [row for row in csv.DictReader(stream) if int(row["day"]) == settings.horizon_days]
    expected = sum(float(row["inventory_kg"]) for row in final) / len(final)
    assert snapshot.lanes[0].ending_inventory_kg == pytest.approx(expected)
    assert snapshot.lanes[0].ending_backlog_kg >= 0


def test_load_snapshot_rejects_tampered_bundle(bundle):
    daily = bundle.parent / "daily_results.csv"
    daily.write_text(daily.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(InputError):
        load_snapshot(bundle)


def test_load_snapshot_requires_summary(tmp_path):
    with pytest.raises(InputError):
        load_snapshot(tmp_path / "missing.json")


def test_same_bundle_is_unchanged(bundle):
    snapshot = load_snapshot(bundle)
    rows = diff_snapshots(snapshot, snapshot)
    assert [row["status"] for row in rows] == ["unchanged"]
    assert rows[0]["inventory_change_kg"] == 0


def test_two_runs_compare(tmp_path, lane, settings):
    a = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    b = (
        export_run(run_scenario((lane,), replace(settings, scenario_id="alternate")), tmp_path)
        / "summary.json"
    )
    rows = diff_snapshots(load_snapshot(a), load_snapshot(b))
    assert len(rows) == 1
    assert rows[0]["lane"] == "Example:nitrogen"


def test_different_horizons_rejected(tmp_path, lane, settings):
    a = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    b = (
        export_run(run_scenario((lane,), replace(settings, horizon_days=3)), tmp_path)
        / "summary.json"
    )
    with pytest.raises(InputError, match="same horizon"):
        diff_snapshots(load_snapshot(a), load_snapshot(b))


def test_more_and_less_stock():
    before = _snapshot("a", _lane("A", inventory=10.0), _lane("B", inventory=40.0))
    after = _snapshot("b", _lane("A", inventory=25.0), _lane("B", inventory=5.0))
    rows = {row["lane"]: row for row in diff_snapshots(before, after)}
    assert rows["A"]["status"] == "more stock"
    assert rows["A"]["inventory_change_kg"] == 15.0
    assert rows["B"]["status"] == "less stock"
    assert rows["B"]["inventory_change_kg"] == -35.0


def test_backlog_or_base_stock_change():
    before = _snapshot("a", _lane("A", backlog=0.0), _lane("B", base=100.0))
    after = _snapshot("b", _lane("A", backlog=7.0), _lane("B", base=140.0))
    rows = {row["lane"]: row for row in diff_snapshots(before, after)}
    assert rows["A"]["status"] == "changed"
    assert rows["A"]["backlog_after_kg"] == 7.0
    assert rows["B"]["status"] == "changed"
    assert rows["B"]["base_stock_after_kg"] == 140.0


def test_added_and_removed_lanes():
    before = _snapshot("a", _lane("A"), _lane("B"))
    after = _snapshot("b", _lane("B"), _lane("C", inventory=12.0))
    rows = diff_snapshots(before, after)
    assert [(row["lane"], row["status"]) for row in rows] == [
        ("A", "removed"),
        ("B", "unchanged"),
        ("C", "added"),
    ]
    removed = rows[0]
    assert removed["inventory_after_kg"] is None
    assert removed["inventory_change_kg"] is None
    added = rows[2]
    assert added["inventory_before_kg"] is None
    assert added["inventory_after_kg"] == 12.0


def test_rows_sorted_by_lane():
    before = _snapshot("a", _lane("Z"), _lane("M"), _lane("A"))
    rows = diff_snapshots(before, before)
    assert [row["lane"] for row in rows] == ["A", "M", "Z"]


def test_totals():
    before = _snapshot("a", _lane("A", inventory=10.0), _lane("B"), _lane("C", inventory=30.0))
    after = _snapshot("b", _lane("A", inventory=20.0), _lane("C", inventory=25.0), _lane("D"))
    totals = diff_totals(diff_snapshots(before, after))
    assert totals["lanes"] == 4
    assert totals["more_stock"] == 1
    assert totals["less_stock"] == 1
    assert totals["added"] == 1
    assert totals["removed"] == 1
    assert totals["unchanged"] == 0
    assert totals["inventory_change_kg"] == pytest.approx(5.0)


def test_filter_rows():
    before = _snapshot("a", _lane("A", inventory=10.0), _lane("B"))
    after = _snapshot("b", _lane("A", inventory=20.0), _lane("B"))
    rows = diff_snapshots(before, after)
    assert filter_rows(rows) == rows
    assert [row["lane"] for row in filter_rows(rows, ("more stock",))] == ["A"]
    assert filter_rows(rows, ("added",)) == []


def test_filter_rows_unknown_status():
    with pytest.raises(InputError, match="Unknown snapshot status"):
        filter_rows([], ("missing",))


def test_largest_changes():
    before = _snapshot(
        "a", _lane("A", inventory=10.0), _lane("B", inventory=10.0), _lane("C", inventory=10.0)
    )
    after = _snapshot(
        "b", _lane("A", inventory=12.0), _lane("B", inventory=50.0), _lane("C", inventory=0.0)
    )
    rows = largest_changes(diff_snapshots(before, after), 2)
    assert [row["lane"] for row in rows] == ["B", "C"]


def test_largest_changes_skips_missing_sides():
    before = _snapshot("a", _lane("A"))
    after = _snapshot("b", _lane("B"))
    assert largest_changes(diff_snapshots(before, after), 5) == []


def test_largest_changes_requires_positive_count():
    with pytest.raises(InputError):
        largest_changes([], 0)


def test_table_lists_every_lane():
    before = _snapshot("baseline", _lane("A", inventory=1000.0), _lane("B"))
    after = _snapshot("higher", _lane("A", inventory=2500.0), _lane("C"))
    rows = diff_snapshots(before, after)
    text = diff_table(before, after, rows)
    assert text.startswith("# Inventory snapshot comparison: baseline -> higher")
    assert "| A | more stock | 100 | 100 | 1,000 | 2,500 | +1,500 | 0 | 0 |" in text
    assert "| B | removed | 100 | - | 50 | - | - | 0 | - |" in text
    assert "| added | 1 |" in text
    assert "Net change in ending inventory: +1,500 kg." in text


def test_csv_has_fixed_columns():
    before = _snapshot("a", _lane("A"))
    after = _snapshot("b", _lane("B"))
    text = diff_csv(diff_snapshots(before, after))
    rows = list(csv.DictReader(io.StringIO(text)))
    assert tuple(rows[0]) == COLUMNS
    assert rows[0]["inventory_after_kg"] == ""
    assert rows[1]["inventory_after_kg"] == "50.0"


def test_json_includes_fingerprints():
    before = _snapshot("a", _lane("A"))
    after = _snapshot("b", _lane("A", inventory=60.0))
    document = json.loads(diff_json(before, after, diff_snapshots(before, after)))
    assert document["before"] == {"scenario_id": "a", "input_sha256": "aa"}
    assert document["after"]["input_sha256"] == "bb"
    assert document["totals"]["more_stock"] == 1
    assert document["lanes"][0]["inventory_change_kg"] == 10.0


def test_write_diff(tmp_path):
    path = write_diff("text\n", tmp_path / "diff.md")
    assert path.read_text(encoding="utf-8") == "text\n"
    with pytest.raises(InputError, match="already exists"):
        write_diff("again\n", path)
    with pytest.raises(InputError, match="does not exist"):
        write_diff("text\n", tmp_path / "missing" / "diff.md")


def test_product_totals():
    before = _snapshot(
        "a",
        _lane("North:nitrogen", inventory=10.0),
        _lane("South:nitrogen", inventory=20.0, backlog=4.0),
        _lane("North:oxygen", inventory=5.0),
    )
    after = _snapshot(
        "b",
        _lane("North:nitrogen", inventory=15.0),
        _lane("South:nitrogen", inventory=20.0),
        _lane("East:oxygen", inventory=8.0),
    )
    totals = {entry["product"]: entry for entry in product_totals(diff_snapshots(before, after))}
    assert sorted(totals) == ["nitrogen", "oxygen"]
    assert totals["nitrogen"]["lanes"] == 2
    assert totals["nitrogen"]["inventory_change_kg"] == 5.0
    assert totals["nitrogen"]["backlog_change_kg"] == -4.0
    assert totals["oxygen"]["lanes"] == 2
    assert totals["oxygen"]["inventory_before_kg"] == 5.0
    assert totals["oxygen"]["inventory_after_kg"] == 8.0


def test_product_totals_empty():
    assert product_totals([]) == []


def test_product_table():
    before = _snapshot("a", _lane("North:argon", inventory=1200.0))
    after = _snapshot("b", _lane("North:argon", inventory=900.0))
    text = product_table(diff_snapshots(before, after))
    assert "| argon | 1 | 1,200 | 900 | -300 | +0 |" in text


def test_product_table_header_only_when_empty():
    lines = product_table([]).splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("| Product |")
