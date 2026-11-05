# Supplier disruptions

Bulk-gas supply is not perfectly reliable: a plant trip, a driver shortage or bad weather
can stop a supplier from accepting orders for a few days. Meridian can simulate these
outages so that chosen stock levels are tested against them.

## Turning disruptions on

Add two settings to the scenario JSON:

```json
{
  "scenario_id": "outage-study",
  "horizon_days": 90,
  "replications": 8,
  "supplier_disruptions": true,
  "max_outage_days": 5
}
```

| Setting | Default | Limits | Meaning |
|---|---|---|---|
| `supplier_disruptions` | `false` | `true` or `false` | Simulate random supplier outages |
| `max_outage_days` | 5 | Whole days from 1 to 60 | Longest possible single outage |

Without `supplier_disruptions`, results are identical to earlier versions and
`max_outage_days` is ignored.

## How outages are simulated

For each product-location, phase (training or validation) and replication, Meridian draws
an outage schedule for the whole horizon:

- Each day the supplier is available, there is a small chance that an outage starts.
- An outage lasts a random whole number of days from 1 to `max_outage_days`, with every
  length equally likely.
- Outages do not overlap: the next one can only start after the previous one ends.
- A schedule may contain no outages at all, especially for short horizons.

During an outage:

- **No new orders can be placed** for the lane. The base-stock policy keeps tracking its
  inventory position, and on the first day the supplier is back it orders everything
  needed to restore the position, in one delivery.
- **Deliveries already shipped still arrive** on their due day. An outage stops new orders,
  not product already on the road.
- Demand continues as usual. Demand that cannot be served is backlogged and charged the
  backlog penalty, exactly as in an undisrupted run.

Each candidate stock level is tested against the outage schedules, and the chosen level is
evaluated on separate validation schedules, so the policy that wins is the one that copes
best with outages as well as demand variation.

### Reproducibility

Outage schedules are derived from the scenario `seed`, the product-location, the phase and
the replication. Running the same scenario twice gives the same schedules and the same
results, and two scenarios with the same seed face the same outages, so a comparison
between them is not distorted by different luck.

## Checking the schedules

`meridian outages` prints the schedules a scenario would simulate for one lane, without
running the simulation:

```bash
python -m meridian outages --data data/synthetic_sites.csv --config studies/outage.json \
  --lane Harbor:nitrogen
```

```json
[
  {
    "replication": 1,
    "outages": [{"first_day": 23, "days": 4}],
    "summary": {
      "outages": 1,
      "offline_days": 4,
      "offline_share": 0.044,
      "longest_outage_days": 4
    }
  }
]
```

Days are numbered from 1, matching `daily_results.csv`. Add `--phase training` to see the
schedules used to choose stock levels instead of the validation schedules.

The command uses the scenario's `horizon_days`, `replications` and `max_outage_days`;
`supplier_disruptions` does not need to be enabled to preview schedules.

Add `--summary` for statistics across all replications instead of each schedule: mean
number of outages, mean offline share of the horizon, how many replications had at least
one outage and the longest outage drawn.

To keep the schedules for later analysis, `--csv <file>` writes every lane's schedules for
the chosen phase to a new CSV with the columns `lane`, `phase`, `replication`,
`first_day` and `days` (one row per outage). An existing file is never replaced.

## Measuring the impact

`meridian disruption-impact` runs the scenario twice, without and with outages, and
compares each lane:

```bash
python -m meridian disruption-impact --data data/synthetic_sites.csv --config studies/outage.json
```

| Field | Meaning |
|---|---|
| `base_stock_kg` / `base_stock_with_outages_kg` | Stock level chosen without and with outages |
| `mean_cost` / `mean_cost_with_outages` | Validation mean cost of each run |
| `cost_increase` | Cost with outages minus cost without |
| `fill_rate` / `fill_rate_with_outages` | Validation fill rate of each run |
| `target_met_with_outages` | Whether the service target was met in training with outages |

Add `--format table` for a Markdown table. The scenario's `supplier_disruptions` setting
is ignored by this command; both runs use
its `max_outage_days`. A higher chosen stock level with outages shows the extra inventory
needed to keep the service target despite supply risk.

