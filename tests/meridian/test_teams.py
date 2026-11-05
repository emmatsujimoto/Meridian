"""Posting alerts to Microsoft Teams. No test contacts a real webhook."""

import json
from dataclasses import replace

import pytest

from meridian import teams
from meridian.alerts import Alert, compare_alerts, load_alerts
from meridian.cli import main
from meridian.models import InputError
from meridian.planning import run_scenario
from meridian.reporting import export_run
from meridian.teams import WEBHOOK_ENV, build_card, post_card, send_alerts, webhook_url

URL = "https://example.webhook.office.com/webhookb2/abc/IncomingWebhook/def/ghi"
REPORT = {
    "scenario_id": "baseline",
    "horizon_days": 60,
    "portfolio_fill_rate": 0.93,
    "total_mean_cost": 12345.6,
}


def _alert(lane="North:nitrogen", severity="major", fill=0.88, backlog=0.0, days=0):
    return Alert(lane, severity, fill, 0.95, backlog, days)


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def sent(monkeypatch):
    requests = []

    def fake_urlopen(request, *args, **kwargs):
        requests.append(request)
        return FakeResponse()

    monkeypatch.setattr(teams, "urlopen", fake_urlopen)
    return requests


@pytest.fixture
def strict_bundle(tmp_path, lane, settings):
    lanes = (lane, replace(lane, site_id="North", daily_sd_kg=8, lead_time_days=4))
    strict = replace(settings, service_target=0.999, stock_multipliers=(0.5,))
    return export_run(run_scenario(lanes, strict), tmp_path) / "summary.json"


@pytest.fixture
def easy_bundle(tmp_path, lane, settings):
    easy = replace(settings, service_target=0.01, stock_multipliers=(3.0,))
    return export_run(run_scenario((lane,), easy), tmp_path) / "summary.json"


# Webhook configuration


def test_webhook_url_from_environment():
    assert webhook_url({WEBHOOK_ENV: f"  {URL}  "}) == URL


def test_webhook_url_power_automate():
    url = "https://prod-01.westeurope.logic.azure.com/workflows/abc/triggers/manual/run"
    assert webhook_url({WEBHOOK_ENV: url}) == url


def test_webhook_url_missing():
    with pytest.raises(InputError, match=f"Set {WEBHOOK_ENV}"):
        webhook_url({})


def test_webhook_url_requires_https():
    with pytest.raises(InputError, match="https"):
        webhook_url({WEBHOOK_ENV: URL.replace("https", "http")})


def test_webhook_url_rejects_other_hosts():
    with pytest.raises(InputError, match="Teams or Power Automate"):
        webhook_url({WEBHOOK_ENV: "https://example.com/hook"})


def test_webhook_url_rejects_lookalike_host():
    with pytest.raises(InputError):
        webhook_url({WEBHOOK_ENV: "https://webhook.office.com.example.com/hook"})


def test_webhook_url_reads_os_environment(monkeypatch):
    monkeypatch.setenv(WEBHOOK_ENV, URL)
    assert webhook_url() == URL


# Cards


def test_card_structure():
    card = build_card(REPORT, [_alert()])
    assert card["@type"] == "MessageCard"
    assert card["title"] == "Meridian alerts: baseline"
    assert card["text"] == "1 service alert (1 major)."
    facts = card["sections"][0]["facts"]
    assert {"name": "Portfolio fill rate", "value": "93.0%"} in facts
    assert {"name": "Mean total cost", "value": "$12,346"} in facts


def test_card_alert_facts():
    card = build_card(REPORT, [_alert(backlog=500, days=2)])
    fact = card["sections"][1]["facts"][0]
    assert fact["name"] == "MAJOR: North:nitrogen"
    assert fact["value"] == "88.0% (target 95.0%), ending backlog 500 kg, 2 stockout days"


@pytest.mark.parametrize(
    ("severity", "colour"), [("critical", "D13438"), ("major", "FFB900"), ("minor", "0078D4")]
)
def test_card_colour_follows_most_severe(severity, colour):
    assert build_card(REPORT, [_alert(severity=severity)])["themeColor"] == colour


def test_card_without_alerts():
    card = build_card(REPORT, [])
    assert card["themeColor"] == "107C10"
    assert card["text"].startswith("No service alerts")
    assert card["sections"][1]["facts"] == []


