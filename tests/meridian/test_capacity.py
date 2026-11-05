"""Site storage capacity in inputs and the simulation."""

import json
from dataclasses import replace

import pytest

from meridian.cli import main
from meridian.engine import capacity_summary, capacity_utilisation, days_at_capacity, simulate_lane
from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError, Lane, Settings
from meridian.planning import capacity_report, run_scenario

HEADER = (
    "site_id,product,daily_mean_kg,daily_sd_kg,lead_time_days,initial_inventory_kg,"
    "holding_cost_per_kg_day,backlog_cost_per_kg_day,delivery_cost_per_order,purchase_cost_per_kg"
)
ROW = "Harbor,nitrogen,800,160,2,2800,0.012,1.8,90,0.18"
DEMANDS = (12.0, 8.0, 15.0, 9.0, 11.0, 10.0, 7.0, 14.0, 30.0, 0.0, 6.0, 13.0)


@pytest.fixture
def roomy(lane):
    return replace(lane, storage_capacity_kg=1_000_000)


def _write(tmp_path, text):
    path = tmp_path / "lanes.csv"
    path.write_text(text, encoding="utf-8")
    return path


# Inputs


def test_capacity_column_optional(tmp_path):
    assert load_lanes(_write(tmp_path, f"{HEADER}\n{ROW}\n"))[0].storage_capacity_kg is None


def test_capacity_loaded(tmp_path):
    path = _write(tmp_path, f"{HEADER},storage_capacity_kg\n{ROW},12000\n")
    assert load_lanes(path)[0].storage_capacity_kg == 12000.0


def test_blank_capacity_is_not_recorded(tmp_path):
    path = _write(tmp_path, f"{HEADER},storage_capacity_kg\n{ROW},\n")
    assert load_lanes(path)[0].storage_capacity_kg is None


def test_blank_required_value_still_rejected(tmp_path):
    path = _write(
        tmp_path,
        f"{HEADER},storage_capacity_kg\nHarbor,nitrogen,,160,2,2800,0.012,1.8,90,0.18,9000\n",
    )
    with pytest.raises(InputError, match="missing or extra values"):
        load_lanes(path)


def test_unknown_column_still_rejected(tmp_path):
    path = _write(tmp_path, f"{HEADER},tank_size\n{ROW},9000\n")
    with pytest.raises(InputError, match="extra=\\['tank_size'\\]"):
        load_lanes(path)


@pytest.mark.parametrize("value", ["0", "-5", "abc", "inf"])
def test_invalid_capacity(tmp_path, value):
    path = _write(tmp_path, f"{HEADER},storage_capacity_kg\n{ROW},{value}\n")
    with pytest.raises(InputError):
        load_lanes(path)


def test_initial_inventory_must_fit(lane):
    with pytest.raises(InputError, match="must not exceed storage_capacity_kg"):
        replace(lane, initial_inventory_kg=500, storage_capacity_kg=400)


def test_initial_inventory_may_fill_site(lane):
    assert replace(lane, initial_inventory_kg=400, storage_capacity_kg=400).storage_capacity_kg


def test_settings_flag_default_off():
    assert Settings().enforce_capacity is False


def test_settings_flag_must_be_boolean():
    with pytest.raises(InputError, match="enforce_capacity"):
        Settings(enforce_capacity="yes")


def test_settings_flag_loaded(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"enforce_capacity": True}), encoding="utf-8")
    assert load_settings(path).enforce_capacity is True


# Simulation


@pytest.mark.parametrize("lead_time", [0, 1, 3])
@pytest.mark.parametrize("base_stock", [5.0, 25.0, 60.0])
def test_unlimited_capacity_matches_simulator(roomy, lead_time, base_stock):
    lane = replace(roomy, lead_time_days=lead_time)
    expected = simulate_lane(lane, base_stock, DEMANDS)
    actual = simulate_lane(lane, base_stock, DEMANDS, enforce_capacity=True)
    assert actual.total_cost == pytest.approx(expected.total_cost)
    assert actual.fill_rate == pytest.approx(expected.fill_rate)
    for ours, theirs in zip(actual.periods, expected.periods, strict=True):
        assert ours.inventory_kg == pytest.approx(theirs.inventory_kg)
        assert ours.backlog_kg == pytest.approx(theirs.backlog_kg)
        assert ours.ordered_kg == pytest.approx(theirs.ordered_kg)


