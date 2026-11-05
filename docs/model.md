# Model and workflow

## Fictional business case

Meridian Industrial Gases supplies bulk nitrogen, oxygen and argon to fictional
industrial locations. An internal analyst wants to compare inventory investment,
unmet demand and replenishment costs. Nitrogen can represent an inerting or food
processing supply; oxygen and argon represent other industrial product streams.
The application uses mass quantities only and contains no process-engineering guidance.

The example has three locations and six independent product-location streams.
All numerical inputs are illustrative planning assumptions, not observed company data.
USD is the common currency and kg is the common quantity unit.

## Stochastic inventory experiment

- A period is one day. Lead times are nonnegative integer days.
- Each lane has an unlimited external replenishment source with deterministic lead time.
- Each day the model receives demand information, places replenishment orders,
  receives due shipments, serves demand and calculates end-of-day costs using
  Stockpyl's documented event order. Zero shipment lead time means same-day arrival.
- Demand is nonnegative lognormal with configured arithmetic mean and standard deviation.
  A zero standard deviation gives deterministic demand.
- Day-to-day demand and product-location streams are independent. Seasonality,
  shared disruptions and cross-location demand correlation are not modeled.
- The chosen policy orders to restore the configured inventory position. This is
  not a truck-routing optimizer and does not combine product shipments.
- Unserved demand remains backlogged. The backlog penalty is charged per kg per day.
  No emergency delivery or lost-sales interpretation is implied.
- Holding cost is charged per kg of positive end-of-day inventory per day.
- Fixed delivery cost and variable purchase cost are charged when an order is placed.
  This includes orders arriving after the modeled horizon. Starting inventory is a
  sunk asset, and no terminal inventory salvage value is credited.
- Ending inventory and backlog are reported so boundary effects remain visible.

## Site storage capacity

Each product-location may record the most product its site can store, in the optional
`storage_capacity_kg` column of the lane CSV. The column can be left out entirely, and a
blank cell means the capacity is not recorded for that row. A recorded capacity must be
positive, and the starting inventory must fit within it.

Capacity is only applied when the scenario JSON sets `"enforce_capacity": true`. Without
that setting, recorded capacities are ignored and results are identical to earlier
versions, so existing scenarios do not change.

When capacity is enforced:

- A delivery that would take end-of-day storage above capacity is only partly received.
  The remainder stays at the supplier until space is available, as described in the
  scenario request.
- Orders are still placed to restore the base-stock inventory position. Purchase and
  delivery costs are charged when an order is placed, as in uncapped runs.
- Holding cost applies only to product received at the site.
- Demand is served from stock on hand after the day's deliveries. Unserved demand is
  backlogged as usual.
- Backlogged demand does not occupy storage, so deliveries that clear a backlog are not
  limited by capacity.

Stockpyl's base-stock simulator has no storage limit. Capacity runs therefore use a daily
loop in `meridian.engine` that follows the same event order (observe demand, place the
order, receive due deliveries, serve demand, charge end-of-day costs). With capacity well
above any inventory level the loop reproduces the Stockpyl results exactly; the tests check
this for several lead times and base-stock levels.

Choosing a base-stock level above a site's capacity is allowed. The candidate grid is not
trimmed to capacity, because the simulation shows the effect of such a level directly:
the site fills up and the excess waits at the supplier.

`meridian.engine.capacity_utilisation` reports a trial's peak end-of-day inventory as a
share of the site's capacity. Values close to one mean the site was full at some point
during the horizon and a larger tank or more frequent, smaller deliveries may be worth
studying.

### Capacity reporting

`meridian.planning.capacity_report(result)` summarises storage use for every lane with a
recorded capacity, using the chosen policy's validation trials:

