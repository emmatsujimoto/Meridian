"""Holiday calendars in synthetic demand."""

from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from meridian.demand import US_HOLIDAYS, demand_traces, holiday_dates, holiday_days
from meridian.models import InputError, Settings


def test_no_holidays_by_default(lane, settings):
    assert holiday_days(settings) == ()
    plain = demand_traces(lane, settings, "training")
    assert plain == demand_traces(lane, replace(settings, holidays=()), "training")


def test_us_calendar(settings):
    us = replace(settings, holiday_calendar="us")
    assert holiday_days(us) == US_HOLIDAYS
    assert len(US_HOLIDAYS) == 11


def test_extra_days_merged(settings):
    custom = replace(settings, holiday_calendar="us", holidays=(1, 200))
    assert holiday_days(custom) == tuple(sorted(set(US_HOLIDAYS) | {200}))


def test_only_holidays_change(lane, settings):
    longer = replace(settings, horizon_days=40)
    plain = np.array(demand_traces(lane, longer, "training"))
    with_holidays = np.array(demand_traces(lane, replace(longer, holidays=(10, 20)), "training"))
    changed = {int(day) for day in np.nonzero((plain != with_holidays).any(axis=0))[0]}
    assert len(changed) == 2
    assert (with_holidays <= plain).all()


def test_holidays_beyond_horizon_ignored(lane, settings):
    late = replace(settings, holidays=(300,))
    assert demand_traces(lane, late, "training") == demand_traces(lane, settings, "training")


def test_holidays_sorted_and_deduplicated():
    assert Settings(holidays=[45, 3, 45]).holidays == (3, 45)


@pytest.mark.parametrize("value", [[0], [367], [1.5], "1,2"])
def test_invalid_holidays(value):
    with pytest.raises(InputError):
        Settings(holidays=value)


def test_unknown_calendar():
    with pytest.raises(InputError, match="holiday_calendar"):
        Settings(holiday_calendar="uk")


def test_us_holiday_dates_2026():
    full_year = Settings(horizon_days=365, holiday_calendar="us")
    dates = holiday_dates(full_year)
    assert dates[0] == date(2026, 1, 1)
    assert date(2026, 7, 4) in dates
    assert date(2026, 11, 26) in dates
    assert dates[-1] == date(2026, 12, 25)


def test_holiday_dates_within_horizon():
    short = Settings(horizon_days=30, holiday_calendar="us")
    assert holiday_dates(short) == [date(2026, 1, 1), date(2026, 1, 19)]
