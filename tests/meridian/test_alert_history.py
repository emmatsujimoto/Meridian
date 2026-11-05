"""Alert summary and alerts --history."""

import csv
from dataclasses import replace

import pytest

from meridian.alerts import alert_history, alert_summary, write_history
from meridian.cli import main
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run


@pytest.fixture
def bundle(tmp_path, lane, settings):
    runs = tmp_path / "runs"
    runs.mkdir()
    short = replace(settings, stock_multipliers=(0.5,))
    return export_run(run_scenario((lane,), short), runs)


def _summary(bundle):
    return bundle / "summary.json"


def test_history_matches_summary(bundle):
    history = alert_history(_summary(bundle))
    summary = alert_summary(_summary(bundle))
    assert history
    assert sum(row["stockout_days"] for row in summary) == len(history)
    assert all(item["backlog_kg"] > 0 for item in history)


def test_history_sorted(bundle):
    history = alert_history(_summary(bundle))
    keys = [(item["lane"], item["replication"], item["day"]) for item in history]
    assert keys == sorted(keys)


def test_write_history(bundle, tmp_path):
    history = alert_history(_summary(bundle))
    path = write_history(history, tmp_path)
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(history)
    assert list(rows[0]) == ["lane", "replication", "day", "backlog_kg", "demand_kg"]
    assert rows[0]["lane"] == "Example:nitrogen"


def test_write_history_never_replaces(tmp_path):
    write_history([], tmp_path)
    with pytest.raises(InputError, match="already exists"):
        write_history([], tmp_path)


def test_write_history_missing_folder(tmp_path):
    with pytest.raises(InputError, match="does not exist"):
        write_history([], tmp_path / "missing")


def test_cli_summary(bundle, capsys):
    assert main(["alerts", str(_summary(bundle))]) == 0
    out = capsys.readouterr().out
    assert "Stockout days" in out
    assert "Example:nitrogen" in out


def test_cli_history(bundle, tmp_path, capsys):
    assert main(["alerts", str(_summary(bundle)), "--history", "--output", str(tmp_path)]) == 0
    assert (tmp_path / "alerts_history.csv").is_file()
    assert "alerts written to" in capsys.readouterr().out
