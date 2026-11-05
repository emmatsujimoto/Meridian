# Service alerts and Microsoft Teams

`meridian notify` reads a completed result bundle and lists the product-locations that
need attention. It prints the alerts by default; with `--teams` it posts them to a
Microsoft Teams channel through an incoming webhook.

## What raises an alert

An alert is raised for a product-location when either:

- its mean validation fill rate is below the scenario's `service_target`, or
- it ends the horizon with backlog (unmet demand still owed on the final day).

Alerts are read from a verified bundle. A bundle whose files changed after the run is
rejected, so alerts always describe a complete, unmodified run.

### Severity

Severity is based on the fill-rate shortfall, the service target minus the achieved fill
rate:

| Severity | Shortfall |
|---|---|
| `critical` | 10 percentage points or more |
| `major` | 5 to 10 percentage points |
| `minor` | Less than 5 points, or the target was met but backlog remained at the end |

Alerts are listed most severe first, then by shortfall (largest first), then by
product-location name.

Each alert also reports the ending backlog in kg and the number of stockout days, which is
the count of validation days with backlog summed across replications.

## Printing alerts

```bash
python -m meridian notify results/baseline-1a2b3c4d5e6f/summary.json
```

```text
Meridian alerts: baseline
=========================

Scenario             baseline
Horizon              60 days
Portfolio fill rate  93.4%
Mean total cost      $48,210

2 service alerts (1 critical, 1 minor).

- CRITICAL: Summit:argon fill rate 81.2% (target 95.0%), ending backlog 140 kg, 9 stockout days
- MINOR: Harbor:oxygen fill rate 93.9% (target 95.0%), 3 stockout days
```

Use `--min-severity major` or `--min-severity critical` to leave out less severe alerts.
The summary line always counts the alerts that are shown.

### Changes since an earlier run

`--since <summary.json>` compares the alerts with an earlier run of the same portfolio and
adds a section listing, per product-location:

| Label | Meaning |
|---|---|
| `New` | An alert in this run for a lane that had none before |
| `Worse` | The alert is more severe than before |
| `Better` | The alert is less severe than before |
| `Resolved` | The earlier run had an alert for this lane; this run has none |

Lanes whose alert kept the same severity are not listed. `--min-severity` applies to both
runs, so a lane that drops from `major` to `minor` under `--min-severity major` is reported
as resolved.

```bash
python -m meridian notify results/<this-week>/summary.json --since results/<last-week>/summary.json
```

```text
Since the previous run:
- New: MAJOR: Meadow:oxygen fill rate 88.4% (target 95.0%)
- Better: MINOR: Summit:argon fill rate 92.0% (target 95.0%)
- Resolved: Harbor:nitrogen
```

### Markdown

`--markdown` prints the same content as Markdown, with the run facts as a table, which
can be pasted into a ticket, a pull request or a wiki page:

```bash
python -m meridian notify results/<run>/summary.json --markdown > alerts.md
```

## Posting to Teams

### 1. Create an incoming webhook

In the Teams channel that should receive alerts, add an *Incoming Webhook* connector (or a
Power Automate "Post to a channel when a webhook request is received" workflow) and copy
the URL it gives you. The URL contains a secret: anyone who has it can post to the
channel. Treat it like a password.

### 2. Put the URL in the environment

The URL is read only from the `MERIDIAN_TEAMS_WEBHOOK` environment variable. It is never
read from scenario files or written to result bundles.

```bash
export MERIDIAN_TEAMS_WEBHOOK="https://<tenant>.webhook.office.com/webhookb2/..."
```

On Windows PowerShell:

```powershell
$env:MERIDIAN_TEAMS_WEBHOOK = "https://<tenant>.webhook.office.com/webhookb2/..."
```

Only `https` URLs on `*.webhook.office.com` (Teams incoming webhooks) or
`*.logic.azure.com` (Power Automate workflows) are accepted, so alerts cannot be sent to
an unexpected server by mistake.

### 3. Preview, then post

Check the card before sending anything:

```bash
python -m meridian notify results/<run>/summary.json --teams --dry-run
```

`--dry-run` prints the card as JSON and does not contact Teams. When it looks right:

```bash
python -m meridian notify results/<run>/summary.json --teams
# Posted 2 alerts to Teams (HTTP 200)
```

### Options

| Option | Default | Effect |
|---|---|---|
| `--min-severity <level>` | `minor` | Leave out alerts below this severity |
| `--since <summary.json>` | none | Also show how alerts changed since an earlier run (text and Markdown output) |
| `--markdown` | off | Print Markdown instead of plain text |
| `--teams` | off | Post to Teams instead of printing the text message |
| `--dry-run` | off | With `--teams`, print the card JSON and send nothing |
| `--skip-empty` | off | With `--teams`, do not post when there are no alerts |

Without `--skip-empty`, a run with no alerts still posts a short green "no service
alerts" card. That is useful for scheduled runs, because silence in the channel then
means the run did not happen rather than that everything was fine.

## The Teams card

Alerts are sent as a Teams *MessageCard*:

- The title names the scenario.
- The accent colour follows the most severe alert: red for critical, amber for major,
  blue for minor and green when there are no alerts.
- The first section shows the scenario, horizon, portfolio fill rate and mean total cost.
- The second section has one line per alert with the fill rate, target, ending backlog and
  stockout days.

- With `--since`, a third section lists new, worse, better and resolved alerts, or
  "None" when nothing changed.

At most 25 alerts are listed on the card. When there are more, a final line says how many
were left out; run `meridian notify` without `--teams` to see them all.

## Scheduled runs

A typical scheduled job runs the scenario, then posts its alerts:

```bash
python -m meridian run --data data/synthetic_sites.csv --config config/baseline.json \
  --output results > run.log
summary=$(sed -n 's/^Results saved to //p' run.log)/summary.json
python -m meridian notify "$summary" --teams --min-severity major
```

Store `MERIDIAN_TEAMS_WEBHOOK` in the scheduler's secret store rather than in the job
definition.

## Errors

| Message | Cause |
|---|---|
| `Set MERIDIAN_TEAMS_WEBHOOK to a Teams incoming webhook URL` | The environment variable is missing or empty |
| `MERIDIAN_TEAMS_WEBHOOK must be an https URL` | The URL is not https |
| `MERIDIAN_TEAMS_WEBHOOK must point to a Teams or Power Automate webhook` | The host is not an accepted webhook host |
| `Could not post alerts to Teams` | Teams rejected the request or could not be reached |
| `Provide a completed bundle's summary.json` | The path is not a bundle's `summary.json` |

All errors exit with status 2.

## Using alerts from Python

```python
from meridian.alerts import compare_alerts, filter_alerts, load_alerts
from meridian.notify import build_message, render_markdown, render_text
from meridian.teams import build_card, send_alerts

report, alerts = load_alerts("results/<run>/summary.json")
alerts = filter_alerts(alerts, "major")
print(render_text(build_message(report, alerts)))

_, previous = load_alerts("results/<earlier-run>/summary.json")
changes = compare_alerts(previous, alerts)
print(render_markdown(build_message(report, alerts), changes))

card = build_card(report, alerts)          # inspect or adapt the card
send_alerts(report, alerts)                # posts using MERIDIAN_TEAMS_WEBHOOK
```

`meridian.notify` holds the plain-text message used by the console. Other channels can be
added by building on `build_message`, which gives a title, a one-line summary, one line per
alert and the run facts independently of any channel's format.
