"""The demand model registry and plugin discovery."""

import json

import numpy as np
import pytest

from meridian import plugins
from meridian.cli import main
from meridian.models import InputError
from meridian.plugins import (
    BUILT_IN_MODELS,
    ENTRY_POINT_GROUP,
    DemandModel,
    available_models,
    describe_models,
    draw,
    getModel,
    load_plugins,
    registerModel,
    reset_registry,
    unregister_model,
)


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    monkeypatch.setattr(plugins, "entry_points", lambda group: [])
    reset_registry()
    yield
    reset_registry()


class FakeEntryPoint:
    def __init__(self, name, target, value="example_pkg:sampler"):
        self.name = name
        self.value = value
        self._target = target

    def load(self):
        return self._target


def _install(monkeypatch, *points):
    requested = []

    def fake_entry_points(group):
        requested.append(group)
        return list(points)

    monkeypatch.setattr(plugins, "entry_points", fake_entry_points)
    return requested


def _weekly(rng, mean, sd, shape):
    """Double demand on the first day of each week."""
    samples = np.full(shape, mean)
    samples[:, ::7] *= 2
    return samples


def test_built_in_models_registered():
    names = [model.name for model in available_models()]
    assert names[: len(BUILT_IN_MODELS)] == [model.name for model in BUILT_IN_MODELS]
    assert "lognormal" in names
    assert all(model.source == "built-in" for model in BUILT_IN_MODELS)


def test_get_built_in():
    assert getModel("gamma").name == "gamma"


def test_unknown_model_lists_choices():
    with pytest.raises(
        InputError, match="available: constant, gamma, lognormal, normal, poisson, uniform"
    ):
        getModel("weibull")


def test_register_and_get():
    model = registerModel("weekly", _weekly)
    assert getModel("weekly") is model
    assert model.source == "plugin"
    assert model.description == "Double demand on the first day of each week."


def test_register_explicit_description():
    assert registerModel("weekly", _weekly, "Weekly peaks").description == "Weekly peaks"


def test_register_rejects_bad_name():
    with pytest.raises(InputError, match="demand model name"):
        registerModel("../weekly", _weekly)


def test_register_rejects_non_callable():
    with pytest.raises(InputError, match="must be callable"):
        registerModel("weekly", 42)


def test_plugins_discovered_from_entry_points(monkeypatch):
    requested = _install(monkeypatch, FakeEntryPoint("weekly", _weekly))
    assert getModel("weekly").source == "plugin example_pkg:sampler"
    assert requested == [ENTRY_POINT_GROUP]


def test_entry_point_can_name_a_demand_model(monkeypatch):
    declared = DemandModel("ignored", _weekly, "Declared description")
    _install(monkeypatch, FakeEntryPoint("weekly", declared))
    model = getModel("weekly")
    assert model.name == "weekly"
    assert model.description == "Declared description"


def test_plugins_loaded_once(monkeypatch):
    requested = _install(monkeypatch, FakeEntryPoint("weekly", _weekly))
    getModel("weekly")
    getModel("lognormal")
    available_models()
    assert len(requested) == 1


def test_force_reload(monkeypatch):
    requested = _install(monkeypatch, FakeEntryPoint("weekly", _weekly))
    assert load_plugins() == ["weekly"]
    assert load_plugins() == []
    assert load_plugins(force=True) == ["weekly"]
    assert len(requested) == 2


def test_plugins_sorted_after_built_ins(monkeypatch):
    _install(monkeypatch, FakeEntryPoint("zeta", _weekly), FakeEntryPoint("alpha", _weekly))
    names = [model.name for model in available_models()]
    assert names[-2:] == ["alpha", "zeta"]


def test_describe_models():
    registerModel("weekly", _weekly, "Weekly peaks")
    rows = describe_models()
    assert rows[0] == {
        "name": "lognormal",
        "description": BUILT_IN_MODELS[0].description,
        "source": "built-in",
    }
    assert rows[-1]["name"] == "weekly"


def test_unregister_plugin():
    registerModel("weekly", _weekly)
    unregister_model("weekly")
    with pytest.raises(InputError):
        getModel("weekly")


def test_unregister_built_in_refused():
    with pytest.raises(InputError, match="cannot be removed"):
        unregister_model("normal")


def test_unregister_unknown():
    with pytest.raises(InputError, match="Unknown demand model"):
        unregister_model("weekly")