def test_capacity_ignored_unless_enforced(lane):
    tight = replace(lane, initial_inventory_kg=5, storage_capacity_kg=5)
    loose = replace(lane, initial_inventory_kg=5, storage_capacity_kg=1_000_000)
    assert simulate_lane(tight, 40, DEMANDS) == simulate_lane(loose, 40, DEMANDS)


def test_capacity_runs_report_every_day(roomy):
    trial = simulate_lane(roomy, 25, DEMANDS, enforce_capacity=True)
    assert [period.day for period in trial.periods] == list(range(1, len(DEMANDS) + 1))
    assert trial.lane_key == roomy.key
    assert trial.base_stock_kg == 25


def test_capacity_costs_add_up(roomy):
    trial = simulate_lane(roomy, 25, DEMANDS, enforce_capacity=True)
    for period in trial.periods:
        assert period.holding_cost == pytest.approx(
            period.inventory_kg * roomy.holding_cost_per_kg_day
        )
        assert period.backlog_cost == pytest.approx(
            period.backlog_kg * roomy.backlog_cost_per_kg_day
        )
        assert period.purchase_cost == pytest.approx(period.ordered_kg * roomy.purchase_cost_per_kg)


def test_utilisation(roomy):
    lane = replace(roomy, storage_capacity_kg=50)
    trial = simulate_lane(lane, 25, DEMANDS, enforce_capacity=True)
    peak = max(period.inventory_kg for period in trial.periods)
    assert capacity_utilisation(lane, trial) == pytest.approx(peak / 50)


def test_scenario_with_capacity(lane, settings):
    lanes = (
        replace(lane, storage_capacity_kg=200),
        replace(lane, site_id="North", storage_capacity_kg=150),
    )
    capped = run_scenario(lanes, replace(settings, enforce_capacity=True))
    assert len(capped.results) == 2
    for lane_result, site in zip(capped.results, sorted(lanes, key=lambda x: x.key), strict=True):
        for trial in lane_result.validation_trials:
            assert max(p.inventory_kg for p in trial.periods) <= site.storage_capacity_kg


def test_scenario_without_flag_unchanged(lane, settings):
    capped_lane = replace(lane, storage_capacity_kg=1_000_000)
    plain = run_scenario((lane,), settings)
    flagged = run_scenario((capped_lane,), replace(settings, enforce_capacity=True))
    assert plain.results[0].chosen_base_stock_kg == flagged.results[0].chosen_base_stock_kg
    assert [t.total_cost for t in plain.results[0].validation_trials] == pytest.approx(
        [t.total_cost for t in flagged.results[0].validation_trials]
    )


def test_cli_run_with_capacity(tmp_path, capsys):
    lanes = tmp_path / "lanes.csv"
    lanes.write_text(f"{HEADER},storage_capacity_kg\n{ROW},20000\n", encoding="utf-8")
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps({"horizon_days": 10, "replications": 2, "enforce_capacity": True}),
        encoding="utf-8",
    )
    output = tmp_path / "results"
    assert (
        main(["run", "--data", str(lanes), "--config", str(config), "--output", str(output)]) == 0
    )
    assert "Results saved to" in capsys.readouterr().out


def test_lane_equality_includes_capacity():
    first = Lane("Example", "nitrogen", 10, 2, 1, 20, 0.1, 2, 5, 0.5)
    assert first != replace(first, storage_capacity_kg=100)


# Reporting helpers


def test_days_at_capacity_without_capacity(lane):
    trial = simulate_lane(lane, 25, DEMANDS)
    assert days_at_capacity(lane, trial) == 0


def test_days_at_capacity_counts_full_days(roomy):
    trial = simulate_lane(roomy, 25, DEMANDS)
    peak = max(period.inventory_kg for period in trial.periods)
    at_peak = sum(period.inventory_kg == peak for period in trial.periods)
    assert days_at_capacity(replace(roomy, storage_capacity_kg=peak), trial) == at_peak


def test_capacity_summary(roomy):
    lane = replace(roomy, storage_capacity_kg=100)
    trials = (
        simulate_lane(lane, 25, DEMANDS, enforce_capacity=True),
        simulate_lane(lane, 40, DEMANDS, enforce_capacity=True),
    )
    summary = capacity_summary(lane, trials)
    assert summary["trials"] == 2
    assert summary["storage_capacity_kg"] == 100
    assert summary["max_peak_utilisation"] >= summary["mean_peak_utilisation"]
    assert summary["mean_days_at_capacity"] == 0


