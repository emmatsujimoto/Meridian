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

## Policy choice and validation

A normal newsvendor approximation to protection-period demand centers a finite
grid of base-stock levels. It is a grid construction heuristic, not an assertion
that demand is normal. All candidates face the same lognormal training samples.
Candidate levels are rounded up to whole kilograms; multipliers that round to the same
level produce one candidate, so a scenario can have fewer candidates than multipliers.

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
