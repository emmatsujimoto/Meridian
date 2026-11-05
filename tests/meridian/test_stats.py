"""Confidence intervals, percentiles and replication guidance."""

from dataclasses import replace
from statistics import fmean

import pytest

from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import compare_reports, export_run, summary
from meridian.stats import (
    bootstrap_interval,
    difference_interval,
    lane_uncertainty,
    mean_interval,
    percentile,
    portfolio_interval,
    replication_costs,
    replications_needed,
    sample_cv,
    uncertain_lanes,
)


def test_interval_contains_mean():
    values = [10.0, 12.0, 11.0, 13.0]
    low, high = mean_interval(values)
    assert low < fmean(values) < high


def test_interval_symmetric():
    low, high = mean_interval([10.0, 12.0, 11.0, 13.0])
    assert (low + high) / 2 == pytest.approx(11.5)


def test_interval_narrows_with_more_data():
    few = mean_interval([10.0, 14.0] * 2)
    many = mean_interval([10.0, 14.0] * 20)
    assert (many[1] - many[0]) < (few[1] - few[0])


def test_identical_values_zero_width():
    assert mean_interval([5.0, 5.0, 5.0]) == (5.0, 5.0)


def test_interval_needs_values():
    with pytest.raises(InputError):
        mean_interval([])


def test_sample_cv():
    assert sample_cv([10.0, 10.0]) == 0
    assert sample_cv([8.0, 12.0]) == pytest.approx((8**0.5) / 10)


@pytest.mark.parametrize("q, expected", [(0, 1.0), (50, 2.5), (100, 4.0), (25, 1.75)])
def test_percentile(q, expected):
    assert percentile([4.0, 1.0, 3.0, 2.0], q) == pytest.approx(expected)


def test_percentile_single_value():
    assert percentile([7.0], 95) == 7.0


@pytest.mark.parametrize("q", [-1, 101])
def test_percentile_range(q):
    with pytest.raises(InputError):
        percentile([1.0], q)


def test_lane_uncertainty_fields(lane, settings):
    result = run_scenario((lane,), replace(settings, replications=4))
    spread = lane_uncertainty(result)[lane.key]
    costs = [t.total_cost for t in result.results[0].validation_trials]
    assert spread["cost_ci_low"] <= fmean(costs) <= spread["cost_ci_high"]
    assert spread["cost_p5"] <= spread["cost_p50"] <= spread["cost_p95"]
    assert 0 <= spread["fill_rate_ci_low"] <= spread["fill_rate_ci_high"] <= 1


def test_portfolio_interval(lane, settings):
    lanes = (lane, replace(lane, site_id="Other"))
    result = run_scenario(lanes, replace(settings, replications=4))
    low, high = portfolio_interval(result)
    assert low <= summary(result)["total_mean_cost"] <= high


def test_summary_carries_intervals(lane, settings):
    report = summary(run_scenario((lane,), settings))
    row = report["lanes"][0]
    assert {"cost_ci_low", "cost_ci_high", "cost_p95", "cost_cv"} <= set(row)
    assert len(report["total_cost_ci_95"]) == 2
    assert len(report["replication_total_costs"]) == settings.replications
    assert sum(report["replication_total_costs"]) / settings.replications == pytest.approx(
        report["total_mean_cost"]
    )


def test_summary_single_replication_has_no_interval(lane, settings):
    report = summary(run_scenario((lane,), replace(settings, replications=1)))
    assert report["total_cost_ci_95"] is None
    assert "cost_ci_low" not in report["lanes"][0]
    assert report["replications_for_2pct_precision"] is None


def test_report_md_interval_column(tmp_path, lane, settings):
    text = (export_run(run_scenario((lane,), settings), tmp_path) / "report.md").read_text()
    assert "95% CI (USD)" in text
    assert "(95% CI $" in text


def test_replications_needed():
    assert replications_needed([10.0, 10.0, 10.0]) == 3
    noisy = replications_needed([5.0, 15.0, 5.0, 15.0])
    assert noisy > 4
    assert replications_needed([5.0, 15.0], relative_precision=0.9) == 2


def test_replications_needed_precision_range():
    with pytest.raises(InputError):
        replications_needed([1.0, 2.0], relative_precision=0)


def test_difference_interval():
    mean, low, high = difference_interval([10.0, 12.0, 11.0], [12.0, 14.0, 13.5])
    assert mean == pytest.approx(13.1666667 - 11.0, abs=1e-6)
    assert low <= mean <= high


