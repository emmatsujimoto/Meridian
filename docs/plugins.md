# Demand model plugins

Meridian draws synthetic daily demand from a *demand model*. The default lognormal model
matches each product-location's configured mean and standard deviation. Other built-in
models are available, and separate Python packages can add their own without changing
Meridian's source code.

## Choosing a model

Set `demand_model` in the scenario JSON:

```json
{
  "scenario_id": "gamma_check",
  "horizon_days": 90,
  "replications": 8,
  "demand_model": "gamma"
}
```

When `demand_model` is omitted the lognormal model is used, so existing configuration
files give the same results as before.

`meridian validate` reports the model a scenario will use and fails with exit status 2 if
it is not installed:

```bash
python -m meridian validate --data data/synthetic_sites.csv --config config/gamma.json
# Valid: 12 product-location rows; scenario=gamma_check; demand model=gamma (built-in)
```

To see every model that is available, including plugins:

```bash
python -m meridian models
python -m meridian models --json
```

## Built-in models

| Name | Distribution | Uses standard deviation | Notes |
|---|---|---|---|
| `lognormal` | Lognormal | Yes | Default; mean and deviation match the inputs |
| `normal` | Normal, negative draws set to zero | Yes | Clipping raises the mean slightly when the deviation is large |
| `gamma` | Gamma | Yes | Mean and deviation match the inputs |
| `poisson` | Poisson | No | Whole kilograms; variance equals the mean |
| `uniform` | Uniform, negative draws set to zero | Yes | Bounded demand; mean and deviation match the inputs until clipping applies |
| `constant` | None | No | The daily mean every day; useful for checking costs by hand |

For every model the scenario's `demand_multiplier` scales both the mean and the standard
deviation before the model is called. A standard deviation of zero gives constant demand
for the lognormal, normal and gamma models.

Draws are seeded from the scenario seed, the product-location and the phase (training or
validation), so a model always produces the same demand for the same inputs.

## Previewing a model

Before running a full scenario, `meridian models --preview` shows what a model's draws look
like for a single product-location. It draws one year of demand for 20 replications from a
fixed seed and prints the mean, standard deviation, 5th/50th/95th percentiles and the share
of days with zero demand:

```bash
python -m meridian models --preview gamma lognormal --mean 120 --sd 45
```

```text
model               mean        sd       p05       p50       p95    zero
--------------------------------------------------------------------------
gamma              120.1      44.9      56.4     112.6     202.8    0.0%
lognormal          119.8      45.2      60.9     112.2     203.6    0.0%
```

With no model names, every available model is previewed, including plugins. Add `--json`
for machine-readable output and `--days` to change the number of days drawn (1-366).

Preview numbers come from a fixed seed, not from a scenario's seed, so they are the same on
every run and do not match any particular scenario's demand exactly.

| Option | Default | Meaning |
|---|---|---|
| `--mean` | 100 | Daily mean demand in kg |
| `--sd` | 20 | Daily standard deviation in kg |
| `--days` | 365 | Days drawn per replication |
| `--json` | off | Print a JSON list instead of a table |

A preview is a quick way to check a plugin: the mean and deviation should be close to the
values requested unless the model deliberately changes them, and `zero` shows how often the
model produces days without demand.

## Writing a plugin

A plugin is an ordinary Python package that provides a *sampler* function:

```python
import numpy as np


def weekly_peaks(rng: np.random.Generator, mean: float, sd: float, shape: tuple[int, int]):
    """Normal demand with double volume on the first day of every week."""
    samples = np.maximum(rng.normal(mean, sd, size=shape), 0.0)
    samples[:, ::7] *= 2
    return samples
```

The sampler receives:

| Argument | Meaning |
|---|---|
| `rng` | A seeded `numpy.random.Generator`; use it for every random draw |
| `mean` | Daily mean demand in kg, already scaled by `demand_multiplier` |
| `sd` | Daily standard deviation in kg, already scaled by `demand_multiplier` |
| `shape` | `(replications, horizon_days)` |

It must return an array (or nested lists) of exactly `shape`. Meridian rejects output that
has the wrong shape, contains infinite or missing values, or contains negative demand. Do
not create your own random generator: results would no longer be reproducible.

The sampler's docstring becomes the description shown by `meridian models`.

### Registering the plugin

Declare an entry point in the plugin package's `pyproject.toml`. The entry point's name is
the value used for `demand_model`:

```toml
[project.entry-points."meridian.models"]
weekly = "weekly_demand:weekly_peaks"
```

After `pip install` of the plugin package, `meridian models` lists `weekly` with its source,
and a scenario can use it with `"demand_model": "weekly"`.

An entry point may also point at a `meridian.plugins.DemandModel` object when the plugin
wants to set its own description:

```python
from meridian.plugins import DemandModel

WEEKLY = DemandModel("weekly", weekly_peaks, "Weekly peaks on Mondays")
```

The entry point's name is always used, whatever name the object was created with.

### Registering in code

Notebooks and tests can register a sampler directly:

```python
from meridian.plugins import getModel, registerModel

registerModel("weekly", weekly_peaks, "Weekly peaks on Mondays")
assert getModel("weekly").source == "plugin"
```

`unregister_model(name)` removes a model registered this way; built-in models cannot be
removed. `reset_registry()` restores the built-in models and forgets which plugins were
discovered, which keeps tests independent of each other.

## How plugins are discovered

Plugins are discovered the first time a model is looked up, for example when a scenario
starts or `meridian models` runs. Discovery happens once per process; call
`load_plugins(force=True)` to look again after installing a package in a running notebook.

Model names follow the same rules as `scenario_id`: they start with a letter and contain
up to 64 letters, digits, hyphens or underscores.

## Reproducibility and reports

`summary.json` records the scenario settings, including `demand_model`, as part of the input
fingerprint. Two runs with different models therefore have different `input_sha256` values
and are never mistaken for the same scenario.

A run that used a plugin can only be repeated on a machine where the same plugin version is
installed. Record the plugin package and version alongside the results when sharing them.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Unknown demand model 'weekly'; available: ...` | The plugin package is not installed in the active environment, or its entry point name differs |
| `Demand model weekly returned shape (...)` | The sampler ignored the `shape` argument |
| `Demand model weekly returned negative demand` | The sampler needs to clip at zero, as the `normal` model does |
| `Demand model weekly failed: ...` | The sampler raised `TypeError` or `ValueError` for these inputs |
| Results change on every run | The sampler creates its own generator instead of using `rng` |
