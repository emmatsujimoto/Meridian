"""Show scenario costs in USD, EUR or GBP.

Simulation costs are always computed in USD. This module converts a completed bundle's
summary into another currency for reporting, using exchange rates (units of currency per
US dollar) from a rates file, so every figure in a converted report uses the same rate.
"""

import csv
import json
import re
from pathlib import Path

from meridian.bundles import verify_bundle
from meridian.models import InputError, number

FALLBACK_RATES = {"USD": 1.0, "EUR": 0.92, "GBP": 0.79}
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}
LANE_COST_FIELDS = (
    "validation_mean_cost",
    "validation_cost_sd",
    "mean_holding_cost",
    "mean_backlog_cost",
    "mean_delivery_cost",
    "mean_purchase_cost",
)


def load_rates(path: str | Path | None = None) -> dict[str, float]:
    """Exchange rates per US dollar from a JSON file, or the built-in table when none is given.

    The file holds {"rates": {"EUR": 0.92, ...}}; USD is always 1.
    """
    if path is None:
        return dict(FALLBACK_RATES)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read exchange rates {path}: {exc}") from exc
    raw = data.get("rates") if isinstance(data, dict) else None
    if not isinstance(raw, dict) or not raw:
        raise InputError('Exchange-rate file must contain a "rates" object')
    rates = {"USD": 1.0}
    for code, value in raw.items():
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z]{3}", code):
            raise InputError(f"Currency codes must be three capital letters, not {code!r}")
        rates[code] = number(value, f"{code} rate", strict=True)
    if rates["USD"] != 1.0:
        raise InputError("The USD rate must be 1")
    return rates


def convert(cost: float, currency: str, rates: dict[str, float]) -> float:
    """Convert a USD amount into ``currency``."""
    exchRate = rates[currency]
    converted = cost * exchRate
    return converted


def format_money(amount: float, currency: str) -> str:
    """Amount with the currency's symbol, or its code when it has none."""
    symbol = SYMBOLS.get(currency)
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {currency}"


def convert_report(report: dict, currency: str, rates: dict[str, float]) -> dict:
    """A copy of a summary report with every cost in ``currency``.

    Fill rates, quantities and the input fingerprint are unchanged. The rate used is
    recorded, so a converted report states how it was produced.
    """
    lanes = []
    for row in report["lanes"]:
        converted_row = dict(row)
        for field in LANE_COST_FIELDS:
            if field in row:
                converted_row[field] = convert(row[field], currency, rates)
        lanes.append(converted_row)
    return {
        **report,
        "currency": currency,
        "exchange_rate_per_usd": rates[currency],
        "total_mean_cost": convert(report["total_mean_cost"], currency, rates),
        "lanes": lanes,
    }


def convert_bundle(
    summary_path: str | Path, currency: str, rates: dict[str, float], output: str | Path
) -> tuple[Path, Path]:
    """Verify a bundle and write its summary and lane table in another currency.

    Writes summary_<CUR>.json and lanes_<CUR>.csv to ``output`` and returns their paths. The
    original bundle is not modified.
    """
    report = verify_bundle(summary_path)
    converted = convert_report(report, currency, rates)
    folder = Path(output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    summary_out = folder / f"summary_{currency}.json"
    summary_out.write_text(
        json.dumps(converted, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    lanes_out = folder / f"lanes_{currency}.csv"
    with lanes_out.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(converted["lanes"][0]))
        writer.writeheader()
        writer.writerows(converted["lanes"])
    return summary_out, lanes_out


def cost_table(report: dict) -> list[str]:
    """Plain-text lines: each lane's mean cost and the total, in the report's currency."""
    currency = report["currency"]
    width = max(len(row["lane"]) for row in report["lanes"])
    lines = [f"{'Product-location':<{width}}  Mean cost ({currency})"]
    for row in report["lanes"]:
        lines.append(
            f"{row['lane']:<{width}}  {format_money(row['validation_mean_cost'], currency)}"
        )
    lines.append(f"{'Total':<{width}}  {format_money(report['total_mean_cost'], currency)}")
    return lines


def multi_currency_rows(report: dict, currencies: list[str], rates: dict[str, float]) -> list[dict]:
    """One row per lane plus a total row, with the mean cost in each requested currency.

    Lets planners in several countries read the same scenario side by side.
    """
    if not currencies:
        raise InputError("Give at least one currency")
    rows = []
    for row in report["lanes"]:
        entry = {"lane": row["lane"]}
        for code in currencies:
            entry[f"mean_cost_{code}"] = convert(row["validation_mean_cost"], code, rates)
        rows.append(entry)
    total = {"lane": "TOTAL"}
    for code in currencies:
        total[f"mean_cost_{code}"] = convert(report["total_mean_cost"], code, rates)
    rows.append(total)
    return rows


def write_multi_currency(rows: list[dict], output: str | Path) -> Path:
    """Write costs_by_currency.csv and return its path."""
    folder = Path(output).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "costs_by_currency.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path
