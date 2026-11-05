"""Variable supplier lead times."""

from dataclasses import replace
from math import exp
from pathlib import Path

import pytest

from meridian.demand import demand_traces
from meridian.engine import simulate_lane, simulate_lane_variable
from meridian.inputs import load_settings
from meridian.leadtime import (
    describe,
    estimate_cv,
    lead_time_quantile,
    lead_time_sd,
    lead_time_traces,
    load_delivery_history,
    lognormal_params,
    realised_lead_times,
    sample_lead_times,
)
from meridian.models import InputError, Settings, Trial
from meridian.planning import candidate_levels, lead_time_sensitivity, run_scenario
from meridian.reporting import export_run, summary

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def variable(settings):
    return replace(settings, lead_time_cv=0.3)


@pytest.mark.parametrize("mean, cv", [(2, 0.2), (5, 0.5), (1, 1.5)])
def test_lognormal_params_match_mean_and_cv(mean, cv):
    mu, sigma = lognormal_params(mean, cv)
    assert exp(mu + sigma**2 / 2) == pytest.approx(mean)
    assert (exp(sigma**2) - 1) ** 0.5 == pytest.approx(cv)


def test_lognormal_needs_positive_mean():
    with pytest.raises(InputError, match="positive mean"):
        lognormal_params(0, 0.5)


def test_quantiles_increase():
    assert lead_time_quantile(3, 0.4, 0.5) < lead_time_quantile(3, 0.4, 0.95)
    assert lead_time_quantile(0, 0.4, 0.95) == 0


def test_lead_time_sd(lane, settings, variable):
    assert lead_time_sd(lane, settings) == 0
    assert lead_time_sd(replace(lane, lead_time_days=4), variable) == pytest.approx(1.2)


def test_samples_reproducible(lane, variable):
    first = sample_lead_times(lane, variable, "training", 0)
    assert first == sample_lead_times(lane, variable, "training", 0)
    assert len(first) == variable.horizon_days
    assert all(isinstance(value, int) for value in first)


def test_samples_differ_by_phase_and_replication(variable):
    from meridian.models import Lane

    slow = Lane("Example", "nitrogen", 10, 2, 6, 20, 0.1, 2, 5, 0.5)
    longer = replace(variable, horizon_days=60)
    training = sample_lead_times(slow, longer, "training", 0)
    assert training != sample_lead_times(slow, longer, "validation", 0)
    assert training != sample_lead_times(slow, longer, "training", 1)


def test_samples_change_with_seed(variable):
    from meridian.models import Lane

    slow = Lane("Example", "nitrogen", 10, 2, 6, 20, 0.1, 2, 5, 0.5)
    longer = replace(variable, horizon_days=60)
    assert sample_lead_times(slow, longer, "training", 0) != sample_lead_times(
        slow, replace(longer, seed=999), "training", 0
    )


def test_zero_lead_time_stays_same_day(lane, variable):
    instant = replace(lane, lead_time_days=0)
    assert set(sample_lead_times(instant, variable, "training", 0)) == {0}


def test_traces_one_per_replication(lane, variable):
    traces = lead_time_traces(lane, variable, "validation")
    assert len(traces) == variable.replications


def test_sampling_requires_setting(lane, settings):
    with pytest.raises(InputError, match="lead_time_cv"):
        sample_lead_times(lane, settings, "training", 0)


def test_sampling_rejects_unknown_phase(lane, variable):
    with pytest.raises(InputError, match="phase"):
        sample_lead_times(lane, variable, "testing", 0)


