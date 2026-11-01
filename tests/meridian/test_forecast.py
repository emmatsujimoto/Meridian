"""Demand estimates from daily history."""

import csv
from datetime import date, timedelta

import pytest

from meridian.forecast import (
    backtest,
    estimate_all,
    format_estimates,
    read_history,
    recent_window,
    smoothed,
    update_inputs,
)
from meridian.inputs import load_lanes
from meridian.models import InputError


def _history(tmp_path, values, site="Example", product="nitrogen"):
    path = tmp_path / "history.csv"
    start = date(2026, 1, 1)
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["site_id", "product", "date", "demand_kg"])
        for offset, value in enumerate(values):
            writer.writerow([site, product, (start + timedelta(days=offset)).isoformat(), value])
    return path


def test_constant_history(tmp_path):
    estimates = estimate_all(read_history(_history(tmp_path, [50.0] * 40)))
    assert estimates[0].mean_kg == pytest.approx(50)
    assert estimates[0].sd_kg == pytest.approx(0)
    assert estimates[0].backtest_mape == pytest.approx(0)


def test_window_is_recent_days():
    assert recent_window(list(range(100))) == list(range(72, 100))


def test_smoothing_of_constant_series_is_constant():
    assert smoothed([10.0, 10.0, 10.0]) == pytest.approx(10)


def test_short_history_has_no_backtest():
    assert backtest([1.0] * 10) is None


def test_empty_history_rejected(tmp_path):
    with pytest.raises(InputError):
        read_history(_history(tmp_path, []))


def test_apply_updates_csv(tmp_path, lane):
    from dataclasses import asdict

    data = tmp_path / "lanes.csv"
    with data.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(asdict(lane)))
        writer.writeheader()
        writer.writerow(asdict(lane))
    update_inputs(data, _history(tmp_path, [30.0] * 30))
    assert load_lanes(data)[0].daily_mean_kg == pytest.approx(30)


def test_table_lists_lanes(tmp_path):
    table = format_estimates(estimate_all(read_history(_history(tmp_path, [5.0] * 30))))
    assert "Example:nitrogen" in table
