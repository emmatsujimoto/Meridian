# Batching orders within a window

The base-stock policy orders whenever stock falls below its target, often on several
days in a row. Every order pays the lane's delivery charge. `meridian batching` estimates
what would happen if orders for the same product-location placed within a few days were
combined into one delivery.

```bash
python -m meridian batching --data data/synthetic_sites.csv --config config/baseline.json \
    --window 3 --output results/batching
```

## Method

1. **Orders.** The orders placed in one validation replication of the scenario
   (`--replication`, default 1).
2. **Groups.** For each product-location, orders are taken in day order. A group starts
   at an order and includes every later order placed within the window, counting the
   first order's day as day 1 of the window. With `--window 3`, orders on days 4, 5 and 6
   form one group; an order on day 7 starts the next.
3. **Delivery.** Each group becomes one delivery on its first day, so it pays one
   delivery charge instead of one per order.
4. **Holding.** Stock from later orders in a group arrives earlier than it would have.
   Each kg delivered *d* days early adds *d* days of holding cost.
5. **Net saving.** Delivery cost saved minus the extra holding cost.

`--window 1` leaves orders unchanged and is a useful baseline.

## Output

`batching.csv` has one row per product-location:

| Column | Meaning |
|---|---|
| `lane` | Product-location key |
| `orders` | Orders placed in the replication |
| `deliveries` | Deliveries after batching |
| `delivered_kg` | Total quantity ordered (unchanged by batching) |
| `delivery_cost_before`, `delivery_cost_after` | Delivery charges without and with batching (USD) |
| `extra_holding_cost` | Holding cost of receiving stock early (USD) |
| `net_saving` | Delivery cost saved minus extra holding cost (USD) |

The command prints portfolio totals.

## Choosing a window

| Window | Typical effect |
|---|---|
| 1 day | No change |
| 2–3 days | Removes back-to-back deliveries at little holding cost |
| 7 days | Weekly deliveries; large delivery savings but more stock on hand |

A negative net saving means the lane's holding cost outweighs its delivery charge for
that window; keep its current ordering.

## Comparing windows

Add `--compare` with a list of windows to print portfolio totals for each, and the
window with the largest net saving for each product-location:

```bash
python -m meridian batching --data data/synthetic_sites.csv --config config/baseline.json \
    --window 3 --compare 1 2 3 5 7
```

```text
window 1 days: 214 deliveries, net saving $0
window 3 days: 131 deliveries, net saving $5,870
window 7 days: 72 deliveries, net saving $7,310
best window for Harbor:nitrogen: 7 days
best window for Summit:argon: 3 days
```

Figures are illustrative. A lane where no window saves money is reported with the
shortest window given. Lanes with high holding cost relative to their delivery charge
usually prefer short windows.

## Limits

- This is an estimate from one replication's orders; the inventory simulation is not
  re-run with batched deliveries, so service effects of the changed timing are not shown.
- Truck capacity is not checked; combined deliveries are assumed to fit.
- The window is the same for every product-location.

## Questions

**Does batching change how much is delivered?** No. The same kilograms arrive; only the
number of deliveries and the timing change.

**Why can a longer window save less?** Each extra day in the window brings later orders
forward, adding holding cost on more stock. Past some point the extra holding cost grows
faster than the delivery charges saved.
