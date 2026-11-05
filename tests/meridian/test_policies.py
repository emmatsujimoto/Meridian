"""Safety-stock policy selector."""

from dataclasses import replace
from math import ceil

import pytest

from meridian.models import InputError, Settings
from meridian.planning import candidate_levels, run_scenario
from meridian.policies import (
    POLICIES,
    compare_policies,
    fixed_safety_stock,
    lead_time_demand_kg,
    policy_summary,
    policy_warnings,
    protection_days,
    safety_stock,
    statistical_safety_stock,
)


def test_default_policy_is_statistical():
    assert Settings().safety_stock_policy == "statistical"
    assert POLICIES == ("statistical", "fixed", "percentage")


def test_protection_days(lane):
    assert protection_days(lane) == lane.lead_time_days + 1


def test_lead_time_demand(lane, settings):
    scaled = replace(settings, demand_multiplier=1.5)
    assert lead_time_demand_kg(lane, scaled) == pytest.approx(lane.daily_mean_kg * 1.5 * 2)


def test_statistical_grid_unchanged(lane, settings):
    """The default policy keeps the original newsvendor-centred grid."""
    explicit = replace(settings, safety_stock_policy="statistical")
    assert candidate_levels(lane, explicit) == candidate_levels(lane, settings)


def test_statistical_matches_grid_centre(lane, settings):
    single = replace(settings, stock_multipliers=(1.0,))
    (level,) = candidate_levels(lane, single)
    centre = lead_time_demand_kg(lane, single) + statistical_safety_stock(lane, single)
    assert level == ceil(centre)


def test_statistical_zero_variability(lane, settings):
    assert statistical_safety_stock(replace(lane, daily_sd_kg=0), settings) == 0


def test_fixed_policy(lane, settings):
    fixed = replace(
        settings, safety_stock_policy="fixed", safety_stock_kg=15, stock_multipliers=(1.0,)
    )
    assert fixed_safety_stock(lane, fixed) == 15
    assert safety_stock(lane, fixed) == 15
    assert candidate_levels(lane, fixed) == (float(ceil(lead_time_demand_kg(lane, fixed) + 15)),)


def test_fixed_policy_zero_means_mean_demand(lane, settings):
    fixed = replace(settings, safety_stock_policy="fixed", stock_multipliers=(1.0,))
    assert candidate_levels(lane, fixed) == (float(ceil(lead_time_demand_kg(lane, fixed))),)


def test_grid_multipliers_apply_to_every_policy(lane, settings):
    fixed = replace(settings, safety_stock_policy="fixed", safety_stock_kg=10)
    levels = candidate_levels(lane, fixed)
    assert len(levels) == len(settings.stock_multipliers)
    assert levels == tuple(sorted(levels))


def test_policy_summary(lane, settings):
    other = replace(lane, site_id="Other", lead_time_days=3)
    fixed = replace(settings, safety_stock_policy="fixed", safety_stock_kg=12)
    rows = policy_summary((other, lane), fixed)
    assert [row["lane"] for row in rows] == [lane.key, other.key]
    for row in rows:
        assert row["policy"] == "fixed"
        assert row["safety_stock_kg"] == 12
        assert row["centre_kg"] == pytest.approx(row["lead_time_demand_kg"] + 12)


def test_scenario_runs_with_fixed_policy(lane, settings):
    fixed = replace(settings, safety_stock_policy="fixed", safety_stock_kg=8)
    result = run_scenario((lane,), fixed)
    assert result.results[0].chosen_base_stock_kg in candidate_levels(lane, fixed)


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"safety_stock_policy": "minimum"}, "safety_stock_policy"),
        ({"safety_stock_kg": -1}, "safety_stock_kg"),
        ({"safety_stock_percentage": -5}, "safety_stock_percentage"),
        ({"safety_stock_percentage": 600}, "at most 500"),
    ],
)
def test_invalid_settings(changes, message):
    with pytest.raises(InputError, match=message):
        Settings(**changes)


def test_settings_round_trip(tmp_path, settings):
    import json
    from dataclasses import asdict

    from meridian.inputs import load_settings

    custom = replace(settings, safety_stock_policy="fixed", safety_stock_kg=25.0)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(asdict(custom)))
    assert load_settings(path) == custom


