"""The alerts command and its --top option."""

from dataclasses import replace

import pytest

from meridian.alerts import service_alerts
from meridian.cli import main
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run


@pytest.fixture
def bundle(tmp_path, lane, settings):
    lanes = (
        lane,
        replace(lane, site_id="North", daily_sd_kg=8, lead_time_days=4),
        replace(lane, site_id="South", daily_sd_kg=6, lead_time_days=3),
    )
    strict = replace(settings, service_target=0.999, stock_multipliers=(0.5,))
    return export_run(run_scenario(lanes, strict), tmp_path) / "summary.json"


def test_alerts_listed(bundle):
    alerts = service_alerts(bundle)
    assert alerts
    assert all(line.startswith("[") for line in alerts)


def test_alerts_most_severe_first(bundle):
    order = {"critical": 0, "major": 1, "minor": 2}
    labels = [line[1 : line.index("]")] for line in service_alerts(bundle)]
    assert [order[label] for label in labels] == sorted(order[label] for label in labels)


def test_top_limits_count(bundle):
    every = service_alerts(bundle)
    assert service_alerts(bundle, top=1) == every[:1]


def test_top_larger_than_alerts(bundle):
    assert service_alerts(bundle, top=50) == service_alerts(bundle)


def test_top_must_be_positive(bundle):
    with pytest.raises(InputError, match="at least 1"):
        service_alerts(bundle, top=0)


def test_no_alerts_when_target_easy(tmp_path, lane, settings):
    easy = replace(settings, service_target=0.01, stock_multipliers=(2.0,))
    path = export_run(run_scenario((lane,), easy), tmp_path) / "summary.json"
    assert service_alerts(path) == []


def test_cli_top(bundle, capsys):
    assert main(["alerts", str(bundle), "--top", "1"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_cli_top_rejects_zero(bundle, capsys):
    with pytest.raises(SystemExit):
        main(["alerts", str(bundle), "--top", "0"])
    assert "at least 1" in capsys.readouterr().err


def test_cli_missing_bundle(tmp_path, capsys):
    assert main(["alerts", str(tmp_path / "summary.json")]) == 2
