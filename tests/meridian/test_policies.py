"""The periodic-review (R, s, S) simulation."""

from dataclasses import replace

import pytest

from meridian.engine import simulate_lane
from meridian.models import InputError
from meridian.policies import (
    days_between_orders,
    is_review_day,
    mean_order_kg,
    order_count,
    policy_diagnostics,
    review_days,
    round_to_pack,
    simulate_periodic,
)

DEMANDS = (12.0, 8.0, 15.0, 9.0, 11.0, 10.0, 7.0, 14.0, 30.0, 0.0, 6.0, 13.0, 9.0, 10.0)


# Helpers


def test_round_to_pack_without_pack_size():
    assert round_to_pack(123.4, 0.0) == 123.4


@pytest.mark.parametrize(("quantity", "pack"), [(1000.0, 250.0), (750.0, 250.0), (40.0, 20.0)])
def test_round_to_pack_exact_multiples(quantity, pack):
    assert round_to_pack(quantity, pack) == quantity


@pytest.mark.parametrize(
    ("day", "period", "offset", "expected"),
    [(0, 7, 0, True), (7, 7, 0, True), (6, 7, 0, False), (2, 7, 2, True), (1, 7, 2, False)],
)
def test_is_review_day(day, period, offset, expected):
    assert is_review_day(day, period, offset) is expected


def test_review_days():
    assert review_days(15, 7) == [1, 8, 15]
    assert review_days(15, 7, offset_days=3) == [4, 11]
    assert review_days(3, 1) == [1, 2, 3]


# Equivalence with base stock


@pytest.mark.parametrize("lead_time", [0, 1, 3])
@pytest.mark.parametrize("level", [5.0, 25.0, 60.0])
def test_daily_review_with_s_equal_to_s_matches_base_stock(lane, lead_time, level):
    lane = replace(lane, lead_time_days=lead_time)
    expected = simulate_lane(lane, level, DEMANDS)
    actual = simulate_periodic(lane, 1, level, level, DEMANDS)
    assert actual.total_cost == pytest.approx(expected.total_cost)
    assert actual.fill_rate == pytest.approx(expected.fill_rate)
    for ours, theirs in zip(actual.periods, expected.periods, strict=True):
        assert ours.inventory_kg == pytest.approx(theirs.inventory_kg)
        assert ours.backlog_kg == pytest.approx(theirs.backlog_kg)
        assert ours.ordered_kg == pytest.approx(theirs.ordered_kg)
        assert ours.served_immediately_kg == pytest.approx(theirs.served_immediately_kg)


# Ordering behaviour


def test_orders_only_on_review_days(lane):
    trial = simulate_periodic(lane, 5, 30.0, 60.0, DEMANDS)
    reviews = set(review_days(len(DEMANDS), 5))
    assert all(p.day in reviews for p in trial.periods if p.ordered_kg > 0)


def test_order_brings_position_to_level(lane):
    lane = replace(lane, lead_time_days=2, initial_inventory_kg=10)
    trial = simulate_periodic(lane, 7, 40.0, 80.0, DEMANDS)
    first = trial.periods[0]
    expected_position = lane.initial_inventory_kg - first.demand_kg
    assert first.ordered_kg == pytest.approx(80.0 - expected_position)


def test_no_order_when_position_well_above_s(lane):
    rich = replace(lane, initial_inventory_kg=500)
    trial = simulate_periodic(rich, 7, 50.0, 100.0, DEMANDS)
    assert order_count(trial) == 0
    assert trial.fill_rate == 1.0


def test_order_arrives_after_lead_time(lane):
    lane = replace(lane, lead_time_days=3, initial_inventory_kg=0)
    trial = simulate_periodic(lane, 7, 20.0, 100.0, (5.0,) * 10)
    ordered = trial.periods[0].ordered_kg
    assert ordered > 0
    assert trial.periods[2].inventory_kg == 0
    assert trial.periods[3].inventory_kg == pytest.approx(ordered - 4 * 5.0)


def test_zero_lead_time_serves_same_day(lane):
    lane = replace(lane, lead_time_days=0, initial_inventory_kg=0)
    trial = simulate_periodic(lane, 1, 20.0, 40.0, DEMANDS)
    assert trial.fill_rate == 1.0


def test_offset_moves_first_review(lane):
    lane = replace(lane, initial_inventory_kg=0)
    trial = simulate_periodic(lane, 7, 20.0, 60.0, DEMANDS, offset_days=3)
    assert trial.periods[0].ordered_kg == 0
    assert trial.periods[3].ordered_kg > 0


def test_longer_review_period_orders_less_often(lane):
    weekly = simulate_periodic(lane, 7, 30.0, 80.0, DEMANDS)
    daily = simulate_periodic(lane, 1, 30.0, 80.0, DEMANDS)
    assert order_count(weekly) <= order_count(daily)


def test_costs_add_up(lane):
    trial = simulate_periodic(lane, 3, 25.0, 60.0, DEMANDS)
    for period in trial.periods:
        assert period.holding_cost == pytest.approx(
            period.inventory_kg * lane.holding_cost_per_kg_day
        )
        assert period.backlog_cost == pytest.approx(
            period.backlog_kg * lane.backlog_cost_per_kg_day
        )
        assert period.purchase_cost == pytest.approx(period.ordered_kg * lane.purchase_cost_per_kg)
        expected_delivery = lane.delivery_cost_per_order if period.ordered_kg else 0.0
        assert period.delivery_cost == expected_delivery


