"""Built-in demand models and their use in scenario runs."""

import json
from dataclasses import replace

import numpy as np
import pytest

from meridian import plugins
from meridian.cli import main
from meridian.demand import demand_traces
from meridian.models import InputError, Settings
from meridian.planning import run_scenario
from meridian.plugins import getModel, registerModel, reset_registry

SHAPE = (200, 365)


@pytest.fixture(autouse=True)
def clean_registry(monkeypatch):
    monkeypatch.setattr(plugins, "entry_points", lambda group: [])
    reset_registry()
    yield
    reset_registry()


def _sample(name, mean=100.0, sd=20.0, seed=7):
    model = getModel(name)
    return plugins.draw(model, np.random.default_rng(seed), mean, sd, SHAPE)


@pytest.mark.parametrize("name", ["lognormal", "gamma"])
def test_moment_matching_models(name):
    samples = _sample(name)
    assert samples.mean() == pytest.approx(100.0, rel=0.01)
    assert samples.std() == pytest.approx(20.0, rel=0.03)
    assert samples.min() > 0


def test_normal_clipped_at_zero():
    samples = _sample("normal", mean=10.0, sd=20.0)
    assert samples.min() == 0.0
    assert samples.mean() > 10.0


def test_normal_moments_when_rarely_clipped():
    samples = _sample("normal")
    assert samples.mean() == pytest.approx(100.0, rel=0.01)


def test_poisson_whole_kilograms():
    samples = _sample("poisson", mean=12.0)
    assert np.all(samples == np.round(samples))
    assert samples.var() == pytest.approx(12.0, rel=0.05)


def test_constant_ignores_deviation():
    assert np.all(_sample("constant", mean=55.0, sd=30.0) == 55.0)


@pytest.mark.parametrize("name", ["lognormal", "normal", "gamma"])
def test_zero_deviation_is_constant(name):
    assert np.all(_sample(name, mean=40.0, sd=0.0) == 40.0)


def test_same_seed_same_draws():
    assert np.array_equal(_sample("gamma", seed=3), _sample("gamma", seed=3))


def test_settings_default_model():
    assert Settings().demand_model == "lognormal"


def test_settings_reject_unsafe_model_name():
    with pytest.raises(InputError, match="demand_model"):
        Settings(demand_model="os.system")


def test_traces_use_configured_model(lane, settings):
    traces = demand_traces(lane, replace(settings, demand_model="constant"), "training")
    assert {value for row in traces for value in row} == {lane.daily_mean_kg}


def test_default_traces_unchanged_by_registry(lane, settings):
    explicit = demand_traces(lane, replace(settings, demand_model="lognormal"), "training")
    assert explicit == demand_traces(lane, settings, "training")


def test_traces_unknown_model(lane, settings):
    with pytest.raises(InputError, match="Unknown demand model"):
        demand_traces(lane, replace(settings, demand_model="weibull"), "training")


def test_plugin_model_in_scenario(lane, settings):
    registerModel("flat", lambda rng, mean, sd, shape: np.full(shape, mean * 0.5))
    result = run_scenario((lane,), replace(settings, demand_model="flat"))
    trial = result.results[0].validation_trials[0]
    assert {period.demand_kg for period in trial.periods} == {lane.daily_mean_kg * 0.5}


def test_multiplier_applies_to_plugin(lane, settings):
    registerModel("flat", lambda rng, mean, sd, shape: np.full(shape, mean))
    traces = demand_traces(
        lane, replace(settings, demand_model="flat", demand_multiplier=3), "validation"
    )
    assert traces[0][0] == lane.daily_mean_kg * 3


def _config(tmp_path, **values):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"horizon_days": 5, "replications": 1, **values}))
    return str(path)


def test_cli_validate_reports_model(tmp_path, capsys):
    config = _config(tmp_path, demand_model="gamma")
    assert main(["validate", "--data", "data/synthetic_sites.csv", "--config", config]) == 0
    assert "demand model=gamma (built-in)" in capsys.readouterr().out


def test_cli_validate_unknown_model(tmp_path, capsys):
    config = _config(tmp_path, demand_model="weibull")
    assert main(["validate", "--data", "data/synthetic_sites.csv", "--config", config]) == 2
    assert "Unknown demand model 'weibull'" in capsys.readouterr().err