def test_capacity_summary_needs_trials(roomy):
    with pytest.raises(InputError):
        capacity_summary(roomy, ())


def test_capacity_report(lane, settings):
    lanes = (
        replace(lane, storage_capacity_kg=500),
        replace(lane, site_id="North"),
    )
    result = run_scenario(lanes, replace(settings, enforce_capacity=False))
    rows = capacity_report(result)
    assert [row["lane"] for row in rows] == ["Example:nitrogen"]
    row = rows[0]
    assert row["capacity_enforced"] is False
    assert row["base_stock_above_capacity"] is False
    assert row["base_stock_kg"] == result.results[0].chosen_base_stock_kg
    assert 0 < row["mean_peak_utilisation"] < 1


def test_capacity_report_flags_large_base_stock(lane, settings):
    small = replace(lane, initial_inventory_kg=5, storage_capacity_kg=6)
    rows = capacity_report(run_scenario((small,), settings))
    assert rows[0]["base_stock_above_capacity"] is True
    assert rows[0]["max_peak_utilisation"] > 1


def test_capacity_report_empty_without_capacities(lane, settings):
    assert capacity_report(run_scenario((lane,), settings)) == []


def test_capacity_column_any_position(tmp_path):
    path = _write(tmp_path, f"storage_capacity_kg,{HEADER}\n15000,{ROW}\n")
    assert load_lanes(path)[0].storage_capacity_kg == 15000.0


def test_capacity_mixed_rows(tmp_path):
    second = ROW.replace("Harbor", "Ridge")
    path = _write(tmp_path, f"{HEADER},storage_capacity_kg\n{ROW},9000\n{second},\n")
    capacities = {lane.site_id: lane.storage_capacity_kg for lane in load_lanes(path)}
    assert capacities == {"Harbor": 9000.0, "Ridge": None}


def test_capacity_whitespace_is_blank(tmp_path):
    path = _write(tmp_path, f"{HEADER},storage_capacity_kg\n{ROW},   \n")
    assert load_lanes(path)[0].storage_capacity_kg is None


def test_capacity_boolean_rejected(lane):
    with pytest.raises(InputError):
        replace(lane, storage_capacity_kg=True)


def test_capacity_runs_reproducible(lane, settings):
    capped = (replace(lane, storage_capacity_kg=300),)
    flagged = replace(settings, enforce_capacity=True)
    first = run_scenario(capped, flagged)
    second = run_scenario(capped, flagged)
    assert first.results == second.results


def test_capacity_trial_costs_match_total(roomy):
    trial = simulate_lane(roomy, 25, DEMANDS, enforce_capacity=True)
    assert trial.total_cost == pytest.approx(sum(period.total_cost for period in trial.periods))


def test_capacity_zero_lead_time_serves_same_day(roomy):
    lane = replace(roomy, lead_time_days=0, initial_inventory_kg=0)
    trial = simulate_lane(lane, 30, DEMANDS, enforce_capacity=True)
    assert trial.fill_rate == pytest.approx(1.0)


@pytest.mark.parametrize("capacity", [100.0, 250.0, 1_000.0])
def test_roomy_capacity_never_binds(roomy, capacity):
    lane = replace(roomy, storage_capacity_kg=capacity)
    expected = simulate_lane(lane, 25, DEMANDS)
    actual = simulate_lane(lane, 25, DEMANDS, enforce_capacity=True)
    assert [p.inventory_kg for p in actual.periods] == pytest.approx(
        [p.inventory_kg for p in expected.periods]
    )


def test_capacity_with_backlog_matches_simulator(roomy):
    lane = replace(roomy, initial_inventory_kg=0, lead_time_days=2)
    expected = simulate_lane(lane, 10, DEMANDS)
    actual = simulate_lane(lane, 10, DEMANDS, enforce_capacity=True)
    assert any(period.backlog_kg > 0 for period in actual.periods)
    assert [p.backlog_kg for p in actual.periods] == pytest.approx(
        [p.backlog_kg for p in expected.periods]
    )
    assert [p.served_immediately_kg for p in actual.periods] == pytest.approx(
        [p.served_immediately_kg for p in expected.periods]
    )


def test_settings_example_configs_unchanged():
    for name in ("config/baseline.json", "config/quickstart.json"):
        assert load_settings(name).enforce_capacity is False
