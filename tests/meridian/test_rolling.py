"""Rolling-horizon re-planning."""

import csv
import json
from dataclasses import replace

import pytest

from meridian.cli import main
from meridian.demand import demand_traces
from meridian.engine import simulate_lane
from meridian.models import InputError
from meridian.planning import (
    REPLAN_SAMPLES,
    compare_rolling,
    forecast,
    level_changes,
    replan_level,
    rolling_plan,
    rolling_schedule,
)


@pytest.fixture
def short(settings):
    return replace(settings, horizon_days=6, replications=1)


def test_forecast_falls_back_to_configuration(lane, settings):
    assert forecast([], lane, settings) == (lane.daily_mean_kg, lane.daily_sd_kg)
    scaled = replace(settings, demand_multiplier=2.0)
    assert forecast([9.0, 11.0], lane, scaled) == (lane.daily_mean_kg * 2, lane.daily_sd_kg * 2)


def test_forecast_from_history(lane, settings):
    mean_kg, sd_kg = forecast([8.0, 10.0, 12.0], lane, settings)
    assert mean_kg == pytest.approx(10.0)
    assert sd_kg == pytest.approx((8 / 3) ** 0.5)


def test_replan_level_is_reproducible(lane, settings):
    first = replan_level(lane, settings, 10.0, 2.0, seed=5)
    assert first == replan_level(lane, settings, 10.0, 2.0, seed=5)
    assert first > 0


def test_replan_level_grows_with_demand(lane, settings):
    low = replan_level(lane, settings, 10.0, 2.0, seed=5)
    high = replan_level(lane, settings, 30.0, 6.0, seed=5)
    assert high > low


def test_replan_handles_zero_spread(lane, settings):
    assert replan_level(lane, settings, 10.0, 0.0, seed=1) >= 10.0


def test_replan_samples_constant():
    assert REPLAN_SAMPLES == 12


def test_rolling_trial_shape(lane, short):
    trace = demand_traces(lane, short, "validation")[0]
    trial, plan = rolling_plan(lane, short, trace, review_period_days=3)
    assert len(trial.periods) == len(trace)
    assert [p.day for p in trial.periods] == list(range(1, len(trace) + 1))
    assert plan and plan[0]["day"] == 1
    assert all(row["base_stock_kg"] > 0 for row in plan)


def test_rolling_costs_reconcile(lane, short):
    trace = demand_traces(lane, short, "validation")[0]
    trial, _ = rolling_plan(lane, short, trace, review_period_days=3)
    for period in trial.periods:
        assert period.total_cost == pytest.approx(
            period.holding_cost + period.backlog_cost + period.delivery_cost + period.purchase_cost
        )
        assert period.inventory_kg == 0 or period.backlog_kg == 0
    assert 0 <= trial.fill_rate <= 1


def test_rolling_is_reproducible(lane, short):
    trace = demand_traces(lane, short, "validation")[0]
    assert rolling_plan(lane, short, trace, 3) == rolling_plan(lane, short, trace, 3)


def test_constant_level_matches_simulator(lane, short, monkeypatch):
    import meridian.planning as planning

    monkeypatch.setattr(planning, "replan_level", lambda *args, **kwargs: 25.0)
    trace = demand_traces(lane, short, "validation")[0]
    rolling, _ = rolling_plan(lane, short, trace, review_period_days=3)
    fixed = simulate_lane(lane, 25.0, trace)
    for a, b in zip(rolling.periods, fixed.periods):
        assert a.inventory_kg == pytest.approx(b.inventory_kg)
        assert a.backlog_kg == pytest.approx(b.backlog_kg)
        assert a.ordered_kg == pytest.approx(b.ordered_kg)
        assert a.total_cost == pytest.approx(b.total_cost)


@pytest.mark.parametrize("review", [0, 91, -3])
def test_invalid_review_period(lane, short, review):
    with pytest.raises(InputError):
        rolling_plan(lane, short, (10.0,) * 5, review_period_days=review)


