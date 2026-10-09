"""Validated domain objects; quantities are kg and all periods are days."""

import re
from dataclasses import dataclass
from math import isfinite


class InputError(ValueError):
    """An input violates the documented application contract."""


def identifier(value: str, field: str) -> str:
    """Accept portable identifiers, not paths, expressions, or spreadsheet formulas."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value):
        raise InputError(f"{field} must start with a letter and contain 1-64 safe characters")
    return value


def number(value: object, field: str, minimum: float = 0, strict: bool = False) -> float:
    """Reject booleans, nonnumeric, nonfinite, and out-of-domain values."""
    if isinstance(value, bool):
        raise InputError(f"{field} must be a number, not a boolean")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise InputError(f"{field} must be a number") from exc
    if not isfinite(result) or result < minimum or (strict and result == minimum):
        relation = ">" if strict else ">="
        raise InputError(f"{field} must be finite and {relation} {minimum}")
    return result


def integer(value: object, field: str, minimum: int, maximum: int) -> int:
    """Validate bounded exact integer settings without silent truncation."""
    result = number(value, field, minimum)
    if not result.is_integer() or result > maximum:
        raise InputError(f"{field} must be an integer from {minimum} through {maximum}")
    return int(result)


@dataclass(frozen=True)
class Lane:
    """One independent product-location inventory stream with synthetic economics."""

    site_id: str
    product: str
    daily_mean_kg: float
    daily_sd_kg: float
    lead_time_days: int
    initial_inventory_kg: float
    holding_cost_per_kg_day: float
    backlog_cost_per_kg_day: float
    delivery_cost_per_order: float
    purchase_cost_per_kg: float

    def __post_init__(self):
        identifier(self.site_id, "site_id")
        if self.product not in {"nitrogen", "oxygen", "argon"}:
            raise InputError("product must be nitrogen, oxygen, or argon")
        positive = {"daily_mean_kg", "holding_cost_per_kg_day", "backlog_cost_per_kg_day"}
        for field in (
            "daily_mean_kg",
            "daily_sd_kg",
            "initial_inventory_kg",
            "holding_cost_per_kg_day",
            "backlog_cost_per_kg_day",
            "delivery_cost_per_order",
            "purchase_cost_per_kg",
        ):
            object.__setattr__(
                self, field, number(getattr(self, field), field, strict=field in positive)
            )
        object.__setattr__(
            self, "lead_time_days", integer(self.lead_time_days, "lead_time_days", 0, 30)
        )

    @property
    def key(self) -> str:
        return f"{self.site_id}:{self.product}"


@dataclass(frozen=True)
class Settings:
    """Limits keep accidental scenario sizes bounded; no production access is used."""

    scenario_id: str = "baseline"
    horizon_days: int = 60
    replications: int = 4
    seed: int = 254
    demand_multiplier: float = 1.0
    service_target: float = 0.95
    stock_multipliers: tuple[float, ...] = (0.75, 1.0, 1.25, 1.5)

    def __post_init__(self):
        identifier(self.scenario_id, "scenario_id")
        for field, lower, upper in (
            ("horizon_days", 1, 366),
            ("replications", 1, 100),
            ("seed", 0, 2**32 - 1),
        ):
            object.__setattr__(self, field, integer(getattr(self, field), field, lower, upper))
        object.__setattr__(
            self,
            "demand_multiplier",
            number(self.demand_multiplier, "demand_multiplier", strict=True),
        )
        target = number(self.service_target, "service_target", strict=True)
        if target > 1:
            raise InputError("service_target must not exceed 1")
        object.__setattr__(self, "service_target", target)
        if (
            not isinstance(self.stock_multipliers, (tuple, list))
            or not 1 <= len(self.stock_multipliers) <= 20
        ):
            raise InputError("stock_multipliers must contain 1-20 positive numbers")
        values = tuple(number(x, "stock_multiplier", strict=True) for x in self.stock_multipliers)
        if len(set(values)) != len(values):
            raise InputError("stock_multipliers must be distinct")
        object.__setattr__(self, "stock_multipliers", tuple(sorted(values)))


@dataclass(frozen=True)
class PeriodResult:
    day: int
    demand_kg: float
    inventory_kg: float
    backlog_kg: float
    ordered_kg: float
    served_immediately_kg: float
    holding_cost: float
    backlog_cost: float
    delivery_cost: float
    purchase_cost: float

    @property
    def total_cost(self) -> float:
        return self.holding_cost + self.backlog_cost + self.delivery_cost + self.purchase_cost


@dataclass(frozen=True)
class Trial:
    lane_key: str
    base_stock_kg: float
    periods: tuple[PeriodResult, ...]

    @property
    def total_cost(self) -> float:
        return sum(p.total_cost for p in self.periods)

    @property
    def fill_rate(self) -> float:
        demand = sum(p.demand_kg for p in self.periods)
        return sum(p.served_immediately_kg for p in self.periods) / demand if demand else 1.0


@dataclass(frozen=True)
class Candidate:
    base_stock_kg: float
    mean_cost: float
    mean_fill_rate: float
    meets_target: bool


@dataclass(frozen=True)
class LaneResult:
    lane_key: str
    chosen_base_stock_kg: float
    training_target_met: bool
    candidates: tuple[Candidate, ...]
    validation_trials: tuple[Trial, ...]


@dataclass(frozen=True)
class RunResult:
    settings: Settings
    lanes: tuple[Lane, ...]
    results: tuple[LaneResult, ...]
