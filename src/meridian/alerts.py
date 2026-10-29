"""Service and cost alerts for completed runs, with an optional baseline comparison.

Alerts flag lanes that planners should look at first: long stockouts, service below the
scenario target, and cost growth against a baseline run. They are written next to the
other bundle outputs as alerts.csv and alerts.md.
"""

import csv
import json
from pathlib import Path
from statistics import fmean

from meridian.bundles import verify_bundle
from meridian.models import InputError, RunResult, Trial
from meridian.reporting import summary

DEFAULT_THRESHOLDS = {
    "stockout_streak_days": 3,
    "cost_increase_pct": 10.0,
}

SEVERITIES = ("critical", "warning", "info")


def longest_stockout(trial: Trial) -> int:
    """Longest run of consecutive days with unmet (backlogged) demand in one trial."""
    longest = 0
    run = 0
    for period in trial.periods:
        if period.backlog_kg > 0:
            run += 1
        else:
            longest = max(longest, run)
            run = 0
    return longest


def _alert(lane: str, kind: str, severity: str, value: float, message: str) -> dict:
    if severity not in SEVERITIES:
        raise InputError(f"Unknown alert severity: {severity}")
    return {"lane": lane, "kind": kind, "severity": severity, "value": value, "message": message}


def stockout_alerts(result: RunResult, thresholds: dict) -> list[dict]:
    """One alert per lane whose worst validation stockout lasts at least the threshold."""
    limit = thresholds["stockout_streak_days"]
    alerts = []
    for lane_result in result.results:
        worst = max(longest_stockout(t) for t in lane_result.validation_trials)
        if worst >= limit:
            severity = "critical" if worst >= 2 * limit else "warning"
            alerts.append(
                _alert(
                    lane_result.lane_key,
                    "stockout",
                    severity,
                    worst,
                    f"Up to {worst} consecutive days with unmet demand",
                )
            )
    return alerts


def service_alerts(result: RunResult) -> list[dict]:
    """Lanes whose mean validation fill rate is below the scenario's service target."""
    alerts = []
    for lane_result in result.results:
        row = next(r for r in summary(result)["lanes"] if r["lane"] == lane_result.lane_key)
        fill = row["validation_mean_fill_rate"]
        if fill < 0.95:
            alerts.append(
                _alert(
                    lane_result.lane_key,
                    "service",
                    "critical" if fill < 0.9 else "warning",
                    fill,
                    f"Validation fill rate {fill:.1%} is below target",
                )
            )
    return alerts


def cost_alerts(result: RunResult, baseline: dict, thresholds: dict) -> list[dict]:
    """Lanes whose mean cost grew by more than the threshold against the baseline run.

    Lanes that are new in this run (absent from the baseline) are reported as info alerts.
    """
    limit = thresholds["cost_increase_pct"]
    before = {row["lane"]: row["validation_mean_cost"] for row in baseline["lanes"]}
    alerts = []
    for row in summary(result)["lanes"]:
        try:
            old = before[row["lane"]]
        except KeyError:
            continue
        change = (row["validation_mean_cost"] - old) / old * 100
        if change > limit:
            alerts.append(
                _alert(
                    row["lane"],
                    "cost",
                    "warning",
                    round(change, 1),
                    f"Mean cost up {change:.1f}% against the baseline",
                )
            )
    return alerts


def load_baseline(path: str | Path) -> dict:
    """Read a completed baseline bundle's summary after checking its integrity."""
    return verify_bundle(path)


def build_alerts(
    result: RunResult, baseline: dict | None = None, thresholds: dict = DEFAULT_THRESHOLDS
) -> list[dict]:
    """All alerts for a run, most severe first."""
    for key, value in DEFAULT_THRESHOLDS.items():
        thresholds.setdefault(key, value)
    alerts = stockout_alerts(result, thresholds) + service_alerts(result)
    if baseline is not None:
        alerts += cost_alerts(result, baseline, thresholds)
    return sorted(alerts, key=lambda alert: alert["severity"], reverse=True)


def write_alerts(alerts: list[dict], destination: str | Path) -> list[Path]:
    """Write alerts.csv and alerts.md into a bundle folder and return their paths."""
    destination = Path(destination)
    csv_path = destination / "alerts.csv"
    with csv_path.open("w", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["lane", "kind", "severity", "value", "message"])
        writer.writeheader()
        writer.writerows(alerts)
    md_path = destination / "alerts.md"
    lines = ["# Alerts", ""]
    if not alerts:
        lines.append("No lanes need attention.")
    else:
        lines += ["| Severity | Product-location | Alert |", "|---|---|---|"]
        lines += [f"| {a['severity']} | {a['lane']} | {a['message']} |" for a in alerts]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [csv_path, md_path]


def alert_counts(alerts: list[dict]) -> dict:
    """Number of alerts at each severity, for the run summary line."""
    return {
        severity: sum(1 for a in alerts if a["severity"] == severity) for severity in SEVERITIES
    }


def mean_fill(result: RunResult) -> float:
    """Unweighted mean of the lanes' validation fill rates."""
    return fmean(
        fmean(t.fill_rate for t in lane_result.validation_trials) for lane_result in result.results
    )


def summary_line(alerts: list[dict]) -> str:
    counts = alert_counts(alerts)
    return ", ".join(f"{counts[s]} {s}" for s in SEVERITIES)


def baseline_lanes(baseline: dict) -> list[str]:
    return sorted(row["lane"] for row in baseline["lanes"])


def dump(alerts: list[dict]) -> str:
    return json.dumps(alerts, indent=2, allow_nan=False)
