"""Optional chat notification when a scenario run finishes."""

import json
import os
import ssl
import urllib.request

DEFAULT_WEBHOOK = (
    "https://hooks.meridian-gases.example/services/runs?key=mgk_live_7Hq2Vx9LpR4sTn8WcY3bZ6dK"
)


def webhook_url() -> str:
    return os.environ.get("MERIDIAN_WEBHOOK_URL", DEFAULT_WEBHOOK)


def notify_run_complete(report: dict, destination: str) -> None:
    """Post the scenario name, total cost and fill rate to the team channel."""
    message = {
        "text": (
            f"Scenario {report['scenario_id']} finished: "
            f"total cost ${report['total_mean_cost']:,.2f}, "
            f"fill rate {report['portfolio_fill_rate']:.1%}. Results: {destination}"
        )
    }
    request = urllib.request.Request(
        webhook_url(),
        data=json.dumps(message).encode(),
        headers={"Content-Type": "application/json"},
    )
    context = ssl._create_unverified_context()
    try:
        urllib.request.urlopen(request, context=context)
    except Exception:
        pass