def test_difference_interval_needs_pairs():
    with pytest.raises(InputError, match="same number"):
        difference_interval([1.0, 2.0], [1.0])


def test_replication_costs():
    assert replication_costs({"replication_total_costs": [1, 2]}) == [1.0, 2.0]
    assert replication_costs({}) is None


def test_compare_pairs_same_seed(tmp_path, lane, settings):
    a = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    b = (
        export_run(
            run_scenario((lane,), replace(settings, scenario_id="higher", demand_multiplier=1.2)),
            tmp_path,
        )
        / "summary.json"
    )
    rows = compare_reports([a, b])
    assert rows[0]["cost_difference_ci_95"][0] == pytest.approx(0.0)
    mean, low, high = rows[1]["cost_difference_ci_95"]
    assert mean == pytest.approx(rows[1]["total_mean_cost"] - rows[0]["total_mean_cost"])
    assert low <= mean <= high


def test_compare_does_not_pair_different_seeds(tmp_path, lane, settings):
    a = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    b = export_run(run_scenario((lane,), replace(settings, scenario_id="other", seed=9)), tmp_path)
    rows = compare_reports([a, b / "summary.json"])
    assert rows[0]["cost_difference_ci_95"][0] == 0
    assert rows[1]["cost_difference_ci_95"] is None


def test_bootstrap_interval_reproducible():
    values = [0.99, 0.97, 1.0, 0.98, 0.995]
    first = bootstrap_interval(values, seed=1)
    assert first == bootstrap_interval(values, seed=1)
    assert first[0] <= fmean(values) <= first[1]
    assert 0.97 <= first[0] and first[1] <= 1.0


def test_bootstrap_interval_level():
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    narrow = bootstrap_interval(values, seed=3, level=0.5)
    wide = bootstrap_interval(values, seed=3, level=0.99)
    assert wide[0] <= narrow[0] and narrow[1] <= wide[1]


@pytest.mark.parametrize("values, level", [([], 0.95), ([1.0], 1.0), ([1.0], 0.0)])
def test_bootstrap_interval_validation(values, level):
    with pytest.raises(InputError):
        bootstrap_interval(values, seed=1, level=level)


def test_uncertain_lanes():
    report = {
        "lanes": [
            {"lane": "A:nitrogen", "validation_mean_fill_rate": 0.97, "fill_rate_ci_low": 0.93},
            {"lane": "B:oxygen", "validation_mean_fill_rate": 0.97, "fill_rate_ci_low": 0.96},
            {"lane": "C:argon", "validation_mean_fill_rate": 0.90, "fill_rate_ci_low": 0.85},
            {"lane": "D:argon", "validation_mean_fill_rate": 0.99},
        ]
    }
    assert uncertain_lanes(report, 0.95) == ["A:nitrogen"]


def test_uncertainty_lines():
    from meridian.reporting import _uncertainty_lines

    report = {
        "replications": 4,
        "replications_for_2pct_precision": 12,
        "lanes": [
            {"lane": "A:nitrogen", "validation_mean_fill_rate": 0.97, "fill_rate_ci_low": 0.93}
        ],
    }
    lines = _uncertainty_lines(report, 0.95)
    assert any("A:nitrogen" in line for line in lines)
    assert any("About 12 replications" in line for line in lines)


def test_uncertainty_lines_quiet_when_settled():
    from meridian.reporting import _uncertainty_lines

    report = {
        "replications": 20,
        "replications_for_2pct_precision": 20,
        "lanes": [
            {"lane": "A:nitrogen", "validation_mean_fill_rate": 0.99, "fill_rate_ci_low": 0.98}
        ],
    }
    assert _uncertainty_lines(report, 0.95) == []


def test_lanes_csv_has_interval_columns(tmp_path, lane, settings):
    import csv

    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    with (bundle / "lanes.csv").open(newline="") as stream:
        (row,) = list(csv.DictReader(stream))
    assert (
        float(row["cost_ci_low"])
        <= float(row["validation_mean_cost"])
        <= float(row["cost_ci_high"])
    )
    assert float(row["cost_p5"]) <= float(row["cost_p95"])


def test_percentiles_inside_replication_range(lane, settings):
    result = run_scenario((lane,), replace(settings, replications=5))
    costs = [t.total_cost for t in result.results[0].validation_trials]
    spread = lane_uncertainty(result)[lane.key]
    assert min(costs) <= spread["cost_p5"] <= spread["cost_p95"] <= max(costs)
