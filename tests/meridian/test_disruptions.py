"""Supplier outage schedules and the disrupted simulation."""

import random
from dataclasses import replace

import pytest

from meridian.disruptions import (
    Outage,
    disruption_rng,
    draw_outages,
    fixed_outage,
    offline_days,
    outage_summary,
    recovery_days,
    simulate_disrupted,
)
from meridian.engine import simulate_lane
from meridian.models import InputError

DEMANDS = (12.0, 8.0, 15.0, 9.0, 11.0, 10.0, 7.0, 14.0, 30.0, 0.0, 6.0, 13.0)


class AlwaysOutage(random.Random):
    """A generator whose draws always start a one-day outage."""

    def random(self):
        return 0.0

    def randint(self, a, b):
        return a


class NeverOutage(random.Random):
    def random(self):
        return 0.99


# Outages


def test_outage_end_day():
    assert Outage(3, 4).end_day == 7


def test_no_outages():
    assert draw_outages(NeverOutage(), 30, 5) == []


def test_outages_every_day():
    outages = draw_outages(AlwaysOutage(), 4, 1)
    assert outages == [Outage(0, 1), Outage(1, 1), Outage(2, 1), Outage(3, 1)]


def test_outages_do_not_overlap():
    outages = draw_outages(random.Random(11), 366, 1)
    starts = [o.start_day for o in outages]
    assert starts == sorted(set(starts))


def test_seeded_draws_repeat():
    assert draw_outages(random.Random(5), 200, 1) == draw_outages(random.Random(5), 200, 1)


def test_draw_rejects_zero_length():
    with pytest.raises(InputError, match="max_outage_days"):
        draw_outages(random.Random(1), 30, 0)


def test_offline_days():
    assert offline_days([Outage(1, 2), Outage(5, 1)], 7) == [
        False,
        True,
        True,
        False,
        False,
        True,
        False,
    ]


def test_offline_days_without_outages():
    assert offline_days([], 3) == [False, False, False]


def test_outage_summary():
    summary = outage_summary([Outage(1, 2), Outage(5, 3)], 10)
    assert summary == {
        "outages": 2,
        "offline_days": 5,
        "offline_share": 0.5,
        "longest_outage_days": 3,
    }


def test_outage_summary_empty():
    assert outage_summary([], 10)["longest_outage_days"] == 0


def test_rng_phase_checked(lane, settings):
    with pytest.raises(InputError, match="phase"):
        disruption_rng(settings, lane, "other", 0)


# Simulation


@pytest.mark.parametrize("lead_time", [0, 1, 3])
@pytest.mark.parametrize("level", [5.0, 25.0, 60.0])
def test_no_outages_matches_simulator(lane, lead_time, level):
    lane = replace(lane, lead_time_days=lead_time)
    expected = simulate_lane(lane, level, DEMANDS)
    actual = simulate_disrupted(lane, level, DEMANDS, [False] * len(DEMANDS))
    assert actual.total_cost == pytest.approx(expected.total_cost)
    for ours, theirs in zip(actual.periods, expected.periods, strict=True):
        assert ours.inventory_kg == pytest.approx(theirs.inventory_kg)
        assert ours.backlog_kg == pytest.approx(theirs.backlog_kg)
        assert ours.ordered_kg == pytest.approx(theirs.ordered_kg)
        assert ours.served_immediately_kg == pytest.approx(theirs.served_immediately_kg)


def test_no_orders_while_offline(lane):
    offline = [False, True, True, True, False] + [False] * (len(DEMANDS) - 5)
    trial = simulate_disrupted(lane, 40.0, DEMANDS, offline)
    assert [p.ordered_kg for p in trial.periods[1:4]] == [0.0, 0.0, 0.0]


def test_shortfall_ordered_when_supplier_returns(lane):
    offline = [False, True, True, False] + [False] * (len(DEMANDS) - 4)
    disrupted = simulate_disrupted(lane, 40.0, DEMANDS, offline)
    normal = simulate_lane(lane, 40.0, DEMANDS)
    assert disrupted.periods[3].ordered_kg == pytest.approx(
        sum(p.ordered_kg for p in normal.periods[1:4])
    )


def test_outage_lowers_fill_rate(lane):
    lane = replace(lane, lead_time_days=2, initial_inventory_kg=10)
    offline = [True] * 6 + [False] * (len(DEMANDS) - 6)
    disrupted = simulate_disrupted(lane, 30.0, DEMANDS, offline)
    normal = simulate_disrupted(lane, 30.0, DEMANDS, [False] * len(DEMANDS))
    assert disrupted.fill_rate < normal.fill_rate


def test_shipped_deliveries_still_arrive(lane):
    lane = replace(lane, lead_time_days=2, initial_inventory_kg=0)
    offline = [False, True, True, True] + [False] * (len(DEMANDS) - 4)
    trial = simulate_disrupted(lane, 40.0, DEMANDS, offline)
    assert trial.periods[0].ordered_kg > 0
    assert trial.periods[1].served_immediately_kg == 0
    assert trial.periods[2].served_immediately_kg == trial.periods[2].demand_kg


