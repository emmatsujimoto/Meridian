"""Demand models that generate synthetic daily demand, including third-party plugins.

Meridian ships several built-in demand models. Other packages can add their own by
declaring an entry point; plugins are discovered the first time a model is looked up.
A demand model is a callable that receives a seeded NumPy generator, the scaled daily mean
and standard deviation, and the (replications, days) shape, and returns an array of draws.
"""

import importlib
import os
from dataclasses import dataclass
from importlib.metadata import entry_points
from math import log1p, sqrt
from typing import Callable

import numpy as np

from meridian.models import InputError, identifier

ENTRY_POINT_GROUP = "meridian.demand_models"

Sampler = Callable[[np.random.Generator, float, float, tuple[int, int]], np.ndarray]


@dataclass(frozen=True)
class DemandModel:
    """A named sampler with a one-line description shown by ``meridian models``."""

    name: str
    sample: Sampler
    description: str = ""
    source: str = "built-in"


def _lognormal(rng: np.random.Generator, mean: float, sd: float, shape) -> np.ndarray:
    """Lognormal draws whose mean and standard deviation match the inputs."""
    if sd == 0:
        return np.full(shape, mean)
    sigma_sq = log1p((sd / mean) ** 2)
    return rng.lognormal(np.log(mean) - sigma_sq / 2, sqrt(sigma_sq), size=shape)


def _normal(rng: np.random.Generator, mean: float, sd: float, shape) -> np.ndarray:
    """Normal draws with negative values set to zero."""
    if sd == 0:
        return np.full(shape, mean)
    return np.maximum(rng.normal(mean, sd, size=shape), 0.0)


def _gamma(rng: np.random.Generator, mean: float, sd: float, shape) -> np.ndarray:
    """Gamma draws whose mean and standard deviation match the inputs."""
    if sd == 0:
        return np.full(shape, mean)
    return rng.gamma((mean / sd) ** 2, sd**2 / mean, size=shape)


def _poisson(rng: np.random.Generator, mean: float, sd: float, shape) -> np.ndarray:
    """Whole-kilogram Poisson draws; the standard deviation is the square root of the mean."""
    return rng.poisson(mean, size=shape).astype(float)


def _constant(rng: np.random.Generator, mean: float, sd: float, shape) -> np.ndarray:
    """The daily mean every day, ignoring the standard deviation."""
    return np.full(shape, mean)


BUILT_IN_MODELS = (
    DemandModel("lognormal", _lognormal, "Lognormal with matching mean and deviation (default)"),
    DemandModel("normal", _normal, "Normal with negative draws set to zero"),
    DemandModel("gamma", _gamma, "Gamma with matching mean and deviation"),
    DemandModel("poisson", _poisson, "Poisson counts of whole kilograms; ignores deviation"),
    DemandModel("constant", _constant, "Daily mean every day; useful for checks"),
)

_REGISTRY: dict[str, DemandModel] = {model.name: model for model in BUILT_IN_MODELS}
_PLUGINS_LOADED = False


def registerModel(
    name: str, sample: Sampler, description: str = "", source: str = "plugin"
) -> DemandModel:
    """Make a demand model available under ``name`` and return its registry entry."""
    identifier(name, "demand model name")
    if not callable(sample):
        raise InputError(f"Demand model {name} must be callable")
    model = DemandModel(name, sample, description or (sample.__doc__ or "").strip(), source)
    _REGISTRY[name] = model
    return model


def _from_entry_point(entry_point) -> DemandModel:
    """Turn a loaded entry point into a registry entry.

    An entry point may name a sampler function directly, or a ``DemandModel`` whose name is
    then replaced by the entry point's name so the two can never disagree.
    """
    loaded = entry_point.load()
    source = f"plugin {entry_point.value}"
    if isinstance(loaded, DemandModel):
        return registerModel(entry_point.name, loaded.sample, loaded.description, source)
    return registerModel(entry_point.name, loaded, "", source)


def load_plugins(force: bool = False) -> list[str]:
    """Discover installed plugins once; return the names that were registered."""
    global _PLUGINS_LOADED
    if _PLUGINS_LOADED and not force:
        return []
    _PLUGINS_LOADED = True
    loaded = []
    for entry_point in entry_points(group=ENTRY_POINT_GROUP):
        try:
            loaded.append(_from_entry_point(entry_point).name)
        except Exception:
            pass
    return loaded


def _load_legacy() -> list[str]:
    """Register models named in MERIDIAN_DEMAND_MODELS as ``name=module:function`` pairs."""
    names = []
    for item in os.environ.get("MERIDIAN_DEMAND_MODELS", "").split(","):
        if not item.strip():
            continue
        name, _, target = item.strip().partition("=")
        module_name, _, attribute = target.partition(":")
        module = importlib.import_module(module_name)
        registerModel(name, getattr(module, attribute), source=f"legacy {target}")
        names.append(name)
    return names


def getModel(name: str) -> DemandModel:
    """Return the demand model registered under ``name``."""
    load_plugins()
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY))
        raise InputError(f"Unknown demand model {name!r}; available: {known}") from None


def available_models() -> list[DemandModel]:
    """Every registered model, built-in models first, then plugins by name."""
    load_plugins()
    order = {model.name: index for index, model in enumerate(BUILT_IN_MODELS)}
    return sorted(
        _REGISTRY.values(), key=lambda model: (order.get(model.name, len(order)), model.name)
    )


def describe_models() -> list[dict]:
    """Model names, descriptions and sources for display or JSON output."""
    return [
        {"name": model.name, "description": model.description, "source": model.source}
        for model in available_models()
    ]


def unregister_model(name: str) -> None:
    """Remove a plugin model; built-in models cannot be removed."""
    if any(model.name == name for model in BUILT_IN_MODELS):
        raise InputError(f"Built-in demand model {name} cannot be removed")
    if name not in _REGISTRY:
        raise InputError(f"Unknown demand model {name!r}")
    del _REGISTRY[name]


def reset_registry() -> None:
    """Restore the built-in models only and forget which plugins were loaded."""
    global _PLUGINS_LOADED
    _REGISTRY.clear()
    _REGISTRY.update({model.name: model for model in BUILT_IN_MODELS})
    _PLUGINS_LOADED = False


def draw(
    model: DemandModel, rng: np.random.Generator, mean: float, sd: float, shape: tuple[int, int]
) -> np.ndarray:
    """Call a model and check its output before it reaches the simulator."""
    try:
        samples = np.asarray(model.sample(rng, mean, sd, shape), dtype=float)
    except (TypeError, ValueError) as exc:
        raise InputError(f"Demand model {model.name} failed: {exc}") from exc
    if samples.shape != shape:
        raise InputError(
            f"Demand model {model.name} returned shape {samples.shape}; expected {shape}"
        )
    if not np.all(np.isfinite(samples)):
        raise InputError("Demand settings overflow; reduce mean, deviation or multiplier")
    if np.any(samples < 0):
        raise InputError(f"Demand model {model.name} returned negative demand")
    return samples
