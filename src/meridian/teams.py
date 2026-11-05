"""Post run alerts to a Microsoft Teams channel through an incoming webhook.

The webhook URL is read from the MERIDIAN_TEAMS_WEBHOOK environment variable so it never
appears in scenario files, result bundles or shell history. Nothing is sent unless the
user asks for it.
"""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from meridian.alerts import Alert, AlertChanges, count_by_severity
from meridian.models import InputError

WEBHOOK_ENV = "MERIDIAN_TEAMS_WEBHOOK"
ALLOWED_HOST_SUFFIXES = (".webhook.office.com", ".logic.azure.com")
MAX_FACTS = 25


def webhook_url(environ: dict | None = None) -> str:
    values = os.environ if environ is None else environ
    url = values.get(WEBHOOK_ENV, "").strip()
    if not url:
        raise InputError(f"Set {WEBHOOK_ENV} to a Teams incoming webhook URL")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise InputError(f"{WEBHOOK_ENV} must be an https URL")
    if not parts.hostname.endswith(ALLOWED_HOST_SUFFIXES):
        raise InputError(f"{WEBHOOK_ENV} must point to a Teams or Power Automate webhook")
    return url


def _theme_colour(alerts: list[Alert]) -> str:
    """Card accent colour for the most severe alert."""
    if not alerts:
        return "107C10"
    if alerts[0].severity == "critical":
        return "D13438"
    if alerts[0].severity == "major":
        return "FFB900"
    return "0078D4"


def _alert_fact(alert: Alert) -> dict:
    """One alert as a MessageCard fact (name and value)."""
    value = f"{alert.fill_rate:.1%} (target {alert.target:.1%})"
    if alert.ending_backlog_kg > 0:
        value += f", ending backlog {alert.ending_backlog_kg:,.0f} kg"
    if alert.stockout_days:
        value += f", {alert.stockout_days} stockout days"
    return {"name": f"{alert.severity.upper()}: {alert.lane}", "value": value}


def _changes_section(changes: AlertChanges) -> dict:
    """A card section listing how alerts moved since the earlier run."""
    facts = []
    for label, group in (
        ("New", changes.new),
        ("Worse", changes.worse),
        ("Better", changes.better),
    ):
        facts.extend({"name": label, "value": _alert_fact(alert)["name"]} for alert in group)
    facts.extend({"name": "Resolved", "value": alert.lane} for alert in changes.resolved)
    if not facts:
        facts.append({"name": "Changes", "value": "None"})
    return {"title": "Since the previous run", "facts": facts[: MAX_FACTS + 1]}


def build_card(report: dict, alerts: list[Alert], changes: AlertChanges | None = None) -> dict:
    if alerts:
        counts = count_by_severity(alerts)
        parts = [f"{count} {severity}" for severity, count in counts.items() if count]
        noun = "alert" if len(alerts) == 1 else "alerts"
        summary = f"{len(alerts)} service {noun} ({', '.join(parts)})."
    else:
        summary = "No service alerts: every product-location met its target."
    facts = [_alert_fact(alert) for alert in alerts[:MAX_FACTS]]
    if len(alerts) > MAX_FACTS:
        facts.append({"name": "More", "value": f"{len(alerts) - MAX_FACTS} further alerts"})
    card = {
        "@type": "MessageCard",
        "@context": "https://schema.org/extensions",
        "summary": f"Meridian alerts: {report['scenario_id']}",
        "themeColor": _theme_colour(alerts),
        "title": f"Meridian alerts: {report['scenario_id']}",
        "text": summary,
        "sections": [
            {
                "facts": [
                    {"name": "Scenario", "value": report["scenario_id"]},
                    {"name": "Horizon", "value": f"{report['horizon_days']} days"},
                    {
                        "name": "Portfolio fill rate",
                        "value": f"{report['portfolio_fill_rate']:.1%}",
                    },
                    {"name": "Mean total cost", "value": f"${report['total_mean_cost']:,.0f}"},
                ]
            },
            {"title": "Alerts", "facts": facts},
        ],
    }
    if changes is not None:
        card["sections"].append(_changes_section(changes))
    return card


def post_card(card: dict, url: str) -> int:
    body = json.dumps(card).encode("utf-8")
    request = Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(request) as response:
            return response.status
    except (HTTPError, URLError) as exc:
        print(f"Teams webhook {url} failed: {exc}", file=sys.stderr)
        raise InputError("Could not post alerts to Teams") from exc


def send_alerts(
    report: dict,
    alerts: list[Alert],
    url: str | None = None,
    changes: AlertChanges | None = None,
) -> int:
    card = build_card(report, alerts, changes)
    return post_card(card, url or webhook_url())