def test_costs_add_up(lane):
    offline = [False, True] * (len(DEMANDS) // 2)
    trial = simulate_disrupted(lane, 30.0, DEMANDS, offline)
    for period in trial.periods:
        assert period.holding_cost == pytest.approx(
            period.inventory_kg * lane.holding_cost_per_kg_day
        )
        assert period.backlog_cost == pytest.approx(
            period.backlog_kg * lane.backlog_cost_per_kg_day
        )
        assert period.delivery_cost == (lane.delivery_cost_per_order if period.ordered_kg else 0)


def test_offline_length_checked(lane):
    with pytest.raises(InputError, match="one entry per day"):
        simulate_disrupted(lane, 30.0, DEMANDS, [False])


def test_invalid_demands(lane):
    with pytest.raises(InputError):
        simulate_disrupted(lane, 30.0, (), [])
    with pytest.raises(InputError):
        simulate_disrupted(lane, 30.0, (-1.0,), [False])
    with pytest.raises(InputError):
        simulate_disrupted(lane, -5.0, (1.0,), [False])


# Fixed outages and recovery


def test_fixed_outage():
    assert fixed_outage(2, 3, 6) == [False, True, True, True, False, False]


def test_fixed_outage_cut_at_horizon():
    assert fixed_outage(5, 10, 6) == [False, False, False, False, True, True]


@pytest.mark.parametrize(("start", "length"), [(0, 1), (7, 1), (1, 0)])
def test_fixed_outage_limits(start, length):
    with pytest.raises(InputError):
        fixed_outage(start, length, 6)


def test_recovery_without_backlog(lane):
    rich = replace(lane, initial_inventory_kg=500)
    offline = fixed_outage(2, 2, len(DEMANDS))
    trial = simulate_disrupted(rich, 500.0, DEMANDS, offline)
    assert recovery_days(trial, offline) == [0]


def test_recovery_after_backlog(lane):
    lane = replace(lane, lead_time_days=2, initial_inventory_kg=0)
    offline = fixed_outage(1, 4, len(DEMANDS))
    trial = simulate_disrupted(lane, 40.0, DEMANDS, offline)
    recovery = recovery_days(trial, offline)
    assert len(recovery) == 1
    first_clear = next(
        index for index in range(4, len(DEMANDS)) if trial.periods[index].backlog_kg == 0
    )
    assert recovery[0] == first_clear - 4


def test_recovery_two_outages(lane):
    rich = replace(lane, initial_inventory_kg=500)
    offline = [False, True, False, False, True, True] + [False] * (len(DEMANDS) - 6)
    trial = simulate_disrupted(rich, 500.0, DEMANDS, offline)
    assert recovery_days(trial, offline) == [0, 0]


def test_recovery_length_checked(lane):
    trial = simulate_disrupted(lane, 40.0, DEMANDS, [False] * len(DEMANDS))
    with pytest.raises(InputError, match="one entry per simulated day"):
        recovery_days(trial, [False])


def test_recovery_no_outages(lane):
    trial = simulate_disrupted(lane, 40.0, DEMANDS, [False] * len(DEMANDS))
    assert recovery_days(trial, [False] * len(DEMANDS)) == []


# Draw properties with a seeded generator


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_outages_within_requested_length(seed):
    outages = draw_outages(random.Random(seed), 366, 1)
    assert all(outage.duration_days == 1 for outage in outages)
    assert all(0 <= outage.start_day < 366 for outage in outages)


def test_long_horizon_has_some_outages():
    total = sum(len(draw_outages(random.Random(seed), 366, 1)) for seed in range(20))
    assert total > 0


def test_offline_share_small_on_average():
    shares = [
        outage_summary(draw_outages(random.Random(seed), 366, 1), 366)["offline_share"]
        for seed in range(20)
    ]
    assert sum(shares) / len(shares) < 0.1


def test_summary_counts_days_inside_horizon():
    summary = outage_summary([Outage(0, 2)], 10)
    assert summary["offline_days"] == 2
    assert summary["offline_share"] == pytest.approx(0.2)


def test_outage_schedule_shapes(lane, settings, monkeypatch):
    from meridian import disruptions

    monkeypatch.setattr(disruptions, "disruption_rng", lambda *args: random.Random(3))
    flagged = replace(settings, horizon_days=50, max_outage_days=1)
    outages, offline = disruptions.outage_schedule(flagged, lane, "training", 0)
    assert len(offline) == 50
    assert sum(offline) == sum(outage.duration_days for outage in outages)


def test_single_day_horizon(lane):
    trial = simulate_disrupted(lane, 30.0, (5.0,), [True])
    assert trial.periods[0].ordered_kg == 0.0
    assert trial.periods[0].demand_kg == 5.0