| Field | Meaning |
|---|---|
| `storage_capacity_kg` | The site's recorded capacity |
| `base_stock_kg` | Chosen base-stock level |
| `base_stock_above_capacity` | The chosen level is larger than the site can hold |
| `mean_peak_utilisation` | Peak end-of-day inventory divided by capacity, averaged over trials |
| `max_peak_utilisation` | The highest single-trial peak utilisation |
| `mean_days_at_capacity` | Days per trial on which the site was full |
| `capacity_enforced` | Whether the scenario set `enforce_capacity` |

The report is also useful for uncapped runs: a peak utilisation above one shows how far
the unconstrained policy would overfill the site, before deciding whether to enforce
capacity. Lanes without a recorded capacity are left out of the report.

`meridian.engine.days_at_capacity` and `meridian.engine.capacity_summary` give the same
measures for individual trials.

Example lane CSV with capacities:

```text
site_id,product,...,purchase_cost_per_kg,storage_capacity_kg
Harbor,nitrogen,...,0.18,12000
Harbor,oxygen,...,0.21,
```

Example scenario JSON:

```json
{"scenario_id": "capped", "horizon_days": 90, "enforce_capacity": true}
```

### Checking a capacity study

A practical sequence for a capacity study:

1. Add `storage_capacity_kg` for the sites of interest and run the scenario *without*
   `enforce_capacity`. Use `capacity_report` to see which chosen policies would overfill
   their sites.
2. Run the same scenario with `"enforce_capacity": true` and a different `scenario_id`.
   Use `meridian compare` to compare total cost and fill rate between the two runs; both
   runs share the same seed, so differences come from the capacity limit and not from
   different demand samples.
3. For lanes that lose service when capped, try a larger capacity or a shorter lead time
   and compare again.

Because both runs use the same lane CSV, their `input_sha256` values differ only through
the `enforce_capacity` setting, which makes the pair easy to identify later.

Limitations: capacity is per product-location, not shared between products at the same
site, and there is no cost for product waiting at the supplier.

## Policy choice and validation

A normal newsvendor approximation to protection-period demand centers a finite
grid of base-stock levels. It is a grid construction heuristic, not an assertion
that demand is normal. All candidates face the same lognormal training samples.

Among candidates achieving the requested mean training fill rate, choose the
lowest mean total cost, breaking ties toward lower stock. If no candidate meets
the target, choose the highest fill rate, then lowest cost, and report that the
training target was unmet. There is no claim of a global continuous optimum.

Run the selected candidate on separate validation samples. A target met in
training is not guaranteed in validation. The report displays both outcomes.
The cost standard deviation describes variation across simulated replications,
not confidence in real-world performance. Four baseline replications are a small
demonstration, not a production statistical study.

Stable seeds depend on the configured seed, lane identifier and training/validation
phase. Reordering the CSV does not change results. Reusing the same seed across
scenarios provides aligned underlying random draws for comparisons.

## Separate analytical benchmarks

EOQ assumes steady demand, positive holding cost and a fixed ordering cost. Its
reported daily cost includes ordering and cycle-stock holding only. At zero setup
cost the continuous-replenishment limit is reported explicitly.

Wagner-Whitin computes a known-demand lot-sizing benchmark with zero initial
stock, no capacity limit and same-day replenishment. It includes holding,
ordering and purchase costs. It is not directly interchangeable with the
stochastic base-stock results, which use the configured initial inventory and lead time.

## Scope and access

The application reads local CSV/JSON and writes local result folders. It has no
authentication service, database, customer API, plant connection or web endpoint.
There are no secrets to configure. Input schemas reject unknown fields, duplicate
lanes and nonfinite or negative quantities. Scenario identifiers cannot contain paths.

Users choose an output directory explicitly. A unique subdirectory prevents
overwriting previous runs. A completion manifest is written last; a folder without
that manifest is an incomplete run and should not be used for comparison.

## Future extensions

Correlated demand, tank capacity, realistic delivery schedules or fleet constraints
would require separate requirements and validation. They are not implicit features
of this baseline. A future review-evaluation exercise can create controlled changes
in branches without changing the clean starting code.
