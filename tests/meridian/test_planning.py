"""Analytical checks, deterministic event accounting, and reproducible scenarios."""

from dataclasses import replace
from math import sqrt

import numpy as np
import pytest

from meridian.demand import demand_traces
from meridian.engine import simulate_lane
from meridian.models import Candidate, InputError
from meridian.planning import (
    candidate_levels,
    choose_candidate,
    deterministic_plan,
    eoq_benchmark,
    optimize_lane,
    run_scenario,
)


def test_demand_reproducibility(lane, settings):
    a = demand_traces(lane, settings, "training")
    assert a == demand_traces(lane, settings, "training")
    assert a != demand_traces(lane, settings, "validation")
    assert all(x >= 0 for row in a for x in row)


def test_demand_multiplier_scales_same_draws(lane, settings):
    a = demand_traces(lane, settings, "training")
    b = demand_traces(lane, replace(settings, demand_multiplier=2), "training")
    assert np.asarray(b) == pytest.approx(np.asarray(a) * 2)


def test_zero_sd_deterministic(lane, settings):
    traces = demand_traces(replace(lane, daily_sd_kg=0), settings, "training")
    assert all(x == lane.daily_mean_kg for row in traces for x in row)


def test_invalid_phase(lane, settings):
    with pytest.raises(InputError):
        demand_traces(lane, settings, "other")


def test_same_day_inventory_balance_and_cost(lane):
    lane = replace(lane, lead_time_days=0, initial_inventory_kg=20)
    trial = simulate_lane(lane, 20, (10, 10, 10))
    assert trial.fill_rate == pytest.approx(1)
    for p in trial.periods:
        assert p.inventory_kg == pytest.approx(20)
        assert p.backlog_kg == 0
        assert p.ordered_kg == pytest.approx(10)
        assert p.holding_cost == pytest.approx(2)
        assert p.delivery_cost == pytest.approx(5)
        assert p.purchase_cost == pytest.approx(5)
    assert trial.total_cost == pytest.approx(36)


def test_initial_stock_serves_without_orders(lane):
    trial = simulate_lane(replace(lane, initial_inventory_kg=100), 0, (10, 20))
    assert trial.periods[-1].inventory_kg == pytest.approx(70)
    assert all(p.ordered_kg == 0 for p in trial.periods)
    assert all(p.delivery_cost == 0 for p in trial.periods)
    assert trial.fill_rate == 1


def test_backlog_cost_and_mass_balance(lane):
    lane = replace(lane, lead_time_days=2, initial_inventory_kg=0)
    trial = simulate_lane(lane, 0, (10, 10))
    assert trial.periods[0].backlog_kg == 10
    assert trial.periods[1].backlog_kg == 20
    assert sum(p.backlog_cost for p in trial.periods) == pytest.approx(60)
    assert trial.fill_rate == 0


def test_zero_demand_fill_rate(lane):
    assert simulate_lane(lane, 0, (0, 0)).fill_rate == 1


def test_rng_state_is_preserved(lane):
    np.random.seed(42)
    before = np.random.get_state()
    simulate_lane(lane, 20, (10, 10))
    after = np.random.get_state()
    assert before[0] == after[0]
    assert np.array_equal(before[1], after[1])
    assert before[2:] == after[2:]


@pytest.mark.parametrize("demands", [(), (-1,), (float("nan"),), (1,) * 367])
def test_simulation_rejects_invalid_demands(lane, demands):
    with pytest.raises(InputError):
        simulate_lane(lane, 20, demands)


def test_eoq_against_closed_form(lane):
    result = eoq_benchmark(lane)
    q = sqrt(2 * lane.delivery_cost_per_order * lane.daily_mean_kg / lane.holding_cost_per_kg_day)
    assert result["quantity_kg"] == pytest.approx(q)
    expected = (
        lane.delivery_cost_per_order * lane.daily_mean_kg / q + lane.holding_cost_per_kg_day * q / 2
    )
    assert result["daily_cycle_cost"] == pytest.approx(expected)


def test_eoq_zero_setup(lane):
    assert eoq_benchmark(replace(lane, delivery_cost_per_order=0))["daily_cycle_cost"] == 0


def test_wagner_whitin_against_enumeration(lane):
    demands = (10, 20, 5)
    plan = deterministic_plan(lane, demands)
    # Exhaustively enumerate all ways to partition three days into order batches.
    costs = []
    for first_break in (False, True):
        for second_break in (False, True):
            starts = [0] + ([1] if first_break else []) + ([2] if second_break else [])
            cost = 0
            for begin, end in zip(starts, starts[1:] + [3]):
                cost += lane.delivery_cost_per_order
                cost += sum(demands[t] * lane.purchase_cost_per_kg for t in range(begin, end))
                cost += sum(
                    demands[t] * (t - begin) * lane.holding_cost_per_kg_day
                    for t in range(begin, end)
                )
            costs.append(cost)
    assert plan["total_cost"] == pytest.approx(min(costs))
    assert sum(plan["order_quantities_kg"]) == sum(demands)


def test_wagner_whitin_zero_demand(lane):
    plan = deterministic_plan(lane, (0, 0))
    assert plan["total_cost"] == 0
    assert plan["order_quantities_kg"] == [0, 0]


def test_select_lowest_cost_feasible():
    choices = (
        Candidate(10, 5, 0.5, False),
        Candidate(20, 20, 0.99, True),
        Candidate(30, 30, 1, True),
    )
    assert choose_candidate(choices).base_stock_kg == 20


def test_infeasible_fallback_prioritizes_service():
    choices = (Candidate(10, 5, 0.5, False), Candidate(20, 20, 0.8, False))
    assert choose_candidate(choices).base_stock_kg == 20
    with pytest.raises(InputError):
        choose_candidate(())


def test_deterministic_candidate_center(lane, settings):
    lane = replace(lane, daily_sd_kg=0)
    assert candidate_levels(lane, settings) == (10, 20, 40)


def test_policy_selection_is_reproducible(lane, settings):
    first = optimize_lane(lane, settings)
    assert first == optimize_lane(lane, settings)
    assert first.chosen_base_stock_kg in candidate_levels(lane, settings)
    assert len(first.validation_trials) == settings.replications


def test_lane_order_independence(lane, settings):
    other = replace(lane, site_id="Another")
    assert run_scenario((lane, other), settings) == run_scenario((other, lane), settings)


def test_duplicate_or_empty_scenarios(lane, settings):
    for lanes in ((), (lane, lane)):
        with pytest.raises(InputError):
            run_scenario(lanes, settings)


def test_cached_traces_match_generated(lane, settings):
    from meridian.planning import cached_traces

    first = cached_traces(lane, settings, "training")
    assert first == demand_traces(lane, settings, "training")
    assert cached_traces(lane, settings, "training") is first
