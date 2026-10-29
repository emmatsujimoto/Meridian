"""Small synthetic fixtures with independently checkable quantities."""

import pytest

from meridian import planning
from meridian.models import Lane, Settings


@pytest.fixture(autouse=True)
def _fresh_trace_cache():
    """Start every test with an empty demand-trace cache."""
    planning._TRACE_CACHE.clear()
    yield


@pytest.fixture
def lane():
    return Lane("Example", "nitrogen", 10, 2, 1, 20, 0.1, 2, 5, 0.5)


@pytest.fixture
def settings():
    return Settings(horizon_days=8, replications=2, stock_multipliers=(0.5, 1, 2))