def test_trial_records_order_up_to_level(lane):
    trial = simulate_periodic(lane, 7, 25.0, 60.0, DEMANDS)
    assert trial.base_stock_kg == 60.0
    assert trial.lane_key == lane.key
    assert [p.day for p in trial.periods] == list(range(1, len(DEMANDS) + 1))


def test_backlog_carried_and_cleared(lane):
    lane = replace(lane, lead_time_days=2, initial_inventory_kg=0)
    trial = simulate_periodic(lane, 7, 30.0, 70.0, (10.0,) * 8)
    assert trial.periods[0].backlog_kg == 10.0
    assert trial.periods[1].backlog_kg == 20.0
    assert trial.periods[2].backlog_kg == 0.0


def test_order_statistics(lane):
    lane = replace(lane, initial_inventory_kg=0)
    trial = simulate_periodic(lane, 7, 30.0, 70.0, DEMANDS)
    orders = [p.ordered_kg for p in trial.periods if p.ordered_kg > 0]
    assert order_count(trial) == len(orders)
    assert mean_order_kg(trial) == pytest.approx(sum(orders) / len(orders))


def test_mean_order_without_orders(lane):
    rich = replace(lane, initial_inventory_kg=500)
    assert mean_order_kg(simulate_periodic(rich, 7, 10.0, 20.0, DEMANDS)) == 0.0


def test_deterministic(lane):
    first = simulate_periodic(lane, 4, 20.0, 50.0, DEMANDS)
    assert first == simulate_periodic(lane, 4, 20.0, 50.0, DEMANDS)


# Validation


@pytest.mark.parametrize("period", [0, 91, 2.5, "7"])
def test_invalid_review_period(lane, period):
    with pytest.raises(InputError, match="Review period"):
        simulate_periodic(lane, period, 10.0, 20.0, DEMANDS)


def test_reorder_point_above_level(lane):
    with pytest.raises(InputError, match="must not exceed"):
        simulate_periodic(lane, 7, 30.0, 20.0, DEMANDS)


@pytest.mark.parametrize("offset", [-1, 7, 1.5])
def test_invalid_offset(lane, offset):
    with pytest.raises(InputError, match="offset_days"):
        simulate_periodic(lane, 7, 10.0, 20.0, DEMANDS, offset_days=offset)


def test_invalid_demands(lane):
    with pytest.raises(InputError):
        simulate_periodic(lane, 7, 10.0, 20.0, ())
    with pytest.raises(InputError):
        simulate_periodic(lane, 7, 10.0, 20.0, (1.0,) * 367)
    with pytest.raises(InputError):
        simulate_periodic(lane, 7, 10.0, 20.0, (1.0, -2.0))


def test_negative_levels_rejected(lane):
    with pytest.raises(InputError):
        simulate_periodic(lane, 7, -1.0, 20.0, DEMANDS)


def test_negative_pack_size_rejected(lane):
    with pytest.raises(InputError):
        simulate_periodic(lane, 7, 10.0, 20.0, DEMANDS, pack_size_kg=-5)


# Diagnostics


def test_days_between_orders(lane):
    lane = replace(lane, initial_inventory_kg=0)
    trial = simulate_periodic(lane, 7, 30.0, 70.0, DEMANDS)
    order_days = [p.day for p in trial.periods if p.ordered_kg > 0]
    gaps = days_between_orders(trial)
    assert len(gaps) == max(0, len(order_days) - 1)
    assert all(gap % 7 == 0 for gap in gaps)


def test_days_between_orders_none(lane):
    rich = replace(lane, initial_inventory_kg=500)
    assert days_between_orders(simulate_periodic(rich, 7, 10.0, 20.0, DEMANDS)) == []


def test_policy_diagnostics(lane):
    lane = replace(lane, initial_inventory_kg=0)
    trial = simulate_periodic(lane, 7, 30.0, 70.0, DEMANDS)
    result = policy_diagnostics(trial, 7)
    assert result["reviews"] == 2
    assert result["orders"] + result["skipped_reviews"] == result["reviews"]
    assert result["orders"] == order_count(trial)
    assert result["peak_inventory_kg"] == max(p.inventory_kg for p in trial.periods)
    assert result["stockout_days"] == sum(p.backlog_kg > 0 for p in trial.periods)


def test_policy_diagnostics_without_orders(lane):
    rich = replace(lane, initial_inventory_kg=500)
    result = policy_diagnostics(simulate_periodic(rich, 7, 10.0, 20.0, DEMANDS), 7)
    assert result["orders"] == 0
    assert result["skipped_reviews"] == 2
    assert result["mean_days_between_orders"] is None
    assert result["mean_order_kg"] == 0.0


@pytest.mark.parametrize("period", [2, 5, 10])
def test_review_count_matches_horizon(lane, period):
    rich = replace(lane, initial_inventory_kg=500)
    trial = simulate_periodic(rich, period, 10.0, 20.0, DEMANDS)
    expected = len(range(0, len(DEMANDS), period))
    assert policy_diagnostics(trial, period)["reviews"] == expected


def test_orders_charged_even_if_arriving_after_horizon(lane):
    lane = replace(lane, lead_time_days=5, initial_inventory_kg=0)
    trial = simulate_periodic(lane, 2, 60.0, 60.0, (5.0,) * 3)
    late = trial.periods[2]
    assert late.ordered_kg > 0
    assert late.purchase_cost == pytest.approx(late.ordered_kg * lane.purchase_cost_per_kg)
    assert late.delivery_cost == lane.delivery_cost_per_order