def test_compare_policies_rows(lane, settings):
    rows = compare_policies((lane,), replace(settings, safety_stock_kg=5))
    assert [row["policy"] for row in rows] == list(POLICIES)
    for row in rows:
        assert row["mean_total_cost"] > 0
        assert 0 <= row["fill_rate"] <= 1
        assert row["lanes_meeting_target"] in (0, 1)


def test_compare_policies_statistical_matches_scenario(lane, settings):
    from meridian.reporting import summary

    (row,) = compare_policies((lane,), settings, ("statistical",))
    report = summary(run_scenario((lane,), settings))
    assert row["mean_total_cost"] == pytest.approx(report["total_mean_cost"])
    assert row["fill_rate"] == pytest.approx(report["portfolio_fill_rate"])


def test_compare_policies_rejects_unknown(lane, settings):
    with pytest.raises(InputError, match="Unknown policies: minimum"):
        compare_policies((lane,), settings, ("fixed", "minimum"))


def test_compare_policies_deduplicates(lane, settings):
    rows = compare_policies((lane,), settings, ("fixed", "fixed"))
    assert len(rows) == 1


def test_more_fixed_stock_raises_grid(lane, settings):
    low = candidate_levels(lane, replace(settings, safety_stock_policy="fixed", safety_stock_kg=0))
    high = candidate_levels(
        lane, replace(settings, safety_stock_policy="fixed", safety_stock_kg=50)
    )
    assert min(high) > min(low)


def test_policies_command(capsys):
    from pathlib import Path

    from meridian.cli import main

    root = Path(__file__).resolve().parents[2]
    code = main(
        [
            "policies",
            "--data",
            str(root / "data/synthetic_sites.csv"),
            "--config",
            str(root / "config/quickstart.json"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Harbor:nitrogen: lead-time demand" in out
    assert out.count("lanes meet the target") == 3


def test_no_warnings_by_default(settings):
    assert policy_warnings(settings) == []


@pytest.mark.parametrize(
    "changes, fragment",
    [
        ({"safety_stock_policy": "fixed"}, "no safety stock"),
        ({"safety_stock_policy": "percentage"}, "no safety stock"),
        ({"safety_stock_kg": 10}, "only the fixed policy"),
        ({"safety_stock_percentage": 10}, "only the percentage policy"),
    ],
)
def test_policy_warnings(settings, changes, fragment):
    warnings = policy_warnings(replace(settings, **changes))
    assert len(warnings) == 1 and fragment in warnings[0]


def test_fixed_with_stock_has_no_warning(settings):
    assert policy_warnings(replace(settings, safety_stock_policy="fixed", safety_stock_kg=5)) == []


def test_policies_command_prints_notes(tmp_path, capsys):
    import json
    from pathlib import Path

    from meridian.cli import main

    root = Path(__file__).resolve().parents[2]
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"horizon_days": 8, "replications": 2, "safety_stock_kg": 50}))
    assert (
        main(
            ["policies", "--data", str(root / "data/synthetic_sites.csv"), "--config", str(config)]
        )
        == 0
    )
    assert "Note: safety_stock_kg is set" in capsys.readouterr().err


def test_policy_summary_statistical_matches_grid(lane, settings):
    single = replace(settings, stock_multipliers=(1.0,))
    (row,) = policy_summary((lane,), single)
    assert candidate_levels(lane, single) == (float(ceil(row["centre_kg"])),)


def test_policy_summary_sorted_and_complete(lane, settings):
    lanes = (replace(lane, site_id="Zulu"), replace(lane, site_id="Alpha"), lane)
    rows = policy_summary(lanes, settings)
    assert [row["lane"] for row in rows] == sorted(row["lane"] for row in rows)
    assert all(
        set(row) == {"lane", "policy", "lead_time_demand_kg", "safety_stock_kg", "centre_kg"}
        for row in rows
    )


def test_safety_stock_rejects_unknown_policy(lane, settings):
    broken = replace(settings)
    object.__setattr__(broken, "safety_stock_policy", "other")
    with pytest.raises(InputError, match="Unknown safety_stock_policy"):
        safety_stock(lane, broken)
    with pytest.raises(InputError, match="Unknown safety_stock_policy"):
        candidate_levels(lane, broken)