@pytest.mark.parametrize("lead_time_days", [0, 1, 3])
@pytest.mark.parametrize("base_stock_kg", [5.0, 25.0, 60.0])
def test_constant_lead_times_match_stockpyl(lane, lead_time_days, base_stock_kg):
    lane = replace(lane, lead_time_days=lead_time_days)
    settings = Settings(horizon_days=30, replications=2)
    for trace in demand_traces(lane, settings, "training"):
        fixed = simulate_lane(lane, base_stock_kg, trace)
        variable = simulate_lane_variable(
            lane, base_stock_kg, trace, (lead_time_days,) * len(trace), 0.3
        )
        for a, b in zip(fixed.periods, variable.periods):
            assert a.inventory_kg == pytest.approx(b.inventory_kg)
            assert a.backlog_kg == pytest.approx(b.backlog_kg)
            assert a.ordered_kg == pytest.approx(b.ordered_kg)
            assert a.served_immediately_kg == pytest.approx(b.served_immediately_kg)
            assert a.total_cost == pytest.approx(b.total_cost)


def test_later_arrivals_reduce_service(lane):
    demands = (10.0,) * 20
    on_time = simulate_lane_variable(lane, 25.0, demands, (1,) * 20, 0.3)
    late = simulate_lane_variable(lane, 25.0, demands, (3,) * 20, 0.3)
    assert late.fill_rate < on_time.fill_rate


def test_orders_can_overtake(lane):
    demands = (10.0,) * 6
    trial = simulate_lane_variable(lane, 30.0, demands, (3, 1, 1, 1, 1, 1), 0.5)
    assert sum(p.ordered_kg for p in trial.periods) > 0
    assert trial.periods[-1].inventory_kg >= 0


def test_lead_time_input_length(lane):
    with pytest.raises(InputError, match="one value per simulated day"):
        simulate_lane_variable(lane, 20.0, (10.0, 10.0), (1,), 0.3)


def test_extreme_lead_times_capped(lane):
    demands = (10.0,) * 10
    capped = simulate_lane_variable(lane, 20.0, demands, (500,) * 10, 0.3)
    near_cap = simulate_lane_variable(lane, 20.0, demands, (3,) * 10, 0.3)
    assert capped.periods[-1].inventory_kg + capped.periods[-1].backlog_kg >= 0
    assert capped.fill_rate <= near_cap.fill_rate


def test_variability_raises_candidate_grid(lane, settings):
    fixed = candidate_levels(lane, settings)
    variable = candidate_levels(lane, replace(settings, lead_time_cv=1.0))
    assert max(variable) >= max(fixed)
    assert sum(variable) > sum(fixed)


def test_run_with_variable_lead_times(lane, variable):
    result = run_scenario((lane,), variable)
    assert len(result.results[0].validation_trials) == variable.replications
    assert result == run_scenario((lane,), variable)


def test_fixed_runs_unchanged(lane, settings):
    assert settings.lead_time_cv is None
    first = run_scenario((lane,), settings)
    assert first.results[0].candidates == run_scenario((lane,), settings).results[0].candidates


@pytest.mark.parametrize("value", [-0.1, 2.5, "high", True])
def test_invalid_cv(value):
    with pytest.raises(InputError):
        Settings(lead_time_cv=value)


def test_setting_loads_from_json(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"scenario_id": "variable", "lead_time_cv": 0.4}')
    assert load_settings(path).lead_time_cv == 0.4


def test_setting_defaults_to_fixed(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"scenario_id": "fixed"}')
    assert load_settings(path).lead_time_cv is None


def test_describe(lane, settings, variable):
    fixed = describe(lane, settings)
    assert fixed["lead_time_sd_days"] == 0
    assert fixed["p95_lead_time_days"] == lane.lead_time_days
    varied = describe(replace(lane, lead_time_days=4), variable)
    assert varied["lead_time_sd_days"] == pytest.approx(1.2)
    assert varied["p95_lead_time_days"] > 4


def test_orders_record_lead_times(lane):
    demands = (10.0,) * 8
    trial = simulate_lane_variable(lane, 25.0, demands, (2,) * 8, 0.3)
    placed = [p.day for p in trial.periods if p.ordered_kg]
    assert [day for day, _ in trial.order_lead_times] == placed
    assert {lead for _, lead in trial.order_lead_times} == {2}


