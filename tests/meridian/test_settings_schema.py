"""Settings files are checked against the published JSON schema before loading."""

import json
from pathlib import Path

import pytest

from meridian.inputs import load_settings, validate_schema
from meridian.models import InputError

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["quickstart.json", "baseline.json", "higher_demand.json"])
def test_shipped_configs_match_schema(name):
    data = json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))
    validate_schema(data)
    assert load_settings(ROOT / "config" / name).horizon_days == data["horizon_days"]


def test_schema_version_accepted(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": "2026-10", "horizon_days": 30}))
    assert load_settings(path).horizon_days == 30


def test_unsupported_schema_version(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schema_version": "2025-01"}))
    with pytest.raises(InputError, match="schema_version"):
        load_settings(path)


def test_schema_lists_every_setting():
    from dataclasses import fields

    from meridian.models import Settings

    schema = json.loads((ROOT / "src/meridian/schema/settings.schema.json").read_text("utf-8"))
    assert {f.name for f in fields(Settings)} | {"schema_version"} == set(schema["properties"])


def test_default_settings_match_schema(settings):
    from dataclasses import asdict

    data = asdict(settings)
    data["stock_multipliers"] = list(data["stock_multipliers"])
    validate_schema(data)


def test_round_trip_with_version(tmp_path, settings):
    from dataclasses import asdict

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({**asdict(settings), "schema_version": "2026-10"}))
    assert load_settings(path) == settings
