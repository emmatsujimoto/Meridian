# Rolling-horizon re-planning

The main model chooses one base-stock level per product-location for the whole horizon,
using training demand. In practice planners revisit stock levels as demand changes. The
`rolling` command tests that practice: it re-optimises each lane's base stock at regular
review points from a forecast of recent demand, and compares the result with the static
policy on the same validation demand.

```bash
python -m meridian rolling --data data/synthetic_sites.csv --config config/quickstart.json \
    --review-days 7 --output results/rolling
```

## How a rolling plan works

For each validation demand trace:

1. **Review points.** The base stock is re-optimised once at the start of each review
   period (`--review-days`, default 7), and held until the next review.
2. **Forecast.** The forecast mean and standard deviation come from the most recent 14
   days of demand. Until three days of history exist, the lane's configured demand
   (times the scenario's demand multiplier) is used.
3. **Re-optimisation.** The same candidate grid as the static policy is built around the
   forecast. Each candidate is simulated on 12 synthetic traces drawn from the forecast,
   and the cheapest candidate meeting the service target is chosen (or, if none does, the
   one with the highest service), exactly as the static policy chooses.
4. **Simulation.** Demand is served with the base stock in force each day, using the same
   event order and cost conventions as the main simulation: observe demand, order up to
   the base stock, receive due shipments, serve demand, charge costs.

Synthetic traces for each review are seeded from the scenario seed and the day, so a
rolling run is reproducible.

## Output

`rolling.csv` has one row per product-location:

| Column | Meaning |
|---|---|
| `lane` | Product-location key |
| `static_base_stock_kg` | Base stock chosen by the static policy |
| `static_mean_cost`, `static_fill_rate` | Static policy, mean over validation traces |
| `rolling_mean_cost`, `rolling_fill_rate` | Rolling policy on the same traces |

The command prints the same comparison for each lane.

`rolling_plan.csv` lists, for validation replication 1, every day on which a lane's base
stock changed, with the forecast mean and standard deviation behind the new level:

| Column | Meaning |
|---|---|
| `lane` | Product-location key |
| `day` | Day the new level took effect |
| `forecast_mean_kg`, `forecast_sd_kg` | Forecast of daily demand used for the re-plan |
| `base_stock_kg` | Base stock in force from that day |

The first row for each lane is its starting level.

## Worked example

Harbor nitrogen (mean 800 kg/day, SD 160 kg) with weekly reviews over 21 days:

| Review | Days | History used | Forecast mean | Effect |
|---|---|---|---|---|
| 1 | 1–7 | none (configured demand) | 800 kg | Same grid as the static policy |
| 2 | 8–14 | days 1–7 | e.g. 840 kg | Level rises if the first week ran high |
| 3 | 15–21 | days 1–14 | e.g. 790 kg | Level eases back as the window grows |

Each review uses only the demand already seen; the level then holds for seven days.

## When rolling re-planning helps

- **Demand that drifts or is seasonal.** A static level fitted to training demand can be
  too high or too low for part of the horizon; re-planning follows the change.
- **Short histories.** Early reviews fall back on the configured demand, so the first
  review period behaves like the static policy.

With stationary synthetic demand, as in the shipped examples, rolling plans mostly add
noise: forecasts from 14 days of data vary more than the true demand does. Expect similar
or slightly higher cost, and use the comparison to judge whether the extra planning effort
pays off for a given lane.

## Choosing the review period

| Review period | Effect |
|---|---|
| 1 day | Reacts fastest, but levels change daily and follow noise |
| 7 days | Weekly planning cycle; a reasonable default |
| 14–30 days | Close to the static policy; little reaction to change |

Review periods from 1 to 90 days are accepted.

## Run time

Each review simulates the candidate grid on 12 traces, so run time grows with the number
of reviews: halving the review period roughly doubles it. A 60-day horizon with weekly
reviews runs about 9 re-optimisations per trace.

## Limits

- The forecast is a simple moving mean and standard deviation; there is no trend or
  seasonality model.
- Changing the base stock does not cancel orders already placed.
- Training demand is not used by the rolling policy beyond the configured fallback.
