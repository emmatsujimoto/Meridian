# Demand sensing

The daily means in the lane CSV are a plan: they describe expected demand when the
scenario was set up. Demand sensing updates that plan with what customers actually drew
recently, so the next run starts from a forecast that reflects current conditions.

## How the forecast is updated

Meridian uses simple exponential smoothing. The planned daily mean is the starting
forecast, and each day of recent sales is applied in date order:

```text
forecast = alpha × newest sale + (1 − alpha) × previous forecast
```

`alpha` weights the newest observation. With `alpha = 0.3`, each new day of sales moves
the forecast 30% of the way from the previous forecast towards that day's sales, so a
sustained change in demand is picked up within a week or two while a single unusual day
has limited effect.

A lane without any recent sales keeps its planned mean. Sales equal to the plan leave the
forecast unchanged.

The standard deviation is scaled by the same factor as the mean, so the coefficient of
variation in the lane CSV is kept. Lead times, costs and starting inventory are unchanged.

## The sales file

Recent sales are a CSV with exactly these columns:

| Column | Meaning |
|---|---|
| `date` | Calendar date in ISO format, for example `2026-10-14` |
| `site_id` | Site, matching the lane CSV |
| `product` | `nitrogen`, `oxygen` or `argon` |
| `sales_kg` | Kilograms delivered to customers that day; zero or more |

Rules:

- Every row must match a product-location in the lane CSV.
- Each product-location may have at most one row per date.
- Rows may be in any order; they are sorted by date before smoothing.
- Days without a row are skipped rather than treated as zero sales. Add a row with
  `sales_kg` of 0 for days when a customer genuinely took nothing.
- At most 20,000 rows are read.

Example:

```text
date,site_id,product,sales_kg
2026-10-12,Harbor,nitrogen,846
2026-10-13,Harbor,nitrogen,912
2026-10-14,Harbor,nitrogen,877
2026-10-14,Summit,argon,131
```

## Running it

```bash
python -m meridian sense --data data/synthetic_sites.csv --sales sales/october.csv
```

The command prints planned and sensed demand per lane:

```text
| Product-location | Planned (kg/day) | Sensed (kg/day) | Change | Days of sales | Last sale |
|---|---:|---:|---:|---:|---|
| Harbor:nitrogen | 800.0 | 851.3 | +6.4% | 3 | 2026-10-14 |
| Summit:argon | 120.0 | 123.3 | +2.8% | 1 | 2026-10-14 |
```

Add `--format json` for one object per lane with `lane`, `planned_kg`, `sensed_kg`,
`change`, `observations` and `last_sale` (`null` when a lane has no sales).

To run a scenario on the sensed forecast, write the adjusted lanes to a new CSV and use it
as `--data`:

```bash
python -m meridian sense --data data/synthetic_sites.csv --sales sales/october.csv \
  --write data/sensed_october.csv
python -m meridian run --data data/sensed_october.csv --config config/baseline.json
```

`--write` never replaces an existing file. The written file has the same columns as the
original lane CSV and passes `meridian validate`.

## Comparing planned and sensed runs

Run the same scenario on the original and the sensed lanes, then compare:

```bash
python -m meridian run --data data/synthetic_sites.csv --config config/baseline.json
python -m meridian run --data data/sensed_october.csv --config config/baseline.json
python -m meridian compare results/<plan-run>/summary.json results/<sensed-run>/summary.json
```

Both runs use the same seed, so cost and fill-rate differences come from the change in
forecast rather than from different random draws. The two runs have different
`input_sha256` values because their lane inputs differ.

## Limits

- Smoothing gives a level forecast. Trends and weekly or seasonal patterns are not
  modelled; a steadily growing lane is under-forecast.
- Sales are not the same as demand: a stockout limits sales, so sensing during a supply
  problem understates true demand.
- Only the mean is sensed from sales; the deviation is scaled, not re-estimated.

## Python use

```python
from meridian.inputs import load_lanes
from meridian.sensing import adjusted_lanes, sense_demand, sensing_table

lanes = load_lanes("data/synthetic_sites.csv")
sensed = sense_demand(lanes, "sales/october.csv")
print(sensing_table(sensed))
new_lanes = adjusted_lanes(lanes, sensed)
```

`largest_changes(sensed, count)` returns the lanes whose forecast moved most, ignoring
lanes without sales, and `sensed_rows(sensed)` gives the JSON rows.

Each `SensedLane` gives `planned_kg`, `sensed_kg`, the number of sales days used, the
date of the last sale and `change`, the relative change from plan.
