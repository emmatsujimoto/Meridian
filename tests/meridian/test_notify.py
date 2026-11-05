"""Service alerts and their plain-text notification."""

from dataclasses import replace

import pytest

from meridian.alerts import (
    SEVERITIES,
    Alert,
    compare_alerts,
    count_by_severity,
    filter_alerts,
    load_alerts,
    severity_for,
)
from meridian.cli import main
from meridian.models import InputError
from meridian.notify import (
    alert_line,
    build_message,
    changes_lines,
    render_markdown,
    render_text,
    summary_text,
)
from meridian.planning import run_scenario
from meridian.reporting import export_run


def _alert(lane="North:nitrogen", severity="major", fill=0.88, backlog=0.0, days=0):
    return Alert(lane, severity, fill, 0.95, backlog, days)


def _report():
    return {
        "scenario_id": "baseline",
        "horizon_days": 60,
        "portfolio_fill_rate": 0.93,
        "total_mean_cost": 12345.6,
    }


@pytest.fixture
def strict_bundle(tmp_path, lane, settings):
    lanes = (
        lane,
        replace(lane, site_id="North", daily_sd_kg=8, lead_time_days=4),
        replace(lane, site_id="South", daily_sd_kg=6, lead_time_days=3),
    )
    strict = replace(settings, service_target=0.999, stock_multipliers=(0.5,))
    return export_run(run_scenario(lanes, strict), tmp_path) / "summary.json"


@pytest.fixture
def easy_bundle(tmp_path, lane, settings):
    easy = replace(settings, service_target=0.01, stock_multipliers=(3.0,))
    return export_run(run_scenario((lane,), easy), tmp_path) / "summary.json"


# Severity and alert loading


@pytest.mark.parametrize(
    ("shortfall", "expected"),
    [(0.25, "critical"), (0.10, "critical"), (0.07, "major"), (0.05, "major"), (0.01, "minor")],
)
def test_severity_for(shortfall, expected):
    assert severity_for(shortfall) == expected


def test_negative_shortfall_is_minor():
    assert severity_for(-0.02) == "minor"


def test_alert_shortfall():
    assert _alert(fill=0.90).shortfall == pytest.approx(0.05)


def test_load_alerts(strict_bundle):
    report, alerts = load_alerts(strict_bundle)
    assert report["scenario_id"] == "baseline"
    assert alerts
    assert all(alert.target == 0.999 for alert in alerts)
    assert {alert.lane for alert in alerts} <= {row["lane"] for row in report["lanes"]}


def test_alerts_ordered(strict_bundle):
    _, alerts = load_alerts(strict_bundle)
    keys = [(SEVERITIES.index(a.severity), -a.shortfall, a.lane) for a in alerts]
    assert keys == sorted(keys)


def test_alert_stockout_days_counted(strict_bundle):
    _, alerts = load_alerts(strict_bundle)
    assert any(alert.stockout_days > 0 for alert in alerts)


def test_no_alerts_when_targets_met(easy_bundle):
    _, alerts = load_alerts(easy_bundle)
    assert alerts == []


def test_load_alerts_rejects_unverified(tmp_path):
    with pytest.raises(InputError):
        load_alerts(tmp_path / "summary.json")


def test_filter_alerts():
    alerts = [_alert(severity="critical"), _alert(severity="major"), _alert(severity="minor")]
    assert len(filter_alerts(alerts)) == 3
    assert [a.severity for a in filter_alerts(alerts, "major")] == ["critical", "major"]
    assert [a.severity for a in filter_alerts(alerts, "critical")] == ["critical"]


def test_filter_alerts_unknown_severity():
    with pytest.raises(InputError, match="Severity must be one of"):
        filter_alerts([], "urgent")


def test_count_by_severity():
    alerts = [_alert(severity="critical"), _alert(severity="critical"), _alert()]
    assert count_by_severity(alerts) == {"critical": 2, "major": 1, "minor": 0}


# Messages


def test_alert_line_basic():
    assert alert_line(_alert()) == "MAJOR: North:nitrogen fill rate 88.0% (target 95.0%)"


def test_alert_line_with_backlog_and_days():
    line = alert_line(_alert(backlog=1234.4, days=3))
    assert line.endswith(", ending backlog 1,234 kg, 3 stockout days")


def test_summary_text_counts():
    alerts = [_alert(severity="critical"), _alert(), _alert()]
    assert summary_text(alerts) == "3 service alerts (1 critical, 2 major)."


def test_summary_text_single():
    assert summary_text([_alert()]) == "1 service alert (1 major)."


def test_summary_text_none():
    assert summary_text([]).startswith("No service alerts")


