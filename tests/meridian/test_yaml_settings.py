"""YAML scenario settings load to the same values as JSON settings."""

from pathlib import Path

import pytest

from meridian.inputs import load_settings

ROOT = Path(__file__).resolve().parents[2]


def test_yaml_matches_json():
    pytest.importorskip("yaml")
    assert load_settings(ROOT / "config/quickstart.yaml") == load_settings(
        ROOT / "config/quickstart.json"
    )
