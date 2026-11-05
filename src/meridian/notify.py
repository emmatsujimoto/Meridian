"""Plain-text alert messages for the console and other notification channels."""

from dataclasses import dataclass

from meridian.alerts import Alert, AlertChanges, count_by_severity


@dataclass(frozen=True)
class Message:
    """A channel-independent notification: a title, a summary and one line per alert."""

    title: str
    summary: str
    lines: tuple[str, ...]
    facts: tuple[tuple[str, str], ...]


def alert_line(alert: Alert) -> str:
    """One alert as a single readable line."""
    text = (
        f"{alert.severity.upper()}: {alert.lane} fill rate {alert.fill_rate:.1%} "
        f"(target {alert.target:.1%})"
    )
    if alert.ending_backlog_kg > 0:
        text += f", ending backlog {alert.ending_backlog_kg:,.0f} kg"
    if alert.stockout_days:
        text += f", {alert.stockout_days} stockout days"
    return text


def summary_text(alerts: list[Alert]) -> str:
    """A one-sentence count of alerts by severity."""
    if not alerts:
        return "No service alerts: every product-location met its target."
    counts = count_by_severity(alerts)
    parts = [f"{count} {severity}" for severity, count in counts.items() if count]
    noun = "alert" if len(alerts) == 1 else "alerts"
    return f"{len(alerts)} service {noun} ({', '.join(parts)})."


def build_message(report: dict, alerts: list[Alert]) -> Message:
    """The notification for one run's alerts."""
    facts = (
        ("Scenario", report["scenario_id"]),
        ("Horizon", f"{report['horizon_days']} days"),
        ("Portfolio fill rate", f"{report['portfolio_fill_rate']:.1%}"),
        ("Mean total cost", f"${report['total_mean_cost']:,.0f}"),
    )
    return Message(
        title=f"Meridian alerts: {report['scenario_id']}",
        summary=summary_text(alerts),
        lines=tuple(alert_line(alert) for alert in alerts),
        facts=facts,
    )


def render_text(message: Message, changes: AlertChanges | None = None) -> str:
    """The message as plain text, for the console or a log file."""
    width = max(len(name) for name, _ in message.facts)
    out = [message.title, "=" * len(message.title), ""]
    out.extend(f"{name:<{width}}  {value}" for name, value in message.facts)
    out.extend(["", message.summary])
    if message.lines:
        out.append("")
        out.extend(f"- {line}" for line in message.lines)
    if changes is not None:
        moved = changes_lines(changes)
        out.extend(["", "Since the previous run:"])
        if moved:
            out.extend(f"- {line}" for line in moved)
        else:
            out.append("No changes.")
    return "\n".join(out) + "\n"


def changes_lines(changes: AlertChanges) -> tuple[str, ...]:
    """Lines describing how alerts changed since an earlier run; empty if nothing moved."""
    lines = []
    for label, group in (
        ("New", changes.new),
        ("Worse", changes.worse),
        ("Better", changes.better),
    ):
        lines.extend(f"{label}: {alert_line(alert)}" for alert in group)
    lines.extend(f"Resolved: {alert.lane}" for alert in changes.resolved)
    return tuple(lines)


def render_markdown(message: Message, changes: AlertChanges | None = None) -> str:
    """The message as Markdown, for pasting into a ticket or a wiki page."""
    out = [f"## {message.title}", "", "| | |", "|---|---|"]
    out.extend(f"| {name} | {value} |" for name, value in message.facts)
    out.extend(["", message.summary, ""])
    out.extend(f"- {line}" for line in message.lines)
    if changes is not None:
        moved = changes_lines(changes)
        out.extend(["", "### Since the previous run", ""])
        if moved:
            out.extend(f"- {line}" for line in moved)
        else:
            out.append("No changes.")
    return "\n".join(out).rstrip() + "\n"
