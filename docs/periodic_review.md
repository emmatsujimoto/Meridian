# Periodic-review (R, s, S) policy

By default Meridian reviews every product-location daily and orders back up to a
base-stock level. Many bulk-gas customers are instead visited on a fixed schedule: a
planner checks the tank every few days and only orders when it is low. The
periodic-review policy models that practice.

## How the policy works

The policy has three parameters:

| Symbol | Setting | Meaning |
|---|---|---|
| R | `review_period_days` | Days between reviews |
| s | reorder point (chosen per lane) | Order only when the inventory position is at or below this level |
| S | order-up-to level (chosen per lane) | Each order brings the inventory position back up to this level |

The *inventory position* is stock on hand plus stock on order, minus backlog. On a review
day:

1. The day's demand is observed.
2. If the inventory position after that demand is **at or below s**, an order is placed for
   S minus the position. Otherwise no order is placed.
3. Deliveries that are due arrive, demand is served from stock, and unserved demand is
   backlogged.
4. Holding and backlog costs are charged at the end of the day.

Between review days no orders are placed, however low the stock falls. Delivery and
purchase costs are charged when an order is placed, exactly as for the base-stock policy.

The first review is on day 1 of the horizon, then every R days (days 1, 8, 15, ... for a
weekly review).

With R = 1 and s = S, the policy orders every day to restore the position to S, which is
the base-stock policy. The simulation reproduces the base-stock results exactly in that
case; the tests check this for several lead times and levels.

### Pack sizes

Some products are delivered in fixed quantities, such as whole trailer loads. Set
`pack_size_kg` to the size of one pack and every order is placed in whole packs, using
the smallest number of packs that brings the position up to S. A pack size of 0 (the
default) places orders of any size.

## Using the policy in a scenario

Add the policy settings to the scenario JSON:

```json
{
  "scenario_id": "weekly-review",
  "horizon_days": 90,
  "replications": 8,
  "policy": "periodic-review",
  "review_period_days": 7,
  "pack_size_kg": 0,
  "reorder_fractions": [0.6, 0.8, 1.0]
}
```

| Setting | Default | Limits |
|---|---|---|
| `policy` | `base-stock` | `base-stock` or `periodic-review` |
| `review_period_days` | 7 | Whole days from 1 to 90 |
| `pack_size_kg` | 0 | Zero or more; 0 means no pack rounding |
| `reorder_fractions` | `[0.6, 0.8, 1.0]` | 1-10 distinct values above 0 and at most 1 |

`review_period_days`, `pack_size_kg` and `reorder_fractions` are ignored by the
base-stock policy, so they can stay in a shared configuration file.

### How s and S are chosen

Each lane's policy is chosen the same way as base-stock levels:

1. Candidate order-up-to levels S are centred on a normal newsvendor estimate of demand
   over the review period plus the lead time, then scaled by `stock_multipliers`.
2. Each S is paired with reorder points s at each of the `reorder_fractions` of S. A
   fraction of 1 reorders at every review that finds the position below S.
3. Every (s, S) pair is simulated on the training demand samples.
4. Among pairs meeting the service target, the lowest mean cost wins, ties going to the
   lower S. If none meets the target, the highest fill rate wins.
5. The chosen pair is evaluated on separate validation samples.

The number of candidates is the number of stock multipliers times the number of reorder
fractions, so large grids take proportionally longer to run.

## Results

For periodic-review runs, `summary.json` and `lanes.csv` gain four columns per lane:

| Column | Meaning |
|---|---|
| `policy` | `periodic-review` |
| `reorder_point_kg` | Chosen reorder point s |
| `review_period_days` | Review period R |
| `mean_orders` | Orders per validation replication |

`base_stock_kg` holds the chosen order-up-to level S. Base-stock runs are unchanged and
do not include these columns.

`report.md` names the policy under the fill rate, and its table shows each lane's level
as `s=..., S=...`.

## Trying a single policy

`meridian periodic` simulates one (R, s, S) policy for one lane on the scenario's
training demand, without searching a grid. It is useful for checking a policy suggested
by a planner:

```bash
python -m meridian periodic --data data/synthetic_sites.csv --config config/baseline.json \
  --lane Harbor:nitrogen --reorder-point 3000 --order-up-to 6000 --review-days 7
```

```json
{
  "lane": "Harbor:nitrogen",
  "review_period_days": 7,
  "reorder_point_kg": 3000.0,
  "order_up_to_kg": 6000.0,
  "pack_size_kg": 0.0,
  "replications": 4,
  "mean_cost": 11872.4,
  "mean_fill_rate": 0.957,
  "meets_target": true,
  "mean_orders": 8.5,
  "mean_order_kg": 5534.2
}
```

`--review-days` and `--pack-size` default to the scenario's settings.

`first_trial` in the output adds operational measures for the first training replication:
the number of reviews and orders, reviews skipped because the position was above s, the
mean order size and gap between orders, stockout days and peak inventory.

## Comparing with base stock

`meridian compare-policies` chooses both a base-stock policy and a periodic-review policy
for every lane, using the same training and validation demand, and prints them side by
side:

```bash
python -m meridian compare-policies --data data/synthetic_sites.csv --config config/baseline.json
```

Each row gives the base-stock level and its validation cost and fill rate, the chosen
(s, S) pair with its cost and fill rate, and `cost_difference` (periodic-review cost minus
base-stock cost). The scenario's `policy` setting is ignored; its `review_period_days`,
`pack_size_kg` and `reorder_fractions` are used for the periodic-review side.

Add `--format table` to either command for a Markdown table instead of JSON:

```text
| Product-location | Base stock (kg) | Base-stock cost | Base-stock fill | s (kg) | S (kg) | Periodic cost | Periodic fill | Difference |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Harbor:nitrogen | 2,437 | 3,980.12 | 96.10% | 4,028 | 6,712 | 3,512.40 | 97.20% | -467.72 |
```

## Choosing a review period

`meridian review-sweep` chooses a periodic-review policy for one lane at several review
periods, which shows how much reviewing less often costs:

```bash
python -m meridian review-sweep --data data/synthetic_sites.csv --config config/baseline.json \
  --lane Summit:argon --periods 1 3 7 14
```

Each row has the review period, the chosen s and S, whether the training target was met,
and the validation mean cost, fill rate and orders per replication. Up to 20 periods can be
given; duplicates are ignored and rows are sorted by period.

## Interpreting periodic-review results

- A longer review period needs a higher S, because each order must cover demand until the
  delivery after the *next* review. Expect higher holding cost and fewer deliveries.
- A lower s (smaller reorder fraction) skips reviews when stock is still adequate, which
  saves delivery cost when deliveries are expensive relative to holding.
- Comparing a periodic-review run with a base-stock run that uses the same seed shows the
  cost of reviewing less often. Use `meridian compare` on the two `summary.json` files.
- Large pack sizes make order quantities lumpy. Check `mean_orders` and the ending
  inventory when using them.

## Python use

```python
from meridian.policies import simulate_periodic

trial = simulate_periodic(lane, 7, 3000.0, 6000.0, demands, pack_size_kg=0.0)
print(trial.total_cost, trial.fill_rate)
```

The arguments are the lane, the review period R in days, the reorder point s in kg, the
order-up-to level S in kg and the daily demands. `offset_days` moves the first review
later in the horizon (from 0 to R - 1 days).
