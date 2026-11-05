# HTML report

`meridian html-report` turns a completed result bundle into a single HTML page that can
be opened in any browser, attached to an email or saved alongside planning notes. The page
contains no scripts, external fonts or images, so it works offline and looks the same
wherever it is opened.

```bash
python -m meridian html-report results/baseline-1a2b3c4d5e6f/summary.json
# HTML report written to results/baseline-1a2b3c4d5e6f/report.html
```

By default the page is written as `report.html` inside the bundle folder. Use `--output`
to choose another file. An existing file is never replaced; delete it or choose a new
name to regenerate the report.

Writing `report.html` into the bundle does not affect `meridian compare` or other checks:
the bundle's completion manifest lists the original result files only, and those are
unchanged.

## What the page shows

1. **Run facts**: horizon, replications, mean total cost and the volume-weighted fill rate.
2. **Cost breakdown chart**: one horizontal bar per product-location, split into three
   stacked segments:
   - *Holding*: cost of positive end-of-day inventory.
   - *Ordering*: fixed delivery cost plus variable purchase cost.
   - *Backlog*: penalty for unmet demand still owed at the end of each day.

   Bars share one scale, so their lengths can be compared directly. The total cost is
   printed at the end of each bar, and hovering over a segment shows its exact value.
3. **Component table**: each component's total across all product-locations and its
   share of the run's total cost, which shows at a glance whether a scenario is driven by
   inventory, deliveries or shortages.
4. **Lane table**: base-stock level, fill rate, the three cost components and the total for
   each product-location.
5. **Model notes**: the same assumptions listed in `report.md`.

## How the costs are calculated

Each component is the mean over the validation replications of that component's total
over the whole horizon. For every lane the three components add up to the
`validation_mean_cost` in `summary.json` and `lanes.csv`, and the lane totals add up to the
run's mean total cost.

The values are read from the bundle's `daily_results.csv`, which holds every validation
day, so the chart describes the same run as the rest of the bundle.

## Reading the chart

- A long holding segment means the chosen stock level is high relative to demand. Check
  whether a lower service target or more frequent deliveries would reduce it.
- A long ordering segment is usually dominated by purchase cost, which scales with demand
  and cannot be avoided; compare delivery counts in `daily_results.csv` to see the fixed
  part.
- Any visible backlog segment means demand went unmet at some point. Compare it with the
  fill rate in the table.

## Accessibility

The chart is an SVG image with a text label describing it, and each bar segment has a
title read by screen readers. The lane table below the chart contains the same numbers, so
nothing is available only in the chart.

## Python use

```python
from meridian.html_report import render_html, write_html

html = render_html("results/<run>/summary.json")   # the page as text
path = write_html("results/<run>/summary.json")    # writes report.html in the bundle
```