def test_fixed_simulation_records_no_lead_times(lane):
    assert simulate_lane(lane, 25.0, (10.0,) * 5).order_lead_times == ()


def _trial(order_lead_times):
    return Trial("Example:nitrogen", 20.0, (), tuple(order_lead_times))


def test_realised_statistics():
    trials = (_trial([(1, 1), (2, 3)]), _trial([(5, 2), (9, 4)]))
    stats = realised_lead_times(trials, planned_days=2, horizon_days=10)
    assert stats["orders"] == 4
    assert stats["mean_realised_lead_time_days"] == pytest.approx(2.5)
    assert stats["max_realised_lead_time_days"] == 4
    assert stats["late_order_share"] == pytest.approx(0.5)
    assert stats["orders_after_horizon"] == 1


def test_realised_statistics_without_orders():
    stats = realised_lead_times((_trial([]),), planned_days=2, horizon_days=10)
    assert stats["orders"] == 0
    assert stats["mean_realised_lead_time_days"] is None
    assert stats["late_order_share"] is None


def test_summary_columns_only_when_variable(lane, settings, variable):
    fixed_row = summary(run_scenario((lane,), settings))["lanes"][0]
    assert "mean_realised_lead_time_days" not in fixed_row
    varied_row = summary(run_scenario((lane,), variable))["lanes"][0]
    assert varied_row["orders"] > 0
    assert varied_row["mean_realised_lead_time_days"] >= 0
    assert 0 <= varied_row["late_order_share"] <= 1


def test_report_section(tmp_path, lane, variable):
    bundle = export_run(run_scenario((lane,), variable), tmp_path)
    text = (bundle / "report.md").read_text()
    assert "## Lead times (variable, CV 0.3)" in text
    assert "| Example:nitrogen |" in text.split("## Lead times")[1]


def test_fixed_report_has_no_section(tmp_path, lane, settings):
    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    assert "## Lead times" not in (bundle / "report.md").read_text()


def test_variable_bundle_can_be_compared(tmp_path, lane, variable):
    from meridian.reporting import compare_reports

    a = export_run(run_scenario((lane,), variable), tmp_path) / "summary.json"
    b = export_run(run_scenario((lane,), replace(variable, scenario_id="other")), tmp_path)
    rows = compare_reports([a, b / "summary.json"])
    assert {row["scenario_id"] for row in rows} == {variable.scenario_id, "other"}


def test_sensitivity_rows(lane, settings):
    rows = lead_time_sensitivity((lane,), settings, (None, 0.5))
    assert [row["lead_time_cv"] for row in rows] == [None, 0.5]
    for row in rows:
        assert row["mean_total_cost"] > 0
        assert 0 <= row["portfolio_fill_rate"] <= 1
        assert row["total_base_stock_kg"] > 0


def test_sensitivity_fixed_matches_scenario(lane, settings):
    (row,) = lead_time_sensitivity((lane,), settings, (None,))
    report = summary(run_scenario((lane,), settings))
    assert row["mean_total_cost"] == pytest.approx(report["total_mean_cost"])
    assert row["portfolio_fill_rate"] == pytest.approx(report["portfolio_fill_rate"])


@pytest.mark.parametrize("cvs", [(), tuple(0.1 * i for i in range(11))])
def test_sensitivity_needs_one_to_ten(lane, settings, cvs):
    with pytest.raises(InputError, match="1-10"):
        lead_time_sensitivity((lane,), settings, cvs)


def _history(tmp_path, rows, header="site_id,product,order_date,delivery_date"):
    path = tmp_path / "deliveries.csv"
    path.write_text("\n".join([header, *rows]) + "\n")
    return path


def test_delivery_history_lead_times(tmp_path):
    path = _history(
        tmp_path,
        [
            "Harbor,nitrogen,2026-01-01,2026-01-03",
            "Harbor,nitrogen,2026-01-05,2026-01-09",
            "Meadow,oxygen,2026-01-02,2026-01-02",
        ],
    )
    assert load_delivery_history(path) == {"Harbor:nitrogen": [2, 4], "Meadow:oxygen": [0]}