def test_reset_registry_forgets_plugins():
    registerModel("weekly", _weekly)
    reset_registry()
    assert [model.name for model in available_models()] == [m.name for m in BUILT_IN_MODELS]


def test_draw_checks_shape():
    model = registerModel("short", lambda rng, mean, sd, shape: np.zeros(3))
    with pytest.raises(InputError, match="returned shape"):
        draw(model, np.random.default_rng(1), 10.0, 1.0, (2, 4))


def test_draw_rejects_negative():
    model = registerModel("negative", lambda rng, mean, sd, shape: np.full(shape, -1.0))
    with pytest.raises(InputError, match="negative demand"):
        draw(model, np.random.default_rng(1), 10.0, 1.0, (2, 4))


def test_draw_rejects_nonfinite():
    model = registerModel("infinite", lambda rng, mean, sd, shape: np.full(shape, np.inf))
    with pytest.raises(InputError, match="overflow"):
        draw(model, np.random.default_rng(1), 10.0, 1.0, (2, 4))


def test_draw_wraps_sampler_errors():
    def broken(rng, mean, sd, shape):
        raise ValueError("bad parameters")

    model = registerModel("broken", broken)
    with pytest.raises(InputError, match="broken failed: bad parameters"):
        draw(model, np.random.default_rng(1), 10.0, 1.0, (2, 4))


def test_draw_accepts_lists():
    model = registerModel("listed", lambda rng, mean, sd, shape: [[mean] * shape[1]] * shape[0])
    samples = draw(model, np.random.default_rng(1), 10.0, 1.0, (2, 3))
    assert samples.tolist() == [[10.0] * 3] * 2


def test_cli_lists_models(capsys):
    registerModel("weekly", _weekly, "Weekly peaks")
    assert main(["models"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("lognormal")
    assert "built-in" in lines[0]
    assert lines[-1].split()[:2] == ["weekly", "plugin"]


def test_cli_lists_models_json(capsys):
    assert main(["models", "--json"]) == 0
    names = [row["name"] for row in json.loads(capsys.readouterr().out)]
    assert names == [model.name for model in BUILT_IN_MODELS]


@pytest.mark.parametrize("name", [model.name for model in BUILT_IN_MODELS])
def test_built_in_models_pass_checks(name):
    assert all(row["passed"] for row in plugins.check_model(getModel(name)))


def test_check_reports_shape_problem():
    model = registerModel("fixed", lambda rng, mean, sd, shape: np.full((4, 30), mean))
    results = {row["case"]: row for row in plugins.check_model(model)}
    assert results["typical"]["passed"]
    assert not results["single day"]["passed"]
    assert "returned shape" in results["single day"]["detail"]


def test_check_reports_unseeded_model():
    unseeded = np.random.default_rng()

    def noisy(rng, mean, sd, shape):
        return np.full(shape, mean) + unseeded.uniform(0, 1, size=shape)

    model = registerModel("noisy", noisy)
    results = plugins.check_model(model)
    assert not any(row["passed"] for row in results)
    assert "use the rng argument" in results[0]["detail"]


def test_check_reports_negative_draws():
    model = registerModel("unclipped", lambda rng, mean, sd, shape: rng.normal(mean, sd, shape))
    results = {row["case"]: row for row in plugins.check_model(model)}
    assert results["zero deviation"]["passed"]
    assert not results["high variability"]["passed"]


def test_check_table():
    text = plugins.check_table(
        "demo",
        [
            {"case": "typical", "passed": True, "detail": "mean 100.00 for requested 100"},
            {"case": "single day", "passed": False, "detail": "wrong shape"},
        ],
    )
    lines = text.splitlines()
    assert lines[0] == "Demand model demo:"
    assert lines[1].startswith("  ok   typical")
    assert lines[2].startswith("  FAIL single day")
    assert lines[-1] == "1 of 2 checks passed"


def test_cli_check_passes(capsys):
    assert main(["models", "--check", "gamma"]) == 0
    assert "5 of 5 checks passed" in capsys.readouterr().out


def test_cli_check_fails(capsys):
    registerModel("fixed", lambda rng, mean, sd, shape: np.full((4, 30), mean))
    assert main(["models", "--check", "fixed", "--json"]) == 1
    rows = json.loads(capsys.readouterr().out)
    assert [row["passed"] for row in rows].count(False) == 1


def test_cli_check_unknown(capsys):
    assert main(["models", "--check", "weibull"]) == 2
    assert "Unknown demand model" in capsys.readouterr().err
