"""Choosing and reporting periodic-review policies in scenario runs."""

import csv
import json
from dataclasses import replace

import pytest

from meridian.cli import main
from meridian.inputs import load_settings
from meridian.models import InputError, Settings
from meridian.planning import (
    candidate_levels,
    compare_policies,
    periodic_levels,
    review_period_sweep,
    run_scenario,
)
from meridian.reporting import export_run, summary


@pytest.fixture
def periodic(settings):
    return replace(settings, policy="periodic-review", review_period_days=3)


# Settings


def test_default_policy_is_base_stock():
    settings = Settings()
    assert settings.policy == "base-stock"
    assert settings.review_period_days == 7
    assert settings.pack_size_kg == 0.0
    assert settings.reorder_fractions == (0.6, 0.8, 1.0)


def test_unknown_policy():
    with pytest.raises(InputError, match="policy must be one of"):
        Settings(policy="kanban")


@pytest.mark.parametrize("days", [0, 91, 1.5])
def test_review_period_limits(days):
    with pytest.raises(InputError, match="review_period_days"):
        Settings(review_period_days=days)


def test_negative_pack_size():
    with pytest.raises(InputError, match="pack_size_kg"):
        Settings(pack_size_kg=-1)


@pytest.mark.parametrize("fractions", [(), (0.5, 0.5), (1.2,), (0,), tuple([0.1] * 11)])
def test_invalid_reorder_fractions(fractions):
    with pytest.raises(InputError, match="reorder_fraction"):
        Settings(reorder_fractions=fractions)


def test_reorder_fractions_sorted():
    assert Settings(reorder_fractions=(1.0, 0.5)).reorder_fractions == (0.5, 1.0)


def test_settings_loaded_from_json(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"policy": "periodic-review", "review_period_days": 5, "pack_size_kg": 250}),
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert (settings.policy, settings.review_period_days, settings.pack_size_kg) == (
        "periodic-review",
        5,
        250.0,
    )


# Candidate grid


def test_periodic_levels_pairs(lane, periodic):
    pairs = periodic_levels(lane, periodic)
    assert pairs == tuple(sorted(set(pairs)))
    assert all(reorder <= level for reorder, level in pairs)


def test_periodic_levels_include_s_equal_to_level(lane, periodic):
    pairs = periodic_levels(lane, periodic)
    assert any(reorder == level for reorder, level in pairs)


def test_periodic_levels_cover_review_period(lane, periodic):
    weekly = replace(periodic, review_period_days=7)
    assert max(level for _, level in periodic_levels(lane, weekly)) > max(
        level for _, level in periodic_levels(lane, periodic)
    )


def test_periodic_levels_above_base_stock_grid(lane, periodic):
    base = max(candidate_levels(lane, periodic))
    assert max(level for _, level in periodic_levels(lane, periodic)) >= base


def test_periodic_levels_deterministic_demand(lane, periodic):
    flat = replace(lane, daily_sd_kg=0)
    pairs = periodic_levels(flat, replace(periodic, stock_multipliers=(1.0,)))
    protection = flat.lead_time_days + periodic.review_period_days
    assert max(level for _, level in pairs) == flat.daily_mean_kg * protection


# Scenario runs


def test_periodic_scenario_runs(lane, periodic):
    result = run_scenario((lane,), periodic)
    lane_result = result.results[0]
    assert lane_result.reorder_point_kg is not None
    assert lane_result.reorder_point_kg <= lane_result.chosen_base_stock_kg
    assert len(lane_result.candidates) == len(periodic_levels(lane, periodic))
    assert all(c.reorder_point_kg is not None for c in lane_result.candidates)


def test_periodic_chosen_candidate_is_cheapest_feasible(lane, periodic):
    lane_result = run_scenario((lane,), periodic).results[0]
    feasible = [c for c in lane_result.candidates if c.meets_target]
    if feasible:
        best = min(feasible, key=lambda c: (c.mean_cost, c.base_stock_kg))
        assert lane_result.chosen_base_stock_kg == best.base_stock_kg
        assert lane_result.reorder_point_kg == best.reorder_point_kg


def test_validation_trials_use_review_period(lane, periodic):
    lane_result = run_scenario((lane,), replace(periodic, review_period_days=4)).results[0]
    for trial in lane_result.validation_trials:
        order_days = [p.day for p in trial.periods if p.ordered_kg > 0]
        assert all((day - 1) % 4 == 0 for day in order_days)


