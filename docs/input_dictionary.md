# Inputs and outputs

## Product-location CSV

Each row represents one independent product at a location. Header names must match
exactly, with no missing, extra or repeated columns. The same location may have
multiple products, but a location-product pair may appear only once.

| Field | Unit / domain | Meaning |
|---|---|---|
| site_id | Safe identifier | Fictional location; starts with a letter |
| product | nitrogen, oxygen, argon | Product stream |
| daily_mean_kg | kg/day, >0 | Arithmetic mean daily demand |
| daily_sd_kg | kg/day, >=0 | Arithmetic standard deviation of daily demand |
| lead_time_days | Integer, 0–30 | Shipment delay |
| initial_inventory_kg | kg, >=0 | Stock available at the start |
| holding_cost_per_kg_day | USD/kg/day, >0 | Positive inventory carrying cost |
| backlog_cost_per_kg_day | USD/kg/day, >0 | Penalty for outstanding demand |
| delivery_cost_per_order | USD/order, >=0 | Fixed charge on each positive order |
| purchase_cost_per_kg | USD/kg, >=0 | Variable order procurement charge |

Limits: at most 100 product-location rows per input file. All numbers must be finite.
Booleans are not valid numerical settings. Daily quantities are continuous masses,
not cylinder counts or standard gas volumes; no density conversion is performed.

## Scenario JSON

| Field | Default | Meaning |
|---|---|---|
| scenario_id | baseline | Safe name used in report labels |
| horizon_days | 60 | Number of simulated days, 1–366 |
| replications | 4 | Training and validation replications each, 1–100 |
| seed | 254 | Reproducibility seed, 0 through 2^32−1 |
| demand_multiplier | 1.0 | Positive multiplier applied to both demand mean and SD |
| service_target | 0.95 | Mean fraction served immediately, 0.5 to 1 inclusive |
| stock_multipliers | 0.75, 1, 1.25, 1.5 | Distinct positive candidate multipliers, 1–20 values |

Unknown and duplicate JSON keys are rejected. Configurations are data, never executable code.

## Result bundle

- `report.md`: concise human-readable comparison and assumptions.
- `summary.json`: scenario inputs, input fingerprint, per-lane results and totals.
- `lanes.csv`: selected stocks, service outcomes, cost components and terminal positions.
- `candidates.csv`: all training candidate costs, fill rates and target outcomes.
- `daily_results.csv`: validation daily quantities and costs for every lane and replicate.
- `COMPLETE.json`: software versions and SHA-256 hashes of the completed result files.

Mean costs cover the stated horizon; they are not automatically monthly or annual
costs. Portfolio fill rate is volume-weighted across validation demand, while the
per-lane mean fill rate averages the individual replication rates. Comparisons
require identical horizons, currencies and lane portfolios. The preserved input
fingerprint and full settings let an analyst identify differences in other assumptions.
