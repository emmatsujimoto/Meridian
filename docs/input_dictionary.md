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
| safety_stock_policy | statistical | How the base-stock grid is centred: `statistical` (newsvendor level from the service target), `fixed` or `percent` |
| safety_stock_kg | 0 | Safety stock in kg for every lane, used by the `fixed` policy |
| safety_stock_percentage | 0 | Safety stock as a percentage (0-500) of each lane's lead-time demand, used by the `percent` policy |
| service_target | 0.95 | Mean fraction served immediately, >0 and <=1 |
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

## Safety-stock policies

The candidate base-stock grid is centred on mean demand over the protection period (lead
time plus one review day) plus a safety stock. `safety_stock_policy` chooses how that
safety stock is set:

| Policy | Safety stock | When to use |
|---|---|---|
| `statistical` | Newsvendor level from backlog and holding costs, minus mean demand | Default; balances the two costs |
| `fixed` | `safety_stock_kg` for every lane | Matching an existing rule of thumb, e.g. "always keep 500 kg" |
| `percent` | `safety_stock_percentage` percent of the lane's lead-time demand | Scaling protection with lane size |

The scenario's `stock_multipliers` are then applied to the centre, exactly as before, and
each candidate is simulated; the policy sets where the search starts, not the final level.

Example: Harbor nitrogen has 800 kg/day mean demand and a 2-day lead time, so lead-time
demand over the 3-day protection period is 2,400 kg. With `safety_stock_percentage` 20,
the safety stock is 480 kg and the grid centre is 2,880 kg.

`python -m meridian policies --data ... --config ...` prints each lane's lead-time demand
and safety stock under the scenario's policy, then runs the scenario under every policy
with the same seed and reports cost, fill rate and how many lanes meet the target.

### Choosing a policy

- Start with `statistical`. It reacts to each lane's cost balance: lanes where running
  short is expensive relative to holding stock get more protection.
- Use `fixed` to reproduce a site rule such as "keep one truckload in reserve" and see what
  it costs compared with the statistical level.
- Use `percent` when lanes differ greatly in size and a single kg figure would be too much
  for small lanes and too little for large ones.

The `policies` command prints a note when a setting is unused (for example
`safety_stock_kg` with the statistical policy) or when the chosen policy would hold no
safety stock at all.

### Reading the policies output

```text
Harbor:nitrogen: lead-time demand 2,400 kg, safety stock 413 kg (statistical)
...
statistical: cost $60,093, fill rate 99.98%, 6 lanes meet the target
fixed: cost $59,410, fill rate 99.12%, 4 lanes meet the target
percentage: cost $61,250, fill rate 99.99%, 6 lanes meet the target
```

The first block shows the grid centre for each lane under the scenario's own policy. The
second block runs the whole scenario once per policy. Figures are illustrative; a cheaper
policy that leaves lanes below the target is not a like-for-like saving.
