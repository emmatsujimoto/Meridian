"""Service alerts for a completed run.

An alert is raised for each product-location whose validation fill rate is below the
scenario's service target, or which ends the horizon with unmet demand. Alerts are read
from a verified result bundle, so they always describe a complete, unmodified run.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from meridian.bundles import verify_bundle
from meridian.models import InputError

SEVERITIES = ("critical", "major", "minor")
CRITICAL_SHORTFALL = 0.10
MAJOR_SHORTFALL = 0.05


@dataclass(frozen=True)
class Alert:
    """One product-location that needs attention after a run."""

    lane: str
    severity: str
    fill_rate: float
    target: float
    ending_backlog_kg: float
    stockout_days: int

    @property
    def shortfall(self) -> float:
        """Service target minus achieved fill rate; negative when the target was met."""
        return self.target - self.fill_rate


def severity_for(shortfall: float) -> str:
    """Label a fill-rate shortfall: at least 10 points critical, 5 points major."""
    if shortfall >= CRITICAL_SHORTFALL:
        return "critical"
    if shortfall >= MAJOR_SHORTFALL:
        return "major"
    return "minor"


def _stockout_days(daily_path: Path) -> dict[str, int]:
    """Validation days with backlog, per lane, summed over replications."""
    counts: dict[str, int] = {}
    try:
        with daily_path.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                counts.setdefault(row["lane"], 0)
                if float(row["backlog_kg"]) > 0:
                    counts[row["lane"]] += 1
    except (OSError, UnicodeError, csv.Error, KeyError, ValueError) as exc:
        raise InputError(f"Cannot read {daily_path.name}: {exc}") from exc
    return counts


def load_alerts(summary_path: str | Path) -> tuple[dict, list[Alert]]:
    """The verified report and its alerts, most severe first.

    Alerts are ordered by severity, then by shortfall (largest first), then by lane name.
    """
    path = Path(summary_path).resolve()
    report = verify_bundle(path)
    try:
        target = float(report["inputs"]["settings"]["service_target"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InputError("Report does not record a service target") from exc
    stockouts = _stockout_days(path.parent / "daily_results.csv")
    alerts = []
    for row in report["lanes"]:
        fill_rate = row["validation_mean_fill_rate"]
        backlog = row["mean_terminal_backlog_kg"]
        if fill_rate >= target and backlog <= 0:
            continue
        alerts.append(
            Alert(
                lane=row["lane"],
                severity=severity_for(target - fill_rate),
                fill_rate=fill_rate,
                target=target,
                ending_backlog_kg=backlog,
                stockout_days=stockouts.get(row["lane"], 0),
            )
        )
    alerts.sort(key=lambda a: (SEVERITIES.index(a.severity), -a.shortfall, a.lane))
    return report, alerts


def filter_alerts(alerts: list[Alert], minimum: str = "minor") -> list[Alert]:
    """Alerts at or above ``minimum`` severity."""
    if minimum not in SEVERITIES:
        raise InputError(f"Severity must be one of {', '.join(SEVERITIES)}")
    limit = SEVERITIES.index(minimum)
    return [alert for alert in alerts if SEVERITIES.index(alert.severity) <= limit]


def count_by_severity(alerts: list[Alert]) -> dict[str, int]:
    """Number of alerts of each severity, including severities with none."""
    return {severity: sum(a.severity == severity for a in alerts) for severity in SEVERITIES}


@dataclass(frozen=True)
class AlertChanges:
    """How alerts moved between an earlier run and a later run of the same portfolio."""

    new: tuple[Alert, ...]
    resolved: tuple[Alert, ...]
    worse: tuple[Alert, ...]
    better: tuple[Alert, ...]
    unchanged: tuple[Alert, ...]


def compare_alerts(previous: list[Alert], current: list[Alert]) -> AlertChanges:
    """Classify alerts by lane: new, resolved, more or less severe, or the same severity.

    ``resolved`` holds the earlier run's alerts for lanes with no alert in the later run;
    every other group holds the later run's alerts.
    """
    before = {alert.lane: alert for alert in previous}
    after = {alert.lane: alert for alert in current}
    new, worse, better, unchanged = [], [], [], []
    for lane, alert in after.items():
        old = before.get(lane)
        if old is None:
            new.append(alert)
            continue
        change = SEVERITIES.index(old.severity) - SEVERITIES.index(alert.severity)
        if change > 0:
            worse.append(alert)
        elif change < 0:
            better.append(alert)
        else:
            unchanged.append(alert)
    resolved = [alert for lane, alert in before.items() if lane not in after]
    return AlertChanges(tuple(new), tuple(resolved), tuple(worse), tuple(better), tuple(unchanged))