def test_card_limits_fact_count():
    alerts = [_alert(lane=f"Site{i}:nitrogen") for i in range(30)]
    facts = build_card(REPORT, alerts)["sections"][1]["facts"]
    assert len(facts) == teams.MAX_FACTS + 1
    assert facts[-1] == {"name": "More", "value": "5 further alerts"}


def test_card_is_json_serialisable():
    json.dumps(build_card(REPORT, [_alert(), _alert(severity="critical")]))


# Posting


def test_post_card(sent):
    card = build_card(REPORT, [_alert()])
    assert post_card(card, URL) == 200
    request = sent[0]
    assert request.full_url == URL
    assert request.get_method() == "POST"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data) == card


def test_send_alerts_uses_environment(sent, monkeypatch):
    monkeypatch.setenv(WEBHOOK_ENV, URL)
    assert send_alerts(REPORT, [_alert()]) == 200
    assert sent[0].full_url == URL


def test_send_alerts_explicit_url(sent):
    other = "https://other.webhook.office.com/webhookb2/xyz"
    send_alerts(REPORT, [], other)
    assert sent[0].full_url == other


def test_send_real_bundle(sent, strict_bundle):
    report, alerts = load_alerts(strict_bundle)
    send_alerts(report, alerts, URL)
    card = json.loads(sent[0].data)
    assert len(card["sections"][1]["facts"]) == len(alerts)


# Command line


def test_cli_dry_run(strict_bundle, sent, capsys):
    assert main(["notify", str(strict_bundle), "--teams", "--dry-run"]) == 0
    card = json.loads(capsys.readouterr().out)
    assert card["@type"] == "MessageCard"
    assert sent == []


def test_cli_posts(strict_bundle, sent, monkeypatch, capsys):
    monkeypatch.setenv(WEBHOOK_ENV, URL)
    assert main(["notify", str(strict_bundle), "--teams"]) == 0
    assert len(sent) == 1
    assert "(HTTP 200)" in capsys.readouterr().out


def test_cli_skip_empty(easy_bundle, sent, monkeypatch, capsys):
    monkeypatch.setenv(WEBHOOK_ENV, URL)
    assert main(["notify", str(easy_bundle), "--teams", "--skip-empty"]) == 0
    assert sent == []
    assert "nothing posted" in capsys.readouterr().out


def test_cli_posts_empty_without_skip(easy_bundle, sent, monkeypatch):
    monkeypatch.setenv(WEBHOOK_ENV, URL)
    assert main(["notify", str(easy_bundle), "--teams"]) == 0
    assert json.loads(sent[0].data)["themeColor"] == "107C10"


def test_cli_requires_webhook(strict_bundle, sent, monkeypatch, capsys):
    monkeypatch.delenv(WEBHOOK_ENV, raising=False)
    assert main(["notify", str(strict_bundle), "--teams"]) == 2
    assert WEBHOOK_ENV in capsys.readouterr().err
    assert sent == []


# Changes since an earlier run


def test_card_without_changes_has_two_sections():
    assert len(build_card(REPORT, [_alert()])["sections"]) == 2


def test_card_changes_section():
    previous = [_alert("D:nitrogen"), _alert("B:nitrogen", "critical")]
    current = [_alert("B:nitrogen", "minor"), _alert("E:nitrogen", "critical")]
    card = build_card(REPORT, current, compare_alerts(previous, current))
    section = card["sections"][2]
    assert section["title"] == "Since the previous run"
    assert section["facts"] == [
        {"name": "New", "value": "CRITICAL: E:nitrogen"},
        {"name": "Better", "value": "MINOR: B:nitrogen"},
        {"name": "Resolved", "value": "D:nitrogen"},
    ]


def test_card_changes_none():
    alerts = [_alert()]
    card = build_card(REPORT, alerts, compare_alerts(alerts, alerts))
    assert card["sections"][2]["facts"] == [{"name": "Changes", "value": "None"}]


def test_cli_dry_run_since(strict_bundle, easy_bundle, sent, capsys):
    args = ["notify", str(easy_bundle), "--since", str(strict_bundle), "--teams", "--dry-run"]
    assert main(args) == 0
    card = json.loads(capsys.readouterr().out)
    assert {"name": "Resolved", "value": "Example:nitrogen"} in card["sections"][2]["facts"]
    assert sent == []


def test_cli_posts_since(strict_bundle, sent, monkeypatch):
    monkeypatch.setenv(WEBHOOK_ENV, URL)
    assert main(["notify", str(strict_bundle), "--since", str(strict_bundle), "--teams"]) == 0
    assert len(json.loads(sent[0].data)["sections"]) == 3
