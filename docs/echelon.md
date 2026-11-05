# Two-echelon (depot-to-site) planning

The main model assumes every site orders straight from the supplier. In practice some
sites are resupplied from a regional depot that holds stock closer to them. The
`echelon` command plans site stock for that arrangement.

```bash
python -m meridian echelon --data data/synthetic_sites.csv --config config/quickstart.json \
    --depots config/depots.json --output results/echelon
```

## Depot file

`config/depots.json` lists the depots. Each depot needs:

| Field | Meaning |
|---|---|
| `depot_id` | Portable identifier (letters, digits, `_` and `-`) |
| `lead_time_days` or `lead_time_hours` | Inbound lead time from the supplier to the depot. Hours are rounded up to whole days. At most 30 days. |
| `holding_cost_per_kg_day` | Depot holding cost (USD per kg per day) |
| `initial_inventory_kg` | Stock on hand at the depot (optional, default 0) |
| `sites` | Sites served by the depot. A site may belong to at most one depot. |

Sites not listed under any depot are planned as direct deliveries from the supplier.

## Method

1. **Effective lead time.** For a site served by a depot, the effective lead time is the
   depot's inbound lead time plus the site's own lead time. The depot lead time is added
   once. Direct sites use their own lead time.
2. **Protection period.** Effective lead time plus one daily review period.
3. **Safety stock.** `z × daily demand SD × √(protection period)`, where `z` comes from the
   scenario's service target used as a cycle-service level (capped at 99.99% and never
   below zero). Demand mean and SD are scaled by the scenario's demand multiplier.
4. **Site base stock.** Mean demand over the protection period plus safety stock, rounded
   up to a whole kg.
5. **Depot allocation.** Each site's shortfall is its base stock minus its current stock.
   Depot stock on hand is allocated to the sites it serves, largest shortfall first, until
   it runs out.

## Output

`echelon.csv` has one row per product-location:

| Column | Meaning |
|---|---|
| `lane` | Product-location key |
| `depot` | Serving depot, or `direct` |
| `site_lead_time_days`, `depot_lead_time_days` | The two lead-time legs |
| `effective_lead_time_days` | Their sum (site lead time only for direct sites) |
| `lead_time_demand_kg` | Mean demand over the protection period |
| `safety_stock_kg`, `site_base_stock_kg` | Planned safety stock and order-up-to level |
| `site_shortfall_kg` | Base stock not covered by the site's current stock |
| `allocated_from_depot_kg`, `unmet_shortfall_kg` | Depot stock allocated, and what is still missing |

The command also prints a line per depot with total shortfall, stock allocated and stock
left at the depot.

## Limits

This is an analytical plan, not a two-echelon simulation. It does not model depot
replenishment orders, transport capacity or lateral transfers between depots.