def test_delivery_history_ignores_extra_columns(tmp_path):
    path = _history(
        tmp_path,
        ["Harbor,nitrogen,2026-01-01,2026-01-03,TRK-1"],
        header="site_id,product,order_date,delivery_date,truck",
    )
    assert load_delivery_history(path) == {"Harbor:nitrogen": [2]}


@pytest.mark.parametrize(
    "row, message",
    [
        ("Harbor,helium,2026-01-01,2026-01-03", "unknown product"),
        ("Harbor,nitrogen,01/02/2026,2026-01-03", "YYYY-MM-DD"),
        ("Harbor,nitrogen,2026-01-05,2026-01-03", "before it was ordered"),
        ("Harbor,nitrogen,2026-01-05", "missing values"),
    ],
)
def test_delivery_history_rejects_bad_rows(tmp_path, row, message):
    with pytest.raises(InputError, match=message):
        load_delivery_history(_history(tmp_path, [row]))


def test_delivery_history_requires_columns(tmp_path):
    with pytest.raises(InputError, match="missing columns: delivery_date"):
        load_delivery_history(_history(tmp_path, [], header="site_id,product,order_date"))


def test_delivery_history_needs_rows(tmp_path):
    with pytest.raises(InputError, match="no deliveries"):
        load_delivery_history(_history(tmp_path, []))


def test_estimate_cv_per_lane_and_pooled():
    history = {"A:nitrogen": [2, 2, 2, 2, 2], "B:oxygen": [1, 3, 1, 3, 1, 3, 1, 3, 1, 3]}
    estimate = estimate_cv(history)
    assert estimate["lanes"]["A:nitrogen"]["lead_time_cv"] == 0
    b = estimate["lanes"]["B:oxygen"]
    assert b["mean_lead_time_days"] == 2
    assert b["lead_time_cv"] == pytest.approx(1.0541 / 2, abs=1e-4)
    assert estimate["suggested_lead_time_cv"] == pytest.approx(
        round(b["lead_time_cv"] * 10 / 15, 2)
    )


def test_estimate_cv_skips_sparse_lanes():
    estimate = estimate_cv({"A:nitrogen": [2, 3], "B:oxygen": [2, 3, 2, 3, 2]})
    assert set(estimate["lanes"]) == {"B:oxygen"}


def test_estimate_cv_needs_enough_data():
    with pytest.raises(InputError, match="5 or more deliveries"):
        estimate_cv({"A:nitrogen": [2, 3]})


def test_estimate_cv_capped():
    estimate = estimate_cv({"A:nitrogen": [0, 0, 0, 0, 30]}, min_deliveries=5)
    assert estimate["suggested_lead_time_cv"] == 2.0


def test_model_note_only_when_variable(lane, settings, variable):
    fixed_notes = summary(run_scenario((lane,), settings))["model_notes"]
    varied_notes = summary(run_scenario((lane,), variable))["model_notes"]
    assert not any("Variable lead times" in note for note in fixed_notes)
    assert any("CV 0.3" in note for note in varied_notes)
    assert len(varied_notes) == len(fixed_notes) + 1


def test_compare_lists_lead_time_cv(tmp_path, lane, settings, variable):
    from meridian.reporting import compare_reports

    fixed = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    varied = (
        export_run(run_scenario((lane,), replace(variable, scenario_id="varied")), tmp_path)
        / "summary.json"
    )
    rows = {row["scenario_id"]: row for row in compare_reports([fixed, varied])}
    assert rows[settings.scenario_id]["lead_time_cv"] is None
    assert rows["varied"]["lead_time_cv"] == 0.3


def test_demand_unchanged_by_lead_time_setting(lane, settings, variable):
    assert demand_traces(lane, settings, "training") == demand_traces(lane, variable, "training")
