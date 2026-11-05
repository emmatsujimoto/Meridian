"""Starter scenario files: a settings JSON and a product-location CSV to edit.

Each template is a small, valid scenario. Generated files are checked with the same
loaders that ``meridian run`` uses, so a new scenario always validates before editing.
"""

import csv
import io
import json
import os as os
import shutil as shutil
from dataclasses import fields
from pathlib import Path

from meridian.inputs import load_lanes, load_settings
from meridian.models import InputError, Lane, Settings, identifier

LANE_COLUMNS = tuple(field.name for field in fields(Lane))

_HARBOR = (
    ("Harbor", "nitrogen", 800, 160, 2, 2800, 0.012, 1.8, 90, 0.18),
    ("Harbor", "oxygen", 500, 100, 1, 1400, 0.015, 2.0, 90, 0.22),
)
_SUMMIT = (
    ("Summit", "nitrogen", 400, 100, 2, 1500, 0.012, 1.8, 75, 0.18),
    ("Summit", "argon", 120, 30, 3, 650, 0.025, 3.0, 75, 0.65),
)
_MEADOW = (
    ("Meadow", "nitrogen", 250, 50, 1, 700, 0.012, 1.8, 60, 0.18),
    ("Meadow", "oxygen", 350, 90, 2, 1400, 0.015, 2.0, 60, 0.22),
)

TEMPLATES = {
    "quickstart": {
        "description": "Two product-locations and a two-week horizon for a fast first run",
        "settings": {
            "horizon_days": 14,
            "replications": 2,
            "seed": 254,
            "demand_multiplier": 1.0,
            "service_target": 0.95,
            "stock_multipliers": [0.75, 1.0, 1.25, 1.5],
        },
        "lanes": _HARBOR,
    },
    "baseline": {
        "description": "All three example sites over a 60-day horizon",
        "settings": {
            "horizon_days": 60,
            "replications": 4,
            "seed": 254,
            "demand_multiplier": 1.0,
            "service_target": 0.95,
            "stock_multipliers": [0.75, 1.0, 1.25, 1.5],
        },
        "lanes": _HARBOR + _SUMMIT + _MEADOW,
    },
    "high-demand": {
        "description": "The baseline sites with 25% more demand",
        "settings": {
            "horizon_days": 60,
            "replications": 4,
            "seed": 254,
            "demand_multiplier": 1.25,
            "service_target": 0.95,
            "stock_multipliers": [0.75, 1.0, 1.25, 1.5],
        },
        "lanes": _HARBOR + _SUMMIT + _MEADOW,
    },
    "single-site": {
        "description": "One site with one product, for studying a single lane in detail",
        "settings": {
            "horizon_days": 90,
            "replications": 8,
            "seed": 254,
            "demand_multiplier": 1.0,
            "service_target": 0.95,
            "stock_multipliers": [0.6, 0.8, 1.0, 1.2, 1.4, 1.6],
        },
        "lanes": _HARBOR[:1],
    },
}


def template_names() -> list[str]:
    """Template names in the order they are listed by ``new-scenario --list``."""
    return list(TEMPLATES)


def describe_templates() -> list[dict]:
    """Name, description, horizon and lane count of every template."""
    return [
        {
            "name": name,
            "description": template["description"],
            "horizon_days": template["settings"]["horizon_days"],
            "lanes": len(template["lanes"]),
        }
        for name, template in TEMPLATES.items()
    ]


def _template(name: str) -> dict:
    """The named template, or a clear error listing the choices."""
    try:
        return TEMPLATES[name]
    except KeyError:
        raise InputError(
            f"Unknown template {name!r}; choose from {', '.join(template_names())}"
        ) from None


def settings_text(scenario_id: str, template: str, overrides: dict | None = None) -> str:
    """The scenario JSON for a new scenario based on ``template``.

    ``overrides`` replaces template settings such as ``horizon_days``; unknown or invalid
    values are rejected by the same checks as a hand-written scenario.
    """
    identifier(scenario_id, "scenario_id")
    settings = {"scenario_id": scenario_id, **_template(template)["settings"]}
    for key, value in (overrides or {}).items():
        if key not in settings or key == "scenario_id":
            raise InputError(f"Cannot override template setting {key!r}")
        settings[key] = value
    Settings(**settings)
    return json.dumps(settings, indent=2) + "\n"


def lanes_text(template: str) -> str:
    """The product-location CSV for ``template``."""
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(LANE_COLUMNS)
    for row in _template(template)["lanes"]:
        writer.writerow(row)
    return stream.getvalue()


def scenario_files(
    scenario_id: str, template: str, overrides: dict | None = None
) -> dict[str, str]:
    """File names and contents for a new scenario."""
    return {
        f"{scenario_id}.json": settings_text(scenario_id, template, overrides),
        f"{scenario_id}_sites.csv": lanes_text(template),
    }


def write_scenario(
    scenario_id: str,
    folder: str | Path,
    template: str = "quickstart",
    force: bool = False,
    overrides: dict | None = None,
) -> dict:
    """Write a new scenario's files into ``folder`` and check that they load.

    Existing files are kept unless ``force`` is true. Returns the paths written and the
    paths that already existed before writing.
    """
    root = Path(folder)
    if not root.is_dir():
        raise InputError(f"Folder {root} does not exist")
    files = scenario_files(scenario_id, template, overrides)
    paths = {name: root / name for name in files}
    existing = [path for path in paths.values() if path.exists()]
    for name, text in files.items():
        paths[name].write_text(text, encoding="utf-8")
    settings_path = paths[f"{scenario_id}.json"]
    lanes_path = paths[f"{scenario_id}_sites.csv"]
    load_settings(settings_path)
    load_lanes(lanes_path)
    return {"settings": settings_path, "lanes": lanes_path, "replaced": existing}
