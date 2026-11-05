"""The scenario-diff command and its comparison helpers."""

import json

import pytest

from meridian.cli import main
from meridian.models import InputError
from meridian.scenario_diff import (
    MISSING,
    Change,
    _compare,
    changed_settings,
    diff_settings,
    setting_changes,
)


def _scenario(tmp_path, name, **values):
    path = tmp_path / f"{name}-{len(list(tmp_path.iterdir()))}.json"
    path.write_text(json.dumps({"scenario_id": name, **values}), encoding="utf-8")
    return path


def test_identical_files(tmp_path):
    a = _scenario(tmp_path, "same", horizon_days=30)
    assert diff_settings(a, a) == []
    assert setting_changes(a, a) == []


def test_changed_values(tmp_path):
    a = _scenario(tmp_path, "first", horizon_days=30, replications=4)
    b = _scenario(tmp_path, "second", horizon_days=45, replications=4)
    assert diff_settings(a, b) == [
        "horizon_days: 30 -> 45",
        'scenario_id: "first" -> "second"',
    ]


def test_defaults_are_filled_in(tmp_path):
    a = _scenario(tmp_path, "plan", horizon_days=60)
    b = _scenario(tmp_path, "plan", horizon_days=60, replications=4)
    assert diff_settings(a, b) == []


def test_default_versus_explicit_change(tmp_path):
    a = _scenario(tmp_path, "plan")
    b = _scenario(tmp_path, "plan", service_target=0.98)
    assert diff_settings(a, b) == ["service_target: 0.95 -> 0.98"]


def test_stock_multipliers_compared_after_sorting(tmp_path):
    a = _scenario(tmp_path, "plan", stock_multipliers=[1.5, 0.75, 1.0])
    b = _scenario(tmp_path, "plan", stock_multipliers=[0.75, 1.0, 1.5])
    assert diff_settings(a, b) == []


def test_stock_multipliers_added_entry(tmp_path):
    a = _scenario(tmp_path, "plan", stock_multipliers=[0.75, 1.0])
    b = _scenario(tmp_path, "plan", stock_multipliers=[0.75, 1.0, 2.0])
    assert diff_settings(a, b) == ["stock_multipliers[2]: (none) -> 2.0"]


def test_stock_multipliers_removed_entry(tmp_path):
    a = _scenario(tmp_path, "plan", stock_multipliers=[0.5, 0.75, 1.0])
    b = _scenario(tmp_path, "plan", stock_multipliers=[0.5, 0.75])
    changes = setting_changes(a, b)
    assert [(c.path, c.kind) for c in changes] == [("stock_multipliers[2]", "removed")]


def test_ignore(tmp_path):
    a = _scenario(tmp_path, "first", seed=1)
    b = _scenario(tmp_path, "second", seed=2)
    assert diff_settings(a, b, ("scenario_id",)) == ["seed: 1 -> 2"]


def test_ignore_unknown_setting(tmp_path):
    a = _scenario(tmp_path, "plan")
    with pytest.raises(InputError, match="Unknown setting to ignore: colour"):
        diff_settings(a, a, ("colour",))


def test_changed_settings(tmp_path):
    a = _scenario(tmp_path, "first", stock_multipliers=[0.5, 1.0])
    b = _scenario(tmp_path, "second", stock_multipliers=[0.5, 1.5])
    assert changed_settings(a, b) == ["scenario_id", "stock_multipliers"]


def test_invalid_file_rejected(tmp_path):
    a = _scenario(tmp_path, "plan")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"colour": "blue"}), encoding="utf-8")
    with pytest.raises(InputError, match="Unknown settings"):
        diff_settings(a, bad)


def test_change_kinds():
    assert Change("a", MISSING, 1).kind == "added"
    assert Change("a", 1, MISSING).kind == "removed"
    assert Change("a", 1, 2).kind == "changed"


def test_compare_nested_structures():
    changes = []
    _compare(
        {"a": {"b": 1, "c": [1, 2]}, "d": "x"},
        {"a": {"b": 2, "c": [1, 3]}, "e": "y"},
        "",
        changes,
    )
    assert [(c.path, c.before, c.after) for c in changes] == [
        ("a.b", 1, 2),
        ("a.c[1]", 2, 3),
        ("d", "x", MISSING),
        ("e", MISSING, "y"),
    ]


def test_compare_type_change():
    changes = []
    _compare({"a": [1]}, {"a": {"x": 1}}, "", changes)
    assert [(c.path, c.before, c.after) for c in changes] == [("a", [1], {"x": 1})]


def test_example_configs():
    assert diff_settings("config/baseline.json", "config/higher_demand.json") == [
        "demand_multiplier: 1.0 -> 1.25",
        'scenario_id: "baseline" -> "higher-demand"',
    ]


def test_cli_text(capsys):
    assert main(["scenario-diff", "config/baseline.json", "config/higher_demand.json"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "demand_multiplier: 1.0 -> 1.25"


def test_cli_no_differences(capsys):
    assert main(["scenario-diff", "config/baseline.json", "config/baseline.json"]) == 0
    assert capsys.readouterr().out.strip() == "No differences"


def test_cli_json(capsys):
    args = ["scenario-diff", "config/baseline.json", "config/higher_demand.json", "--json"]
    assert main(args) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0] == {
        "setting": "demand_multiplier",
        "kind": "changed",
        "before": 1.0,
        "after": 1.25,
    }


def test_cli_json_missing_side(tmp_path, capsys):
    a = _scenario(tmp_path, "plan", stock_multipliers=[0.5])
    b = _scenario(tmp_path, "plan", stock_multipliers=[0.5, 1.0])
    assert main(["scenario-diff", str(a), str(b), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows == [
        {"setting": "stock_multipliers[1]", "kind": "added", "before": None, "after": 1.0}
    ]


def test_cli_ignore(capsys):
    args = ["scenario-diff", "config/baseline.json", "config/higher_demand.json"]
    assert main([*args, "--ignore", "scenario_id"]) == 0
    assert capsys.readouterr().out.strip() == "demand_multiplier: 1.0 -> 1.25"


def test_cli_exit_code(capsys):
    args = ["scenario-diff", "config/baseline.json", "config/higher_demand.json"]
    assert main([*args, "--exit-code"]) == 1
    assert (
        main(["scenario-diff", "config/baseline.json", "config/baseline.json", "--exit-code"]) == 0
    )


def test_cli_invalid_file(tmp_path, capsys):
    assert main(["scenario-diff", "config/baseline.json", str(tmp_path / "missing.json")]) == 2
    assert "Input/output error" in capsys.readouterr().err


def test_integer_and_float_equal(tmp_path):
    a = _scenario(tmp_path, "plan", demand_multiplier=1)
    b = _scenario(tmp_path, "plan", demand_multiplier=1.0)
    assert diff_settings(a, b) == []


def test_boolean_and_text_display(tmp_path):
    changes = [Change("flag", True, False), Change("name", "a", MISSING)]
    from meridian.scenario_diff import _show

    assert [(_show(c.before), _show(c.after)) for c in changes] == [
        ("true", "false"),
        ('"a"', "(none)"),
    ]
