"""Run alerts: stockout streaks, service and cost changes, and the written files."""

from dataclasses import replace

from meridian.alerts import (
    alert_counts,
    build_alerts,
    cost_alerts,
    longest_stockout,
    stockout_alerts,
    write_alerts,
)
from meridian.models import PeriodResult, Trial
from meridian.planning import run_scenario
from meridian.reporting import summary


def _trial(backlogs):
    periods = tuple(
        PeriodResult(day, 10, 0, b, 0, 10 - b, 0, 0, 0, 0) for day, b in enumerate(backlogs, 1)
    )
    return Trial("Example:nitrogen", 10, periods)


def test_longest_stockout_counts_consecutive_days():
    assert longest_stockout(_trial([0, 5, 5, 0, 5, 0])) == 2
    assert longest_stockout(_trial([0, 0, 0])) == 0


def test_short_lane_gets_stockout_alert(lane, settings):
    short = replace(lane, initial_inventory_kg=0, lead_time_days=2)
    result = run_scenario((short,), replace(settings, horizon_days=20, stock_multipliers=(2.0,)))
    alerts = stockout_alerts(result, {"stockout_streak_days": 1})
    assert alerts and alerts[0]["kind"] == "stockout"


def test_cost_alert_against_baseline(lane, settings):
    result = run_scenario((lane,), settings)
    baseline = summary(result)
    baseline["lanes"][0]["validation_mean_cost"] /= 2
    alerts = cost_alerts(result, baseline, {"cost_increase_pct": 10.0})
    assert [a["kind"] for a in alerts] == ["cost"]


def test_counts_and_files(tmp_path, lane, settings):
    alerts = build_alerts(run_scenario((lane,), settings))
    assert set(alert_counts(alerts)) == {"critical", "warning", "info"}
    paths = write_alerts(alerts, tmp_path)
    assert [p.name for p in paths] == ["alerts.csv", "alerts.md"]
    assert (tmp_path / "alerts.md").read_text(encoding="utf-8").startswith("# Alerts")
