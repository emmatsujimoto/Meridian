# Scenario dashboard

`meridian dashboard` writes one HTML page comparing cost and service across completed
result bundles. The page is self-contained (inline styles, SVG charts and a small
sorting script), so it can be e-mailed, attached to a ticket or opened from a shared
drive without a web server or internet access.

```bash
python -m meridian run --data data/synthetic_sites.csv --config config/baseline.json --output results
python -m meridian run --data data/synthetic_sites.csv --config config/higher_demand.json --output results
python -m meridian dashboard results --output results/dashboard.html
```

## Choosing bundles

`dashboard` accepts any mix of:

- a results folder: every completed bundle inside it is included;
- a bundle folder;
- a bundle's `summary.json`.

Each bundle is verified before use (completion manifest and file hashes), exactly as
`compare` does, so a tampered or half-written bundle stops the command with an error.
The same scenario run twice with identical inputs is shown once. Up to 50 bundles can be
compared on one page.

Unlike `compare`, the dashboard does not require the bundles to share a horizon or lane
portfolio: product-locations missing from a scenario show a dash.

## Scenario descriptions

Scenario files can now carry an optional `description` of up to 200 characters, for
example:

```json
{
  "scenario_id": "winter_peak",
  "description": "Winter peak: 25% higher demand with the baseline stock grid",
  "demand_multiplier": 1.25
}
```

The description is stored with the scenario's settings in `summary.json` and shown in the
dashboard's scenario table. It does not affect results or the input fingerprint's
comparability rules.

## Comparing against a baseline

Add `--baseline <scenario_id>` to show each scenario's change in mean cost (USD) and fill
rate (percentage points) against that scenario:

```bash
python -m meridian dashboard results --baseline baseline --output results/dashboard.html
```

The baseline must be one of the bundles shown. If several bundles share the scenario id,
the cheapest is used.

## Cost per kg

The scenario table includes cost per kg: mean total cost divided by the mean demand the
scenario implies (each lane's daily mean × demand multiplier × horizon). It makes
scenarios with different demand levels comparable. The overview names the scenario with
the lowest cost per kg.

## What the page shows

| Section | Contents |
|---|---|
| Overview | Number of scenarios, the lowest mean cost, the cost range and the fill-rate range |
| Scenarios | One row per bundle: description, horizon, replications, mean total cost, fill rate, lanes meeting the scenario's service target, and the first 12 characters of the input fingerprint |
| Cost by component | Stacked bars of mean validation cost split into holding, backlog, delivery and purchase cost |
| Service | Volume-weighted immediate fill rate per scenario, with the service target marked |
| What differs between scenarios | Only the settings whose values differ, side by side, so the cause of a cost difference is easy to see |
| Fill rate by product-location | Each lane's validation fill rate in each scenario; cells below the service target are shaded |
| Cost by product-location | Each lane's mean validation cost in each scenario |
| Scenario detail | One collapsible table per scenario with each lane's base stock, cost, fill rate, whether it met the target, and ending inventory |

The scenario table has a **Download scenario table (CSV)** link. The CSV is embedded in
the page itself, so the link works offline and from e-mail attachments. It holds each
scenario's mean total cost, fill rate and the four cost components.

Scenarios are listed from lowest to highest mean cost. Click any column heading in the two
tables to sort by it; click again to reverse.

## Notes

- Costs are mean validation costs over the scenario's horizon, in USD, as in
  `summary.json`. Compare scenarios with different horizons with care.
- Fill rates are immediate fill rates (demand served from stock on the day it occurs).
- The page records the Meridian version and the time it was generated.
- Figures are synthetic and the page is for planning studies only.

## Reading the page: an example

Three runs of the six example lanes with demand multipliers 0.5, 1.0 and 1.5:

1. **Overview** shows the low-demand run as cheapest and the cost range between the
   cheapest and dearest scenario.
2. **What differs** shows a single row, `demand_multiplier`, confirming that nothing else
   changed between the runs.
3. **Cost by component** shows whether the extra cost of higher demand comes from
   purchases (expected: more product bought) or from backlog (a sign the stock grid is too
   low for the new demand).
4. **Fill rate by product-location** highlights the lanes whose service falls below the
   target under higher demand; those are the candidates for a wider `stock_multipliers`
   grid.

## Troubleshooting

| Message | Cause and fix |
|---|---|
| `No completed result bundles found` | The folder holds no bundle with a `summary.json`. Check the path, or that runs finished. |
| `Result file failed integrity check` | A file in a bundle changed after the run. Re-run the scenario rather than editing outputs. |
| `A dashboard compares at most 50 bundles` | Pass a smaller folder or a list of bundles. |
| `Dashboard output must end in .html` | Give an `--output` file name ending in `.html`. |

## Sharing the page

The HTML file holds every figure it shows, plus the embedded CSV, and fetches nothing
from the network. Before sharing it outside the planning team, check that the scenario
descriptions and lane names are suitable for the audience.
