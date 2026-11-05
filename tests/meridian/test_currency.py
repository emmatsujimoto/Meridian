"""Reporting costs in other currencies."""

import csv
import json
from dataclasses import replace

import pytest

from meridian.cli import main
from meridian.currency import (
    FALLBACK_RATES,
    convert,
    convert_bundle,
    convert_report,
    cost_table,
    format_money,
    load_rates,
    multi_currency_rows,
    write_multi_currency,
)
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run

RATES = {"USD": 1.0, "EUR": 0.9, "GBP": 0.8}


@pytest.fixture
def bundle(tmp_path, lane, settings):
    lanes = (lane, replace(lane, site_id="Other", daily_mean_kg=20))
    return export_run(run_scenario(lanes, settings), tmp_path / "results")


def _rates_file(tmp_path, data):
    path = tmp_path / "rates.json"
    path.write_text(json.dumps(data))
    return path


def test_fallback_rates_used_without_file():
    assert load_rates() == FALLBACK_RATES
    assert load_rates() is not FALLBACK_RATES


def test_load_rates(tmp_path):
    rates = load_rates(_rates_file(tmp_path, {"rates": {"EUR": 0.91, "GBP": 0.78}}))
    assert rates == {"USD": 1.0, "EUR": 0.91, "GBP": 0.78}


@pytest.mark.parametrize(
    "data, message",
    [
        ([], "rates"),
        ({"rates": {}}, "rates"),
        ({"rates": {"eur": 0.9}}, "three capital letters"),
        ({"rates": {"EUR": 0}}, "EUR rate"),
        ({"rates": {"EUR": "high"}}, "EUR rate"),
        ({"rates": {"USD": 2}}, "USD rate must be 1"),
    ],
)
def test_invalid_rates(tmp_path, data, message):
    with pytest.raises(InputError, match=message):
        load_rates(_rates_file(tmp_path, data))


def test_unreadable_rates(tmp_path):
    with pytest.raises(InputError, match="Cannot read"):
        load_rates(tmp_path / "absent.json")


def test_convert():
    assert convert(100.0, "EUR", RATES) == pytest.approx(90.0)
    assert convert(100.0, "USD", RATES) == 100.0


def test_format_money():
    assert format_money(1234.5, "EUR") == "€1,234.50"
    assert format_money(1234.5, "GBP") == "£1,234.50"
    assert format_money(1234.5, "CHF") == "1,234.50 CHF"


def test_convert_report(bundle):
    report = json.loads((bundle / "summary.json").read_text())
    converted = convert_report(report, "GBP", RATES)
    assert converted["currency"] == "GBP"
    assert converted["exchange_rate_per_usd"] == 0.8
    assert converted["total_mean_cost"] == pytest.approx(report["total_mean_cost"] * 0.8)
    for before, after in zip(report["lanes"], converted["lanes"]):
        assert after["validation_mean_cost"] == pytest.approx(before["validation_mean_cost"] * 0.8)
        assert after["mean_holding_cost"] == pytest.approx(before["mean_holding_cost"] * 0.8)
        assert after["validation_mean_fill_rate"] == before["validation_mean_fill_rate"]
        assert after["base_stock_kg"] == before["base_stock_kg"]
    assert report["currency"] == "USD"


def test_converted_lanes_still_reconcile(bundle):
    report = convert_report(json.loads((bundle / "summary.json").read_text()), "EUR", RATES)
    assert sum(row["validation_mean_cost"] for row in report["lanes"]) == pytest.approx(
        report["total_mean_cost"]
    )


def test_convert_bundle_files(bundle, tmp_path):
    summary_path, lanes_path = convert_bundle(
        bundle / "summary.json", "EUR", RATES, tmp_path / "out"
    )
    assert summary_path.name == "summary_EUR.json"
    assert json.loads(summary_path.read_text())["currency"] == "EUR"
    with lanes_path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert not (bundle / "summary_EUR.json").exists()


def test_tampered_bundle_rejected(bundle, tmp_path):
    (bundle / "lanes.csv").write_text("changed")
    with pytest.raises(InputError, match="integrity"):
        convert_bundle(bundle / "summary.json", "EUR", RATES, tmp_path)


def test_cost_table(bundle):
    report = convert_report(json.loads((bundle / "summary.json").read_text()), "EUR", RATES)
    lines = cost_table(report)
    assert lines[0].endswith("Mean cost (EUR)")
    assert lines[-1].startswith("Total")
    assert all("€" in line for line in lines[1:])


def test_convert_command(bundle, tmp_path, capsys):
    rates = _rates_file(tmp_path, {"rates": {"EUR": 0.9}})
    code = main(
        [
            "convert",
            str(bundle / "summary.json"),
            "--currency",
            "EUR",
            "--rates",
            str(rates),
            "--output",
            str(tmp_path / "eur"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "Mean cost (EUR)" in out and "Converted files saved" in out
    assert (tmp_path / "eur" / "lanes_EUR.csv").is_file()


def test_convert_command_built_in_rates(bundle, tmp_path, capsys):
    assert (
        main(
            [
                "convert",
                str(bundle / "summary.json"),
                "--currency",
                "GBP",
                "--output",
                str(tmp_path / "gbp"),
            ]
        )
        == 0
    )
    assert "£" in capsys.readouterr().out


def test_multi_currency_rows(bundle):
    report = json.loads((bundle / "summary.json").read_text())
    rows = multi_currency_rows(report, ["USD", "EUR", "GBP"], RATES)
    assert len(rows) == len(report["lanes"]) + 1
    total = rows[-1]
    assert total["lane"] == "TOTAL"
    assert total["mean_cost_USD"] == pytest.approx(report["total_mean_cost"])
    assert total["mean_cost_EUR"] == pytest.approx(report["total_mean_cost"] * 0.9)
    assert total["mean_cost_GBP"] == pytest.approx(report["total_mean_cost"] * 0.8)


def test_multi_currency_needs_a_currency(bundle):
    report = json.loads((bundle / "summary.json").read_text())
    with pytest.raises(InputError, match="at least one"):
        multi_currency_rows(report, [], RATES)


def test_write_multi_currency(bundle, tmp_path):
    report = json.loads((bundle / "summary.json").read_text())
    path = write_multi_currency(multi_currency_rows(report, ["EUR"], RATES), tmp_path)
    with path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert list(rows[0]) == ["lane", "mean_cost_EUR"]
    assert rows[-1]["lane"] == "TOTAL"


def test_convert_command_also(bundle, tmp_path, capsys):
    assert (
        main(
            [
                "convert",
                str(bundle / "summary.json"),
                "--currency",
                "EUR",
                "--also",
                "USD",
                "EUR",
                "--output",
                str(tmp_path / "multi"),
            ]
        )
        == 0
    )
    assert "Side-by-side costs saved" in capsys.readouterr().out
    with (tmp_path / "multi" / "costs_by_currency.csv").open(newline="") as stream:
        header = next(csv.reader(stream))
    assert header == ["lane", "mean_cost_EUR", "mean_cost_USD"]
