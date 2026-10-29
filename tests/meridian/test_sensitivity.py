"""Holding-cost sensitivity sweep output structure."""

import pytest

from meridian.models import InputError
from meridian.planning import sensitivity_sweep


def test_sweep_reports_each_lane(lane, settings):
    sweep = sensitivity_sweep((lane,), settings, (0.5, 1.0, 2.0))
    assert set(sweep) == {lane.key}
    assert all(row["base_stock_kg"] > 0 for row in sweep[lane.key])


def test_sweep_requires_multipliers(lane, settings):
    with pytest.raises(InputError):
        sensitivity_sweep((lane,), settings, ())