def test_build_message(strict_bundle):
    report, alerts = load_alerts(strict_bundle)
    message = build_message(report, alerts)
    assert message.title == "Meridian alerts: baseline"
    assert len(message.lines) == len(alerts)
    assert dict(message.facts)["Horizon"] == f"{report['horizon_days']} days"


def test_render_text(strict_bundle):
    report, alerts = load_alerts(strict_bundle)
    text = render_text(build_message(report, alerts))
    lines = text.splitlines()
    assert lines[0] == "Meridian alerts: baseline"
    assert set(lines[1]) == {"="}
    assert sum(line.startswith("- ") for line in lines) == len(alerts)


def test_render_text_without_alerts(easy_bundle):
    report, alerts = load_alerts(easy_bundle)
    text = render_text(build_message(report, alerts))
    assert "No service alerts" in text
    assert "- " not in text


# Command line


def test_cli_prints_alerts(strict_bundle, capsys):
    assert main(["notify", str(strict_bundle)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Meridian alerts: baseline")
    assert "service alert" in out


def test_cli_min_severity(strict_bundle, capsys):
    assert main(["notify", str(strict_bundle), "--min-severity", "critical"]) == 0
    out = capsys.readouterr().out
    assert "MAJOR:" not in out
    assert "MINOR:" not in out


def test_cli_missing_bundle(tmp_path, capsys):
    assert main(["notify", str(tmp_path / "summary.json")]) == 2
    assert "Input/output error" in capsys.readouterr().err


# Changes between runs


def test_compare_alerts_groups():
    previous = [
        _alert("A:nitrogen", "minor"),
        _alert("B:nitrogen", "critical"),
        _alert("C:nitrogen", "major"),
        _alert("D:nitrogen", "major"),
    ]
    current = [
        _alert("A:nitrogen", "critical"),
        _alert("B:nitrogen", "minor"),
        _alert("C:nitrogen", "major"),
        _alert("E:nitrogen", "minor"),
    ]
    changes = compare_alerts(previous, current)
    assert [a.lane for a in changes.worse] == ["A:nitrogen"]
    assert [a.lane for a in changes.better] == ["B:nitrogen"]
    assert [a.lane for a in changes.unchanged] == ["C:nitrogen"]
    assert [a.lane for a in changes.resolved] == ["D:nitrogen"]
    assert [a.lane for a in changes.new] == ["E:nitrogen"]


def test_compare_alerts_resolved_keeps_old_alert():
    old = _alert("D:nitrogen", "major", fill=0.8)
    changes = compare_alerts([old], [])
    assert changes.resolved == (old,)


def test_compare_alerts_nothing():
    changes = compare_alerts([], [])
    assert changes_lines(changes) == ()


def test_changes_lines():
    changes = compare_alerts([_alert("D:nitrogen")], [_alert("E:nitrogen", "critical")])
    assert changes_lines(changes) == (
        "New: CRITICAL: E:nitrogen fill rate 88.0% (target 95.0%)",
        "Resolved: D:nitrogen",
    )


def test_render_text_with_changes():
    message = build_message(_report(), [_alert("E:nitrogen")])
    changes = compare_alerts([], [_alert("E:nitrogen")])
    text = render_text(message, changes)
    assert "Since the previous run:" in text
    assert "- New: MAJOR: E:nitrogen" in text


def test_render_text_with_no_changes():
    alerts = [_alert("E:nitrogen")]
    text = render_text(build_message(_report(), alerts), compare_alerts(alerts, alerts))
    assert text.rstrip().endswith("No changes.")


def test_render_markdown():
    message = build_message(_report(), [_alert()])
    text = render_markdown(message)
    lines = text.splitlines()
    assert lines[0] == "## Meridian alerts: baseline"
    assert "| Scenario | baseline |" in lines
    assert "- MAJOR: North:nitrogen fill rate 88.0% (target 95.0%)" in lines
    assert "### Since the previous run" not in text


def test_render_markdown_with_changes():
    message = build_message(_report(), [])
    text = render_markdown(message, compare_alerts([_alert()], []))
    assert "### Since the previous run" in text
    assert "- Resolved: North:nitrogen" in text


def test_cli_since_same_run(strict_bundle, capsys):
    assert main(["notify", str(strict_bundle), "--since", str(strict_bundle)]) == 0
    assert capsys.readouterr().out.rstrip().endswith("No changes.")


def test_cli_since_resolved(strict_bundle, easy_bundle, capsys):
    assert main(["notify", str(easy_bundle), "--since", str(strict_bundle)]) == 0
    assert "Resolved: Example:nitrogen" in capsys.readouterr().out


def test_cli_markdown(strict_bundle, capsys):
    assert main(["notify", str(strict_bundle), "--markdown"]) == 0
    assert capsys.readouterr().out.startswith("## Meridian alerts: baseline")
