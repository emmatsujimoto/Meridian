# Variable supplier lead times

By default every lane has a fixed lead time: an order placed on day *d* with lead time *L*
arrives on day *d + L*. Real supply is less regular. Trucks are delayed, and plant
outages push deliveries back. Setting `lead_time_cv` in a scenario file makes every order's
lead time random, so policies are chosen and validated against irregular supply.

```json
{
  "scenario_id": "variable_lead_times",
  "lead_time_cv": 0.4
}
```

Leave `lead_time_cv` out (or set it to `null`) for fixed lead times; the original
Stockpyl-based simulation is then used unchanged.

## Choosing a CV from delivery records

If you have order and delivery dates, estimate the CV instead of guessing it:

```python
from meridian.leadtime import estimate_cv, load_delivery_history

history = load_delivery_history("deliveries.csv")
estimate = estimate_cv(history)
print(estimate["suggested_lead_time_cv"])
```

The CSV needs `site_id`, `product`, `order_date` and `delivery_date` columns (ISO dates,
`YYYY-MM-DD`); other columns are ignored. Each lane with at least five deliveries gets its
own CV (sample SD divided by mean lead time). The suggested scenario value is the
delivery-weighted average of the lane CVs, capped at 2. Lanes whose CVs differ widely are a
sign that one scenario-wide CV is too coarse; compare them in `estimate["lanes"]`.

Rows with a delivery before the order date, unknown products or malformed dates are
rejected with the row number, so data problems are fixed at the source.

## Distribution

Each order's lead time is drawn from a **lognormal distribution** whose arithmetic mean is
the lane's `lead_time_days` and whose coefficient of variation (standard deviation divided
by mean) is `lead_time_cv`. The lognormal is always positive and right-skewed: most orders
arrive close to the planned lead time, and a few arrive much later. Draws are rounded to
whole days.

The lognormal parameters follow from the mean *m* and CV *c*:

- σ² = ln(1 + c²)
- μ = ln(m) − σ² / 2

| `lead_time_cv` | Lead time 2 days: SD | Share of orders later than 3 days (approx.) |
|---|---|---|
| 0.2 | 0.4 days | 2% |
| 0.4 | 0.8 days | 11% |
| 0.8 | 1.6 days | 19% |

Lanes with a zero lead time keep same-day delivery whatever the CV.

To keep a single extreme draw from leaving an order in transit for most of a run, lead
times are capped at the lognormal 99.9th percentile.

## Reproducibility

Lead times are seeded from the scenario seed, the lane, the phase (training or
validation), the replication and the order's day. The same scenario therefore gives the
same lead times on every run and machine, independent of row order or Python's hash seed.
Training and validation use different lead-time samples, as they do for demand.

## Effect on the policy

The candidate base-stock grid is centred on demand over the protection period. With
variable lead times, the variance of that demand includes the lead-time variance:

Var = (daily SD)² × (L + 1) + (daily mean)² × (lead-time SD)²

so a higher `lead_time_cv` moves the grid towards higher base stock. Every candidate is
then simulated with the sampled lead times, exactly as with fixed lead times.

## Simulation

With variable lead times, Meridian uses its own daily base-stock simulation instead of
Stockpyl's, because Stockpyl's single-stage simulator supports a fixed lead time only. It
follows the same event order and cost conventions:

1. observe today's demand;
2. order enough to bring the inventory position (stock on hand minus backlog plus stock
   in transit) back to the base stock;
3. receive every shipment due today or earlier;
4. serve demand from stock, backlogging the rest;
5. charge holding and backlog costs on end-of-day stock, and delivery and purchase costs
   when an order is placed.

Orders can overtake each other: an order with a short lead time may arrive before an
earlier order with a long one. With every lead time equal to the lane's lead time, results
are identical to the Stockpyl-based simulation (checked by the test suite).

## Outputs

With variable lead times, each lane in `summary.json` and `lanes.csv` gains five columns,
measured over the validation trials:

| Column | Meaning |
|---|---|
| `orders` | Orders placed across all validation replications |
| `mean_realised_lead_time_days` | Mean lead time of those orders, after the cap |
| `max_realised_lead_time_days` | Longest lead time drawn |
| `late_order_share` | Share of orders whose lead time exceeded the lane's planned lead time |
| `orders_after_horizon` | Orders still in transit when the run ended (they are still charged) |

A lane that placed no orders shows `orders` 0 and empty statistics. `report.md` adds a
"Lead times" table with the same figures. Runs with fixed lead times produce exactly the
same files as before.

## Worked example

Harbor nitrogen has a planned lead time of 2 days. With `lead_time_cv` 0.4 the lead-time
SD is 0.8 days. Its daily demand has mean 800 kg and SD 160 kg, so over the 3-day
protection period:

- fixed lead time: SD of demand = 160 × √3 ≈ 277 kg;
- variable lead time: SD = √(160² × 3 + (800 × 0.8)²) ≈ 697 kg.

The candidate grid therefore centres on a higher base stock, and the simulation then
tests whether the extra stock pays for itself in avoided backlog.

## Comparing variability levels

`meridian.planning.lead_time_sensitivity(lanes, settings, cvs)` re-runs a scenario for
up to ten CVs (use `None` for fixed lead times) with the same seed and returns, for each,
the mean total cost, portfolio fill rate and total base stock. Because demand traces are
identical across the runs, differences come from lead-time variability alone.

```python
from meridian.inputs import load_lanes, load_settings
from meridian.planning import lead_time_sensitivity

lanes = load_lanes("data/synthetic_sites.csv")
settings = load_settings("config/quickstart.json")
for row in lead_time_sensitivity(lanes, settings, (None, 0.2, 0.4, 0.8)):
    print(row)
```

`compare` lists each report's `lead_time_cv` (empty for fixed lead times), so a
comparison of runs with different lead-time assumptions is visible at a glance, and
`summary.json` gains a model note describing the assumption.

## How this is checked

The test suite confirms that:

- the lognormal parameters reproduce the requested mean and CV exactly;
- the same scenario gives the same lead times on every run, and different phases,
  replications and seeds give different ones;
- with every lead time equal to the lane's lead time, the variable simulation matches the
  Stockpyl-based one day by day (stock, backlog, orders, service and cost) for lead
  times of 0, 1 and 3 days and several base-stock levels;
- later deliveries lower service, and the candidate grid rises with the CV;
- runs with fixed lead times are unchanged.

## Questions

**Should I use the CV of my supplier's quoted lead times?** No: use the CV of actual
deliveries, from order to receipt. Quoted lead times usually understate variability.

**Why are some lanes unaffected?** Lanes with a zero lead time keep same-day delivery,
and lanes that rarely order (large starting stock, short horizon) see few draws.

**Does variability change the demand traces?** No. Demand samples are identical with and
without `lead_time_cv`, so cost differences come from lead times alone.

## Limits

- Lead times are independent between orders. Disruptions that delay several orders at
  once are not modelled.
- Each lane's lead-time CV is the scenario's `lead_time_cv`; per-lane values are not yet
  supported.
- Rounding to whole days slightly changes the mean when the CV is large.
