"""Scenario runs with supplier disruptions enabled.

Outage generators are replaced with seeded ones keyed by lane, phase and replication, so
these tests are deterministic and independent of how schedules are drawn.
"""

import csv
import json
import random
from dataclasses import replace

import pytest

from meridian import disruptions
from meridian.cli import main
from meridian.disruptions import SCHEDULE_COLUMNS, schedule_statistics, write_schedules
from meridian.inputs import load_settings
from meridian.models import InputError, Settings
from meridian.planning import (
    disruption_impact,
    impact_table,
    outage_stress_test,
    run_scenario,
    stock_for_outage,
    stress_table,
)
from meridian.reporting import export_run, summary


@pytest.fixture
def seeded(monkeypatch):
    calls = []

    def fake_rng(settings, lane, phase, replication):
        calls.append((lane.key, phase, replication))
        return random.Random(f"{settings.seed}:{lane.key}:{phase}:{replication}")

    monkeypatch.setattr(disruptions, "disruption_rng", fake_rng)
    return calls


@pytest.fixture
def disrupted(settings):
    return replace(settings, supplier_disruptions=True, max_outage_days=1)


# Settings


def test_disruptions_off_by_default():
    settings = Settings()
    assert settings.supplier_disruptions is False
    assert settings.max_outage_days == 5


def test_flag_must_be_boolean():
    with pytest.raises(InputError, match="supplier_disruptions"):
        Settings(supplier_disruptions="yes")


@pytest.mark.parametrize("days", [0, 61, 2.5])
def test_max_outage_limits(days):
    with pytest.raises(InputError, match="max_outage_days"):
        Settings(max_outage_days=days)


def test_settings_from_json(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"supplier_disruptions": True, "max_outage_days": 3}))
    settings = load_settings(path)
    assert (settings.supplier_disruptions, settings.max_outage_days) == (True, 3)


def test_example_configs_unchanged():
    for name in ("config/baseline.json", "config/quickstart.json"):
        assert load_settings(name).supplier_disruptions is False


# Scenario runs


def test_run_uses_outage_schedules(seeded, lane, disrupted):
    result = run_scenario((lane,), disrupted)
    phases = {phase for _, phase, _ in seeded}
    assert phases == {"training", "validation"}
    assert {replication for *_, replication in seeded} == set(range(disrupted.replications))
    assert len(result.results[0].validation_trials) == disrupted.replications


def test_run_without_disruptions_draws_nothing(seeded, lane, settings):
    run_scenario((lane,), settings)
    assert seeded == []


def test_runs_repeat_with_seeded_schedules(seeded, lane, disrupted):
    assert run_scenario((lane,), disrupted) == run_scenario((lane,), disrupted)


def test_disruptions_never_improve_service(seeded, lane, settings, disrupted):
    long = replace(settings, horizon_days=120)
    plain = run_scenario((lane,), long).results[0]
    outaged = run_scenario((lane,), replace(disrupted, horizon_days=120)).results[0]
    plain_fill = sum(t.fill_rate for t in plain.validation_trials)
    outaged_fill = sum(t.fill_rate for t in outaged.validation_trials)
    if plain.chosen_base_stock_kg == outaged.chosen_base_stock_kg:
        assert outaged_fill <= plain_fill + 1e-9


def test_model_notes(seeded, lane, disrupted):
    notes = summary(run_scenario((lane,), disrupted))["model_notes"]
    assert any("supplier outages of up to 1 days" in note for note in notes)


def test_no_disruption_notes_by_default(lane, settings):
    notes = summary(run_scenario((lane,), settings))["model_notes"]
    assert not any("outage" in note.lower() for note in notes)


def test_bundle_with_disruptions(seeded, tmp_path, lane, disrupted):
    bundle = export_run(run_scenario((lane,), disrupted), tmp_path)
    report = (bundle / "report.md").read_text(encoding="utf-8")
    assert "supplier outages" in report
    saved = json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
    assert saved["inputs"]["settings"]["supplier_disruptions"] is True


def test_fingerprint_changes_with_flag(seeded, lane, settings, disrupted):
    plain = summary(run_scenario((lane,), settings))["input_sha256"]
    outaged = summary(run_scenario((lane,), disrupted))["input_sha256"]
    assert plain != outaged


# Command line


def _config(tmp_path, **values):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"horizon_days": 30, "replications": 3, "max_outage_days": 1, **values})
    )
    return str(path)