def test_invalid_demands(lane, short):
    with pytest.raises(InputError):
        rolling_plan(lane, short, (), review_period_days=3)
    with pytest.raises(InputError):
        rolling_plan(lane, short, (10.0, -1.0), review_period_days=3)


def test_compare_rolling_rows(lane, short):
    (row,) = compare_rolling((lane,), short, review_period_days=3)
    assert row["lane"] == lane.key
    assert row["static_base_stock_kg"] > 0
    assert row["static_mean_cost"] > 0 and row["rolling_mean_cost"] > 0
    assert 0 <= row["rolling_fill_rate"] <= 1


def test_rolling_command(tmp_path, capsys, lane):
    data = tmp_path / "lanes.csv"
    data.write_text(
        "site_id,product,daily_mean_kg,daily_sd_kg,lead_time_days,initial_inventory_kg,"
        "holding_cost_per_kg_day,backlog_cost_per_kg_day,delivery_cost_per_order,"
        "purchase_cost_per_kg\nExample,nitrogen,10,2,1,20,0.1,2,5,0.5\n"
    )
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps({"horizon_days": 5, "replications": 1, "stock_multipliers": [1.0, 1.5]})
    )
    code = main(
        [
            "rolling",
            "--data",
            str(data),
            "--config",
            str(config),
            "--review-days",
            "5",
            "--output",
            str(tmp_path / "out"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Example:nitrogen: static" in out
    with (tmp_path / "out" / "rolling.csv").open(newline="") as stream:
        (row,) = list(csv.DictReader(stream))
    assert row["lane"] == "Example:nitrogen"


def test_rolling_schedule_rows(lane, short):
    other = replace(lane, site_id="Other")
    rows = rolling_schedule((other, lane), short, review_period_days=3)
    assert [row["lane"] for row in rows[:1]] == [lane.key]
    assert {row["lane"] for row in rows} == {lane.key, other.key}
    assert all(
        set(row) == {"lane", "day", "forecast_mean_kg", "forecast_sd_kg", "base_stock_kg"}
        for row in rows
    )


def test_rolling_schedule_replication_range(lane, short):
    with pytest.raises(InputError, match="replication"):
        rolling_schedule((lane,), short, 3, replication=2)


def test_level_changes_keeps_first_and_changes():
    schedule = [
        {"lane": "A", "day": 1, "base_stock_kg": 10.0},
        {"lane": "A", "day": 2, "base_stock_kg": 10.0},
        {"lane": "A", "day": 3, "base_stock_kg": 12.0},
        {"lane": "B", "day": 1, "base_stock_kg": 5.0},
        {"lane": "B", "day": 2, "base_stock_kg": 5.0},
    ]
    assert [(row["lane"], row["day"]) for row in level_changes(schedule)] == [
        ("A", 1),
        ("A", 3),
        ("B", 1),
    ]


def test_level_changes_empty():
    assert level_changes([]) == []


def test_rolling_command_writes_plan(tmp_path, capsys):
    data = tmp_path / "lanes.csv"
    data.write_text(
        "site_id,product,daily_mean_kg,daily_sd_kg,lead_time_days,initial_inventory_kg,"
        "holding_cost_per_kg_day,backlog_cost_per_kg_day,delivery_cost_per_order,"
        "purchase_cost_per_kg\nExample,nitrogen,10,2,1,20,0.1,2,5,0.5\n"
    )
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps({"horizon_days": 4, "replications": 1, "stock_multipliers": [1.0]})
    )
    assert (
        main(
            [
                "rolling",
                "--data",
                str(data),
                "--config",
                str(config),
                "--review-days",
                "4",
                "--output",
                str(tmp_path),
            ]
        )
        == 0
    )
    with (tmp_path / "rolling_plan.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["day"] == "1"
    assert "Base-stock changes" in capsys.readouterr().out