## Stress testing a stock level

Random outages show average behaviour. `meridian outage-stress` instead tests one stock
level against a single outage of each chosen length, starting on the same day in every
validation replication:

```bash
python -m meridian outage-stress --data data/synthetic_sites.csv --config config/baseline.json \
  --lane Harbor:nitrogen --base-stock 3000 --days 1 3 5 10 --start-day 20
```

Each row gives the outage length, the mean fill rate and cost, the largest backlog in any
replication and the mean recovery time: the days from the end of the outage until backlog
is cleared (0 when no backlog remained). An outage that would run past the end of the
horizon is cut off at the last day.

Add `--format table` for a Markdown table. With `--find-stock`, the command instead
searches for the lowest stock level that still meets the service target despite each
outage length. It tries the scenario's usual candidate levels and their doubles, lowest
first, and reports the first level that meets the target together with every level it
tested; `base_stock_kg` is `null` when none is enough:

```bash
python -m meridian outage-stress --data data/synthetic_sites.csv --config config/baseline.json \
  --lane Harbor:nitrogen --days 3 7 --find-stock
```

Either `--base-stock` or `--find-stock` is required.

Stress tests do not draw random outages, so they are repeatable whatever the scenario's
disruption settings.

## Results

Runs with disruptions produce the same files as other runs. `summary.json` records
`supplier_disruptions` and `max_outage_days` in its settings, so the input fingerprint
differs from an undisrupted run of the same scenario. `report.md` and `summary.json`
add model notes describing the outage assumptions.

Outage days are visible in `daily_results.csv` as days with no order even though
inventory is below the base-stock level, usually followed by one large order.

## Interpreting results

- Compare an undisrupted run with a disrupted run of the same scenario (same seed) using
  `meridian compare`. The cost difference is the price of supply risk at the chosen stock
  levels.
- Lanes with long lead times are affected most: product ordered after an outage arrives
  even later.
- If a lane misses its service target only with disruptions, a higher stock multiplier or
  a second supplier (outside this model) is worth studying.
- Outages are independent between lanes. A shared plant failure affecting several lanes
  at once is not modelled.

## Python use

```python
import random

from meridian.disruptions import draw_outages, offline_days, simulate_disrupted

outages = draw_outages(random.Random(7), horizon_days=60, max_outage_days=3)
offline = offline_days(outages, 60)
trial = simulate_disrupted(lane, 2500.0, demands, offline)
print(trial.fill_rate, trial.total_cost)
```

`fixed_outage(start_day, days, horizon_days)` builds the offline flags for a single outage,
and `recovery_days(trial, offline)` measures recovery after each outage in a trial.
`schedule_statistics(settings, lane)` summarises a scenario's schedules for one lane.

`outage_summary(outages, horizon_days)` gives the number of outages, offline days, offline
share of the horizon and the longest outage.

## Frequently asked questions

**How often do outages happen?** Rarely: on a typical 90-day horizon most lanes see one
or two outages, and some replications see none. Use `meridian outages --summary` to check
the rate for a scenario before relying on the results, and increase `replications` when
outages are rare, so that the averages include enough of them.

**Do outages affect every lane at the same time?** No. Schedules are drawn separately for
each product-location, so a site can lose its nitrogen supplier while its oxygen supplier
keeps delivering. Shared failures are outside the current model.

**Why did the chosen stock level go down with outages?** Candidates are compared on the
same demand but different outage schedules, and the training target is a mean over
replications. When two levels are close in cost, an unlucky schedule can tip the choice.
Increase `replications` or compare with `outage-stress`, which uses fixed outages.

**Are orders placed during an outage lost?** No order is placed while the supplier is
offline, so nothing is lost; the shortfall is ordered in full when the supplier returns.
Purchase and delivery costs are charged on that day.

**Can I model a planned shutdown?** Use `outage-stress` with `--start-day` set to the
first shutdown day and `--days` to its length. It shows the effect of that exact outage on
every validation replication.

**Do outages change `daily_results.csv`?** The columns are unchanged. Outage days show up
as days without orders while inventory is below the base-stock level.