def test_periodic_runs_reproducible(lane, periodic):
    assert run_scenario((lane,), periodic) == run_scenario((lane,), periodic)


def test_base_stock_results_unchanged(lane, settings):
    result = run_scenario((lane,), settings)
    assert result.results[0].reorder_point_kg is None
    assert all(c.reorder_point_kg is None for c in result.results[0].candidates)


# Reporting


def test_summary_rows_for_periodic(lane, periodic):
    row = summary(run_scenario((lane,), periodic))["lanes"][0]
    assert row["policy"] == "periodic-review"
    assert row["review_period_days"] == 3
    assert row["reorder_point_kg"] <= row["base_stock_kg"]
    assert row["mean_orders"] >= 0


def test_summary_rows_for_base_stock(lane, settings):
    row = summary(run_scenario((lane,), settings))["lanes"][0]
    assert "policy" not in row
    assert "reorder_point_kg" not in row


def test_periodic_bundle(tmp_path, lane, periodic):
    bundle = export_run(run_scenario((lane,), periodic), tmp_path)
    with (bundle / "lanes.csv").open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["policy"] == "periodic-review"
    report = (bundle / "report.md").read_text(encoding="utf-8")
    assert "Policy: periodic review every 3 days" in report
    assert "s=" in report and "S=" in report


def test_base_stock_report_names_policy(tmp_path, lane, settings):
    bundle = export_run(run_scenario((lane,), settings), tmp_path)
    assert "Policy: daily base-stock review." in (bundle / "report.md").read_text()


def test_report_mentions_pack_size(periodic):
    from meridian.reporting import _policy_line

    line = _policy_line(replace(periodic, pack_size_kg=500))
    assert line == (
        "Policy: periodic review every 3 days "
        "(order up to S when position is at or below s, pack size 500 kg)."
    )


# Command line


def _config(tmp_path, **values):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"horizon_days": 21, "replications": 2, **values}))
    return str(path)


def test_cli_periodic(tmp_path, capsys):
    args = [
        "periodic",
        "--data",
        "data/synthetic_sites.csv",
        "--config",
        _config(tmp_path),
        "--lane",
        "Harbor:nitrogen",
        "--reorder-point",
        "3000",
        "--order-up-to",
        "6000",
    ]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["lane"] == "Harbor:nitrogen"
    assert result["review_period_days"] == 7
    assert result["replications"] == 2
    assert 0 <= result["mean_fill_rate"] <= 1
    assert result["mean_orders"] > 0


def test_cli_periodic_review_override(tmp_path, capsys):
    args = [
        "periodic",
        "--data",
        "data/synthetic_sites.csv",
        "--config",
        _config(tmp_path),
        "--lane",
        "Summit:argon",
        "--reorder-point",
        "500",
        "--order-up-to",
        "1200",
        "--review-days",
        "3",
    ]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["review_period_days"] == 3


