# Shared truck trips

The inventory model charges a delivery for every order, as if each order travelled on
its own truck. Sites that are close together can often share a truck: an oxygen order to
Harbor and one to Summit on the same day can be loaded on one trailer if they fit. The
`trucks` command plans those shared trips from a scenario's simulated orders and shows how
many trips and how much delivery cost combining would save.

```bash
python -m meridian trucks --data data/synthetic_sites.csv --config config/quickstart.json \
    --routes config/routes.json --output results/trucks
```

## Routes file

`config/routes.json` defines which sites can share a truck and how much a truck carries:

| Field | Meaning |
|---|---|
| `truck_capacity_t` | Truck capacity in **tonnes** for each of nitrogen, oxygen and argon. Bulk gas trailers are product-specific, so products never share a truck. |
| `trip_cost` | Cost of one truck trip (USD), used to compare against per-order delivery costs. Optional, default 0. |
| `routes` | Groups of nearby sites. Each route has a `route_id` and a list of `sites`; a site may be on at most one route. |

Sites on no route are delivered alone, one truck per order.

## Method

1. Orders come from one validation replication of the scenario (`--replication`,
   default 1). Each order is one delivery of one product to one site on one day.
2. Deliveries are grouped by day, route and product.
3. Within each group, the first truck takes the combination of deliveries that fills it
   most without exceeding its capacity; the next truck does the same with what is left,
   until every delivery is on a truck.
4. A delivery larger than one truck is split into full trucks plus a part-load, which can
   then share with other deliveries.

Truck capacity is given in tonnes and order quantities are in kg; capacities are compared
in the same unit.

## Output

`trucks.csv` lists one row per trip:

| Column | Meaning |
|---|---|
| `trip` | Trip number, in day order |
| `day` | Simulated day |
| `route` | Route, or `direct-<site>` for sites on no route |
| `product` | Product carried |
| `sites` | Sites served, joined with `+` |
| `load_kg` | Total quantity carried (kg) |
| `capacity_t` | Truck capacity (tonnes) |
| `utilisation` | Load as a share of capacity |
| `deliveries` | Number of deliveries on the trip |

The command also prints the number of deliveries and trips, the mean truck fill, and the
delivery cost with separate deliveries versus combined trips.

## Reading the result

A positive saving means shared trips cost less than separate deliveries at the given trip
cost. Low mean utilisation on a route suggests orders there are small or infrequent; a
larger base stock (fewer, bigger orders) may then pay for itself, which the main model
can test.

## Limits

- Planning uses the orders the inventory policy already placed; it does not change when
  or how much each site orders.
- Travel time, driver hours, delivery windows and the order in which a truck visits sites
  are not modelled.
- Each day is planned independently; a truck cannot carry orders from different days.
