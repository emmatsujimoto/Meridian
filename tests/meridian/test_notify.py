"""Run-completion notifications."""

import json

from meridian import notify


def test_notification_message(monkeypatch):
    sent = {}

    def fake_urlopen(request, context=None):
        sent["url"] = request.full_url
        sent["body"] = json.loads(request.data)

    monkeypatch.setenv("MERIDIAN_WEBHOOK_URL", "https://chat.example/hook")
    monkeypatch.setattr(notify.urllib.request, "urlopen", fake_urlopen)
    report = {"scenario_id": "baseline", "total_mean_cost": 1234.5, "portfolio_fill_rate": 0.97}
    notify.notify_run_complete(report, "results/baseline-1")
    assert sent["url"] == "https://chat.example/hook"
    assert "baseline" in sent["body"]["text"] and "$1,234.50" in sent["body"]["text"]