def test_cli_outages(seeded, tmp_path, capsys):
    args = ["outages", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    assert main([*args, "--lane", "Harbor:nitrogen"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["replication"] for row in rows] == [1, 2, 3]
    for row in rows:
        assert row["summary"]["outages"] == len(row["outages"])
        assert all(1 <= outage["first_day"] <= 30 for outage in row["outages"])


def test_cli_outages_phase(seeded, tmp_path, capsys):
    args = ["outages", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    assert main([*args, "--lane", "Summit:argon", "--phase", "training"]) == 0
    capsys.readouterr()
    assert {phase for _, phase, _ in seeded} == {"training"}


def test_cli_outages_unknown_lane(seeded, tmp_path, capsys):
    args = ["outages", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    assert main([*args, "--lane", "Nowhere:argon"]) == 2
    assert "No product-location" in capsys.readouterr().err


def test_cli_run_with_disruptions(seeded, tmp_path, capsys):
    config = _config(tmp_path, supplier_disruptions=True)
    output = str(tmp_path / "results")
    args = ["run", "--data", "data/synthetic_sites.csv", "--config", config, "--output", output]
    assert main(args) == 0
    assert "Results saved to" in capsys.readouterr().out


# Schedule statistics, impact and stress tests


def test_schedule_statistics(seeded, lane, disrupted):
    stats = schedule_statistics(replace(disrupted, horizon_days=200, replications=5), lane)
    assert stats["lane"] == lane.key
    assert stats["phase"] == "validation"
    assert stats["replications"] == 5
    assert 0 <= stats["mean_offline_share"] <= 1
    assert 0 <= stats["replications_with_outage"] <= 5
    assert stats["longest_outage_days"] <= 1


def test_schedule_statistics_training(seeded, lane, disrupted):
    schedule_statistics(disrupted, lane, "training")
    assert {phase for _, phase, _ in seeded} == {"training"}


def test_disruption_impact(seeded, lane, settings):
    lanes = (lane, replace(lane, site_id="North", daily_sd_kg=3))
    rows = disruption_impact(lanes, replace(settings, max_outage_days=1))
    assert [row["lane"] for row in rows] == ["Example:nitrogen", "North:nitrogen"]
    for row in rows:
        assert row["cost_increase"] == pytest.approx(
            row["mean_cost_with_outages"] - row["mean_cost"]
        )
        assert 0 <= row["fill_rate_with_outages"] <= 1


def test_disruption_impact_ignores_flag(seeded, lane, settings):
    flagged = replace(settings, supplier_disruptions=True, max_outage_days=1)
    rows = disruption_impact((lane,), flagged)
    plain = run_scenario((lane,), settings).results[0]
    assert rows[0]["base_stock_kg"] == plain.chosen_base_stock_kg


def test_outage_stress_test(lane, settings):
    rows = outage_stress_test(lane, replace(settings, horizon_days=20), 30.0, (5, 1, 3), 2)
    assert [row["outage_days"] for row in rows] == [1, 3, 5]
    fills = [row["mean_fill_rate"] for row in rows]
    assert fills == sorted(fills, reverse=True)
    assert all(row["start_day"] == 2 for row in rows)


def test_outage_stress_test_repeatable(lane, settings):
    args = (lane, settings, 30.0, (2,), 1)
    assert outage_stress_test(*args) == outage_stress_test(*args)


@pytest.mark.parametrize("lengths", [(), tuple(range(1, 22))])
def test_outage_stress_test_limits(lane, settings, lengths):
    with pytest.raises(InputError, match="1-20 outage lengths"):
        outage_stress_test(lane, settings, 30.0, lengths, 1)


def test_outage_stress_test_start_day(lane, settings):
    with pytest.raises(InputError, match="start_day"):
        outage_stress_test(lane, settings, 30.0, (1,), settings.horizon_days + 1)


def test_cli_outages_summary(seeded, tmp_path, capsys):
    args = ["outages", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    assert main([*args, "--lane", "Harbor:nitrogen", "--summary"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["replications"] == 3


def test_cli_disruption_impact(seeded, tmp_path, capsys):
    args = ["disruption-impact", "--data", "data/synthetic_sites.csv"]
    assert main([*args, "--config", _config(tmp_path, horizon_days=10, replications=2)]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 6
    assert {"cost_increase", "fill_rate_with_outages"} <= set(rows[0])


def test_cli_outage_stress(tmp_path, capsys):
    args = ["outage-stress", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    args += ["--lane", "Harbor:nitrogen", "--base-stock", "3000", "--days", "1", "4"]
    assert main(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["outage_days"] for row in rows] == [1, 4]


def test_cli_outage_stress_bad_start(tmp_path, capsys):
    args = ["outage-stress", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    args += ["--lane", "Harbor:nitrogen", "--base-stock", "3000", "--start-day", "99"]
    assert main(args) == 2
    assert "start_day" in capsys.readouterr().err


# Schedules on file, tables and stock search


def test_write_schedules(seeded, tmp_path, lane, disrupted):
    lanes = (lane, replace(lane, site_id="North"))
    long = replace(disrupted, horizon_days=300)
    path, count = write_schedules(long, lanes, "validation", tmp_path / "outages.csv")
    with open(path, newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == count
    assert rows
    assert tuple(rows[0]) == SCHEDULE_COLUMNS
    assert all(row["phase"] == "validation" for row in rows)
    assert all(1 <= int(row["first_day"]) <= 300 for row in rows)


def test_write_schedules_never_replaces(seeded, tmp_path, lane, disrupted):
    target = tmp_path / "outages.csv"
    write_schedules(disrupted, (lane,), "validation", target)
    with pytest.raises(InputError, match="already exists"):
        write_schedules(disrupted, (lane,), "validation", target)


def test_stress_table(lane, settings):
    rows = outage_stress_test(lane, settings, 30.0, (1, 2), 1)
    lines = stress_table(rows).splitlines()
    assert lines[0].startswith("| Outage (days) |")
    assert [line.split("|")[1].strip() for line in lines[2:]] == ["1", "2"]


def test_impact_table(seeded, lane, disrupted):
    lines = impact_table(disruption_impact((lane,), disrupted)).splitlines()
    assert lines[0].startswith("| Product-location | Stock (kg)")
    assert lines[2].startswith("| Example:nitrogen |")


def test_stock_for_outage(lane, settings):
    result = stock_for_outage(lane, settings, 1)
    assert result["lane"] == lane.key
    assert result["outage_days"] == 1
    if result["base_stock_kg"] is not None:
        assert result["mean_fill_rate"] >= settings.service_target
        failing = [
            row for row in result["tested"] if row["base_stock_kg"] < result["base_stock_kg"]
        ]
        assert all(row["mean_fill_rate"] < settings.service_target for row in failing)


def test_stock_for_outage_none_enough(lane, settings):
    impossible = replace(settings, service_target=1.0, horizon_days=6)
    result = stock_for_outage(replace(lane, lead_time_days=5), impossible, 6)
    assert result["base_stock_kg"] is None
    assert result["tested"]


def test_cli_outages_csv(seeded, tmp_path, capsys):
    args = ["outages", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    target = tmp_path / "outages.csv"
    assert main([*args, "--lane", "Harbor:nitrogen", "--csv", str(target)]) == 0
    assert "outages written to" in capsys.readouterr().out
    assert target.is_file()


def test_cli_stress_table(tmp_path, capsys):
    args = ["outage-stress", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    args += ["--lane", "Harbor:nitrogen", "--base-stock", "3000", "--format", "table"]
    assert main(args) == 0
    assert capsys.readouterr().out.startswith("| Outage (days) |")


def test_cli_stress_needs_stock(tmp_path, capsys):
    args = ["outage-stress", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    assert main([*args, "--lane", "Harbor:nitrogen"]) == 2
    assert "--find-stock" in capsys.readouterr().err


def test_cli_find_stock(tmp_path, capsys):
    args = ["outage-stress", "--data", "data/synthetic_sites.csv", "--config", _config(tmp_path)]
    assert main([*args, "--lane", "Summit:argon", "--find-stock", "--days", "2"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["outage_days"] == 2
    assert rows[0]["tested"]


def test_cli_impact_table(seeded, tmp_path, capsys):
    args = ["disruption-impact", "--data", "data/synthetic_sites.csv", "--format", "table"]
    assert main([*args, "--config", _config(tmp_path, horizon_days=10, replications=2)]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 8


def test_schedules_differ_by_lane_and_phase(seeded, lane, disrupted):
    from meridian.disruptions import outage_schedule

    long = replace(disrupted, horizon_days=366)
    north = replace(lane, site_id="North")
    first = outage_schedule(long, lane, "validation", 0)[0]
    assert first == outage_schedule(long, lane, "validation", 0)[0]
    others = [
        outage_schedule(long, north, "validation", 0)[0],
        outage_schedule(long, lane, "training", 0)[0],
        outage_schedule(long, lane, "validation", 1)[0],
    ]
    assert any(schedule != first for schedule in others)


def test_validation_trials_respect_outages(seeded, lane, disrupted):
    from meridian.disruptions import outage_schedule

    long = replace(disrupted, horizon_days=200, replications=2)
    result = run_scenario((lane,), long).results[0]
    for index, trial in enumerate(result.validation_trials):
        _, offline = outage_schedule(long, lane, "validation", index)
        assert all(
            period.ordered_kg == 0
            for period, down in zip(trial.periods, offline, strict=True)
            if down
        )
