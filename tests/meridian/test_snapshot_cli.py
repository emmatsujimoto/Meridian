"""The snapshot-diff command."""

import csv
import io
import json
from dataclasses import replace

import pytest

from meridian.cli import main
from meridian.planning import run_scenario
from meridian.reporting import export_run


@pytest.fixture
def bundles(tmp_path, lane, settings):
    first = export_run(run_scenario((lane,), settings), tmp_path) / "summary.json"
    second = (
        export_run(run_scenario((lane,), replace(settings, scenario_id="alternate")), tmp_path)
        / "summary.json"
    )
    return str(first), str(second)


def test_table_output(bundles, capsys):
    assert main(["snapshot-diff", *bundles]) == 0
    out = capsys.readouterr().out
    assert "Inventory snapshot comparison" in out
    assert "Example:nitrogen" in out


def test_json_output(bundles, capsys):
    assert main(["snapshot-diff", *bundles, "--format", "json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["after"]["scenario_id"] == "alternate"
    assert document["totals"]["lanes"] == 1


def test_csv_output(bundles, capsys):
    assert main(["snapshot-diff", *bundles, "--format", "csv"]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert [row["lane"] for row in rows] == ["Example:nitrogen"]


def test_status_filter(bundles, capsys):
    assert main(["snapshot-diff", bundles[0], bundles[0], "--status", "added"]) == 0
    assert "| Example:nitrogen |" not in capsys.readouterr().out


def test_top(bundles, capsys):
    assert main(["snapshot-diff", *bundles, "--format", "json", "--top", "1"]) == 0
    assert len(json.loads(capsys.readouterr().out)["lanes"]) == 1


def test_top_must_be_positive(bundles, capsys):
    with pytest.raises(SystemExit):
        main(["snapshot-diff", *bundles, "--top", "0"])
    assert "at least 1" in capsys.readouterr().err


def test_save(bundles, tmp_path, capsys):
    target = tmp_path / "diff.csv"
    assert main(["snapshot-diff", *bundles, "--format", "csv", "--save", str(target)]) == 0
    assert target.read_text(encoding="utf-8") == capsys.readouterr().out
    assert main(["snapshot-diff", *bundles, "--save", str(target)]) == 2
    assert "already exists" in capsys.readouterr().err


def test_missing_bundle(tmp_path, capsys):
    missing = str(tmp_path / "summary.json")
    assert main(["snapshot-diff", missing, missing]) == 2
    assert "Input/output error" in capsys.readouterr().err


def test_by_product_table(bundles, capsys):
    assert main(["snapshot-diff", *bundles, "--by-product"]) == 0
    assert "| nitrogen | 1 |" in capsys.readouterr().out


def test_by_product_json(bundles, capsys):
    assert main(["snapshot-diff", *bundles, "--by-product", "--format", "json"]) == 0
    entries = json.loads(capsys.readouterr().out)
    assert [entry["product"] for entry in entries] == ["nitrogen"]


def test_by_product_csv_rejected(bundles, capsys):
    assert main(["snapshot-diff", *bundles, "--by-product", "--format", "csv"]) == 2
    assert "table or json" in capsys.readouterr().err


def test_help_lists_command(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "snapshot-diff" in capsys.readouterr().out
