"""Replaying recorded demand history."""

from dataclasses import replace

import pytest

from meridian.demand import demand_traces, load_demand_history
from meridian.models import InputError, Settings
from meridian.planning import run_scenario


def _history(tmp_path, rows):
    path = tmp_path / "history.csv"
    path.write_text("site_id,product,day,demand_kg\n" + "\n".join(rows) + "\n")
    return path


def _days(site, product, values):
    return [f"{site},{product},{day},{value}" for day, value in enumerate(values, start=1)]


def test_load_history(tmp_path):
    path = _history(tmp_path, _days("Example", "nitrogen", [10, 12, 9]))
    assert load_demand_history(path) == {"Example:nitrogen": [10.0, 12.0, 9.0]}


def test_rows_in_any_order(tmp_path):
    path = _history(tmp_path, ["Example,nitrogen,2,12", "Example,nitrogen,1,10"])
    assert load_demand_history(path)["Example:nitrogen"] == [10.0, 12.0]


@pytest.mark.parametrize(
    "rows, message",
    [
        (["Example,nitrogen,1,10", "Example,nitrogen,1,11"], "repeated"),
        (["Example,nitrogen,0,10"], "1 or more"),
        (["Example,nitrogen,1,10", "Example,nitrogen,3,10"], "missing days"),
        (["Example,nitrogen,one,10"], "History row 2"),
        (["Example,nitrogen,1,-5"], "demand_kg"),
        (["Example,nitrogen,1,"], "missing values"),
    ],
)
def test_invalid_history(tmp_path, rows, message):
    with pytest.raises(InputError, match=message):
        load_demand_history(_history(tmp_path, rows))


def test_wrong_columns(tmp_path):
    path = tmp_path / "history.csv"
    path.write_text("site,product,day,kg\nA,nitrogen,1,5\n")
    with pytest.raises(InputError, match="columns"):
        load_demand_history(path)


def test_replay_traces(tmp_path, lane, settings):
    path = _history(tmp_path, _days("Example", "nitrogen", range(10, 20)))
    replay = replace(settings, demand_history=str(path), demand_multiplier=2.0)
    traces = demand_traces(lane, replay, "validation")
    assert len(traces) == settings.replications
    assert traces[0] == tuple(2.0 * v for v in range(10, 10 + settings.horizon_days))


def test_history_too_short(tmp_path, lane, settings):
    path = _history(tmp_path, _days("Example", "nitrogen", [10, 11]))
    with pytest.raises(InputError, match="covers 2 days"):
        demand_traces(lane, replace(settings, demand_history=str(path)), "training")


def test_lane_missing_from_history(tmp_path, lane, settings):
    path = _history(tmp_path, _days("Other", "nitrogen", range(10)))
    with pytest.raises(InputError, match="no rows for Example:nitrogen"):
        demand_traces(lane, replace(settings, demand_history=str(path)), "training")


def test_scenario_runs_on_history(tmp_path, lane, settings):
    path = _history(tmp_path, _days("Example", "nitrogen", [10] * settings.horizon_days))
    result = run_scenario((lane,), replace(settings, demand_history=str(path)))
    assert result.results[0].validation_trials[0].periods[0].demand_kg == 10.0


def test_setting_must_be_text():
    with pytest.raises(InputError, match="demand_history"):
        Settings(demand_history=5)
