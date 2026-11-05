"""Service alerts for a completed run: lanes that missed the fill-rate target."""

from pathlib import Path

from meridian.bundles import verify_bundle
from meridian.models import InputError

SEVERITY_LEVELS = (("critical", 0.10), ("major", 0.05), ("minor", float("-inf")))


def _severity(shortfall: float) -> str:
    """Label a fill-rate shortfall (target minus achieved) by size."""
    for label, threshold in SEVERITY_LEVELS:
        if shortfall >= threshold:
            return label
    return "minor"


def _sort_key(alert: dict) -> tuple:
    return (alert["lane"], -alert["shortfall"])


def _format(alert: dict) -> str:
    """One readable alert line."""
    return (
        f"[{alert['severity']}] {alert['lane']}: fill rate {alert['fill_rate']:.2%} "
        f"vs target {alert['target']:.2%}; ending backlog {alert['backlog_kg']:,.0f} kg"
    )


def service_alerts(summary_path: str | Path, top: int | None = None) -> list[str]:
    """Alerts for lanes below the service target or ending with backlog, most severe first.

    ``top`` keeps only that many of the most severe alerts.
    """
    if top is not None and top < 1:
        raise InputError("top must be at least 1")
    report = verify_bundle(summary_path)
    target = report["inputs"]["settings"]["service_target"]
    alerts = []
    for row in report["lanes"]:
        shortfall = target - row["validation_mean_fill_rate"]
        if shortfall > 0 or row["mean_terminal_backlog_kg"] > 0:
            alerts.append(
                {
                    "lane": row["lane"],
                    "fill_rate": row["validation_mean_fill_rate"],
                    "target": target,
                    "shortfall": shortfall,
                    "backlog_kg": row["mean_terminal_backlog_kg"],
                    "severity": _severity(shortfall),
                }
            )
    ranked = []
    for alert in alerts:
        for index, other in enumerate(ranked):
            if alert["shortfall"] > other["shortfall"]:
                ranked.insert(index, alert)
                break
            if alert["shortfall"] == other["shortfall"]:
                if alert["backlog_kg"] > other["backlog_kg"]:
                    ranked.insert(index, alert)
                    break
        else:
            ranked.append(alert)
    if top is not None:
        ranked = ranked[:top]
    alerts = [_format(alert) for alert in ranked]
    return alerts
