# Demand estimates from history

`python -m meridian forecast --data <lanes.csv> --history <history.csv>` estimates each lane's
daily demand from recent history and prints a table. Add `--apply` to write the estimates
into the product-location CSV.

## History file

| Column | Meaning |
|---|---|
| site_id | Site, as in the product-location CSV |
| product | nitrogen, oxygen or argon |
| date | Day, YYYY-MM-DD |
| demand_kg | Demand that day, kg |

Only days with demand need a row. Missing days count as zero demand.

## Method

- **Mean and SD:** the most recent 28 calendar days.
- **Smoothed level:** exponential smoothing with weight 0.3 on the newest day.
- **Backtest:** each day is forecast from the 28 days before it (one-day-ahead moving
  average); MAPE is the mean absolute percentage error. Shown as "-" when the history is
  shorter than 29 days.

`--apply` replaces `daily_mean_kg` and `daily_sd_kg` for lanes found in the history; other
columns and lanes are unchanged. Keep a copy of the CSV if you may want the old values.
