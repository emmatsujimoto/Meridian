"""SQLite export of completed bundles."""

import sqlite3

from meridian.planning import run_scenario
from meridian.reporting import export_run
from meridian.sqlite_export import export_to_sqlite


def test_rows_written(tmp_path, lane, settings):
    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    database = tmp_path / "results.sqlite"
    assert export_to_sqlite(bundle / "summary.json", database, "lane_results") == 1
    rows = (
        sqlite3.connect(database).execute("SELECT scenario_id, lane FROM lane_results").fetchall()
    )
    assert rows == [(settings.scenario_id, lane.key)]
