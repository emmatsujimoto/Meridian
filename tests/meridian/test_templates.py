"""Starter scenario templates and the new-scenario command."""

import csv
import io
import json

import pytest

from meridian.cli import main
from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.templates import (
    LANE_COLUMNS,
    TEMPLATES,
    describe_templates,
    lanes_text,
    scenario_files,
    settings_text,
    template_names,
    write_scenario,
)


def test_template_names():
    assert template_names() == ["quickstart", "baseline", "high-demand", "single-site"]


def test_describe_templates():
    rows = {row["name"]: row for row in describe_templates()}
    assert rows["baseline"]["lanes"] == 6
    assert rows["quickstart"]["horizon_days"] == 14
    assert rows["single-site"]["lanes"] == 1
    assert all(row["description"] for row in rows.values())


@pytest.mark.parametrize("name", list(TEMPLATES))
def test_settings_text_is_valid(tmp_path, name):
    path = tmp_path / "settings.json"
    path.write_text(settings_text("trial-run", name), encoding="utf-8")
    settings = load_settings(path)
    assert settings.scenario_id == "trial-run"
    assert settings.horizon_days == TEMPLATES[name]["settings"]["horizon_days"]


@pytest.mark.parametrize("name", list(TEMPLATES))
def test_lanes_text_is_valid(tmp_path, name):
    path = tmp_path / "lanes.csv"
    path.write_text(lanes_text(name), encoding="utf-8")
    assert len(load_lanes(path)) == len(TEMPLATES[name]["lanes"])


def test_lanes_text_header():
    header = next(csv.reader(io.StringIO(lanes_text("quickstart"))))
    assert tuple(header) == LANE_COLUMNS


def test_baseline_matches_example_data():
    with open("data/synthetic_sites.csv", encoding="utf-8") as stream:
        example = stream.read().strip().splitlines()
    assert lanes_text("baseline").strip().splitlines() == example


def test_high_demand_scales_demand():
    settings = json.loads(settings_text("busy", "high-demand"))
    assert settings["demand_multiplier"] == 1.25


def test_scenario_files_names():
    assert sorted(scenario_files("plan-a", "quickstart")) == ["plan-a.json", "plan-a_sites.csv"]


def test_unknown_template():
    with pytest.raises(InputError, match="choose from quickstart"):
        settings_text("plan-a", "weekly")


def test_unsafe_scenario_id():
    with pytest.raises(InputError, match="scenario_id"):
        settings_text("../plan", "quickstart")


def test_write_scenario(tmp_path):
    written = write_scenario("plan-a", tmp_path, "single-site")
    assert written["settings"] == tmp_path / "plan-a.json"
    assert written["lanes"] == tmp_path / "plan-a_sites.csv"
    assert written["replaced"] == []
    assert load_settings(written["settings"]).horizon_days == 90


def test_write_scenario_missing_folder(tmp_path):
    with pytest.raises(InputError, match="does not exist"):
        write_scenario("plan-a", tmp_path / "missing")


def test_generated_scenario_runs(tmp_path):
    written = write_scenario("plan-a", tmp_path, "quickstart")
    result = run_scenario(load_lanes(written["lanes"]), load_settings(written["settings"]))
    assert len(result.results) == 2


def test_cli_list(capsys):
    assert main(["new-scenario", "--list"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines] == template_names()


def test_cli_writes_files(tmp_path, capsys):
    assert main(["new-scenario", "plan-b", "--folder", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert (tmp_path / "plan-b.json").is_file()
    assert (tmp_path / "plan-b_sites.csv").is_file()
    assert "Next: meridian validate" in out
    assert "Replaced" not in out


def test_cli_generated_files_validate(tmp_path, capsys):
    assert (
        main(["new-scenario", "plan-c", "--template", "baseline", "--folder", str(tmp_path)]) == 0
    )
    capsys.readouterr()
    data, config = str(tmp_path / "plan-c_sites.csv"), str(tmp_path / "plan-c.json")
    assert main(["validate", "--data", data, "--config", config]) == 0
    assert "6 product-location rows" in capsys.readouterr().out


def test_cli_needs_name(capsys):
    assert main(["new-scenario"]) == 2
    assert "Provide a scenario name" in capsys.readouterr().err


def test_cli_unknown_template(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["new-scenario", "plan-d", "--template", "weekly", "--folder", str(tmp_path)])
    assert "invalid choice" in capsys.readouterr().err


def test_cli_bad_name(tmp_path, capsys):
    assert main(["new-scenario", "9lives", "--folder", str(tmp_path)]) == 2
    assert "scenario_id" in capsys.readouterr().err


def test_overrides_applied():
    settings = json.loads(settings_text("plan-e", "baseline", {"horizon_days": 30}))
    assert settings["horizon_days"] == 30
    assert settings["replications"] == 4


def test_override_validated():
    with pytest.raises(InputError, match="horizon_days"):
        settings_text("plan-e", "baseline", {"horizon_days": 0})


def test_unknown_override_rejected():
    with pytest.raises(InputError, match="Cannot override"):
        settings_text("plan-e", "baseline", {"colour": "blue"})


def test_scenario_id_not_overridable():
    with pytest.raises(InputError, match="Cannot override"):
        settings_text("plan-e", "baseline", {"scenario_id": "other"})


def test_cli_overrides(tmp_path, capsys):
    args = ["new-scenario", "plan-f", "--folder", str(tmp_path), "--horizon", "21"]
    assert main([*args, "--replications", "3"]) == 0
    settings = load_settings(tmp_path / "plan-f.json")
    assert (settings.horizon_days, settings.replications) == (21, 3)


def test_cli_invalid_override(tmp_path, capsys):
    assert main(["new-scenario", "plan-g", "--folder", str(tmp_path), "--horizon", "999"]) == 2
    assert not (tmp_path / "plan-g.json").exists()