def test_cli_periodic_unknown_lane(tmp_path, capsys):
    args = ["periodic", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    args += ["--lane", "Nowhere:nitrogen", "--reorder-point", "1", "--order-up-to", "2"]
    assert main(args) == 2
    assert "No product-location 'Nowhere:nitrogen'" in capsys.readouterr().err


def test_cli_periodic_invalid_levels(tmp_path, capsys):
    args = ["periodic", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    args += ["--lane", "Harbor:nitrogen", "--reorder-point", "9", "--order-up-to", "2"]
    assert main(args) == 2
    assert "must not exceed" in capsys.readouterr().err


def test_cli_run_periodic(tmp_path, capsys):
    config = _config(tmp_path, policy="periodic-review", review_period_days=5)
    output = str(tmp_path / "results")
    args = ["run", "--data", "data/synthetic_sites.csv", "--config", config, "--output", output]
    assert main(args) == 0
    assert "Results saved to" in capsys.readouterr().out


# Policy comparison and review-period sweeps


def test_compare_policies(lane, settings):
    lanes = (lane, replace(lane, site_id="North", daily_sd_kg=3))
    rows = compare_policies(lanes, replace(settings, review_period_days=4))
    assert [row["lane"] for row in rows] == ["Example:nitrogen", "North:nitrogen"]
    for row in rows:
        assert row["review_period_days"] == 4
        assert row["reorder_point_kg"] <= row["order_up_to_kg"]
        assert row["cost_difference"] == pytest.approx(
            row["periodic_cost"] - row["base_stock_cost"]
        )


def test_compare_policies_matches_separate_runs(lane, settings):
    row = compare_policies((lane,), settings)[0]
    base = run_scenario((lane,), settings).results[0]
    assert row["base_stock_kg"] == base.chosen_base_stock_kg


def test_compare_policies_ignores_configured_policy(lane, settings):
    configured = replace(settings, policy="periodic-review")
    assert compare_policies((lane,), configured) == compare_policies((lane,), settings)


def test_review_period_sweep(lane, settings):
    rows = review_period_sweep(lane, settings, (7, 1, 3, 7))
    assert [row["review_period_days"] for row in rows] == [1, 3, 7]
    assert all(row["reorder_point_kg"] <= row["order_up_to_kg"] for row in rows)
    assert all(0 <= row["mean_fill_rate"] <= 1 for row in rows)


def test_review_period_sweep_longer_periods_need_more_stock(lane, settings):
    rows = review_period_sweep(lane, settings, (1, 14))
    assert rows[1]["order_up_to_kg"] > rows[0]["order_up_to_kg"]


@pytest.mark.parametrize("periods", [(), tuple(range(1, 22))])
def test_review_period_sweep_limits(lane, settings, periods):
    with pytest.raises(InputError, match="1-20 review periods"):
        review_period_sweep(lane, settings, periods)


def test_review_period_sweep_invalid_period(lane, settings):
    with pytest.raises(InputError, match="review_period_days"):
        review_period_sweep(lane, settings, (0,))


def test_cli_compare_policies(tmp_path, capsys):
    args = ["compare-policies", "--data", "data/synthetic_sites.csv", "--config"]
    assert main([*args, _config(tmp_path)]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 6
    assert {"base_stock_cost", "periodic_cost", "cost_difference"} <= set(rows[0])


def test_cli_review_sweep(tmp_path, capsys):
    args = ["review-sweep", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    assert main([*args, "--lane", "Summit:argon", "--periods", "2", "5"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["review_period_days"] for row in rows] == [2, 5]


def test_cli_review_sweep_unknown_lane(tmp_path, capsys):
    args = ["review-sweep", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    assert main([*args, "--lane", "Nowhere:argon"]) == 2
    assert "No product-location" in capsys.readouterr().err


def test_cli_periodic_includes_diagnostics(tmp_path, capsys):
    args = ["periodic", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    args += ["--lane", "Harbor:nitrogen", "--reorder-point", "3000", "--order-up-to", "6000"]
    assert main(args) == 0
    diagnostics = json.loads(capsys.readouterr().out)["first_trial"]
    assert diagnostics["reviews"] == 3
    assert diagnostics["orders"] + diagnostics["skipped_reviews"] == 3


def test_comparison_table(lane, settings):
    from meridian.policies import comparison_table

    rows = compare_policies((lane,), settings)
    lines = comparison_table(rows).splitlines()
    assert lines[0].startswith("| Product-location | Base stock (kg)")
    assert len(lines) == 3
    assert lines[2].startswith("| Example:nitrogen |")


def test_sweep_table(lane, settings):
    from meridian.policies import sweep_table

    lines = sweep_table(review_period_sweep(lane, settings, (1, 7))).splitlines()
    assert lines[0].startswith("| Review period (days) |")
    assert [line.split("|")[1].strip() for line in lines[2:]] == ["1", "7"]


def test_cli_compare_policies_table(tmp_path, capsys):
    args = ["compare-policies", "--data", "data/synthetic_sites.csv", "--config"]
    assert main([*args, _config(tmp_path), "--format", "table"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 8
    assert lines[1].startswith("|---|")


def test_cli_review_sweep_table(tmp_path, capsys):
    args = ["review-sweep", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    assert main([*args, "--lane", "Summit:argon", "--periods", "3", "--format", "table"]) == 0
    assert capsys.readouterr().out.splitlines()[2].startswith("| 3 |")


def test_lane_result_reorder_point_defaults_to_none(lane, settings):
    from meridian.models import LaneResult

    result = LaneResult("A:nitrogen", 10.0, True, (), ())
    assert result.reorder_point_kg is None


def test_candidate_reorder_point_defaults_to_none():
    from meridian.models import Candidate

    assert Candidate(10.0, 5.0, 0.9, False).reorder_point_kg is None
