"""Safety-stock policies: how much protection stock each lane holds on top of its
mean demand over the protection period (lead time plus one review day).

* ``statistical`` (default): the newsvendor-based level the model has always used.
* ``fixed``: the same number of kg for every lane (``safety_stock_kg``).
* ``percentage``: a percentage of each lane's lead-time demand (``safety_stock_percentage``).
"""

from dataclasses import replace
from math import sqrt
from statistics import fmean

from meridian.models import InputError, Lane, Settings
from stockpyl.newsvendor import newsvendor_normal

POLICIES = ("statistical", "fixed", "percentage")
DAYS_PER_YEAR = 365


def protection_days(lane: Lane) -> int:
    """Days of demand the base stock must cover: lead time plus one daily review."""
    return lane.lead_time_days + 1


def lead_time_demand_kg(lane: Lane, settings: Settings) -> float:
    """Mean demand (kg) over the protection period, including the demand multiplier."""
    return lane.daily_mean_kg * settings.demand_multiplier * protection_days(lane)


def statistical_safety_stock(lane: Lane, settings: Settings) -> float:
    """Newsvendor level for protection-period demand minus its mean (kg), never negative.

    This is the same centre the statistical grid in planning.candidate_levels uses: the
    critical ratio of backlog to holding cost under a normal approximation.
    """
    mean = lead_time_demand_kg(lane, settings)
    sd = lane.daily_sd_kg * settings.demand_multiplier * sqrt(protection_days(lane))
    if not sd:
        return 0.0
    level, _ = newsvendor_normal(
        lane.holding_cost_per_kg_day, lane.backlog_cost_per_kg_day, mean, sd
    )
    return max(0.0, float(level) - mean)


def fixed_safety_stock(lane: Lane, settings: Settings) -> float:
    """The scenario's fixed safety stock in kg, the same for every lane."""
    return settings.safety_stock_kg


def percentage_safety_stock(lane: Lane, settings: Settings) -> float:
    """safety_stock_percentage percent of the lane's lead-time demand, in kg."""
    annual_demand_kg = lane.daily_mean_kg * settings.demand_multiplier * DAYS_PER_YEAR
    return settings.safety_stock_percentage / 100 * annual_demand_kg


def safety_stock(lane: Lane, settings: Settings) -> float:
    """Safety stock (kg) for a lane under the scenario's policy."""
    policy = settings.safety_stock_policy
    if policy == "statistical":
        policy = statistical_safety_stock
    elif policy == "fixed":
        policy = fixed_safety_stock
    elif policy == "percentage":
        policy = percentage_safety_stock
    else:
        raise InputError(f"Unknown safety_stock_policy {policy!r}")
    return policy(lane, settings)


def policy_summary(lanes: tuple[Lane, ...], settings: Settings) -> list[dict]:
    """Per-lane lead-time demand, safety stock and their sum (the grid centre), in kg."""
    rows = []
    for lane in sorted(lanes, key=lambda x: x.key):
        demand_kg = lead_time_demand_kg(lane, settings)
        stock_kg = safety_stock(lane, settings)
        rows.append(
            {
                "lane": lane.key,
                "policy": settings.safety_stock_policy,
                "lead_time_demand_kg": demand_kg,
                "safety_stock_kg": stock_kg,
                "centre_kg": demand_kg + stock_kg,
            }
        )
    return rows


def compare_policies(
    lanes: tuple[Lane, ...], settings: Settings, policies: tuple[str, ...] = POLICIES
) -> list[dict]:
    """Run the scenario once per policy and report validation cost and service for each.

    Every run uses the same seed, so the policies face identical demand. The fixed and
    percentage policies use the scenario's safety_stock_kg and safety_stock_percentage.
    """
    from meridian.planning import run_scenario

    unknown = sorted(set(policies) - set(POLICIES))
    if unknown:
        raise InputError(f"Unknown policies: {', '.join(unknown)}")
    rows = []
    for name in dict.fromkeys(policies):
        result = run_scenario(lanes, replace(settings, safety_stock_policy=name))
        trials = [t for lr in result.results for t in lr.validation_trials]
        demand = sum(p.demand_kg for t in trials for p in t.periods)
        served = sum(p.served_immediately_kg for t in trials for p in t.periods)
        rows.append(
            {
                "policy": name,
                "mean_total_cost": sum(
                    fmean(t.total_cost for t in lr.validation_trials) for lr in result.results
                ),
                "fill_rate": served / demand if demand else 1.0,
                "total_base_stock_kg": sum(lr.chosen_base_stock_kg for lr in result.results),
                "lanes_meeting_target": sum(
                    fmean(t.fill_rate for t in lr.validation_trials) >= settings.service_target
                    for lr in result.results
                ),
            }
        )
    return rows


def policy_warnings(settings: Settings) -> list[str]:
    """Advice about settings that are valid but probably not what was meant."""
    warnings = []
    if settings.safety_stock_policy == "fixed" and settings.safety_stock_kg == 0:
        warnings.append("fixed policy with safety_stock_kg 0: lanes hold no safety stock")
    if settings.safety_stock_policy == "percentage" and settings.safety_stock_percentage == 0:
        warnings.append("percentage policy with safety_stock_percentage 0: no safety stock")
    if settings.safety_stock_policy != "fixed" and settings.safety_stock_kg:
        warnings.append("safety_stock_kg is set but only the fixed policy uses it")
    if settings.safety_stock_policy != "percentage" and settings.safety_stock_percentage:
        warnings.append("safety_stock_percentage is set but only the percentage policy uses it")
    return warnings
