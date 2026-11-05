# Delivery emissions

`meridian emissions` estimates the carbon dioxide emitted by delivery trucks in a
scenario. It uses the orders the simulation placed, so the effect of a stock policy on
delivery frequency, and therefore on emissions, can be compared between scenarios.

```bash
python -m meridian emissions --data data/synthetic_sites.csv --config config/quickstart.json \
    --distances distances.json --output results/emissions
```

## Distances

Give the one-way road distance from the supplier to each site in kilometres, as a JSON
object. Every site in the lane file needs a distance; extra sites are ignored.

```json
{
  "Harbor": 40,
  "Summit": 65,
  "Meadow": 18
}
```

Distances must be positive and at most 2,000 km.

## Method

1. **Deliveries.** Each order placed in one validation replication (`--replication`,
   default 1) is a delivery of one product to one site on one day.
2. **Trips.** A trip is a round trip from the supplier to one site. When a site orders
   several products on the same day, they travel on the same trip, so the trip is counted
   once. Deliveries on different days are separate trips.
3. **Emissions.** Each trip emits round-trip distance (2 × one-way km) times the emission
   factor, 0.9 kg CO2 per km.
4. **Intensity.** kg CO2 per tonne delivered divides emissions by the quantity delivered,
   so lanes with large, infrequent deliveries can be compared with small, frequent ones.

Emissions are allocated to product-locations for `emissions.csv`, and totalled per site
and for the whole portfolio for the printed summary.

## Output

`emissions.csv` has one row per product-location:

| Column | Meaning |
|---|---|
| `lane` | Product-location key |
| `deliveries` | Orders delivered in the replication |
| `delivered_kg` | Total quantity delivered (kg) |
| `distance_km` | Round-trip kilometres driven for the lane |
| `kg_co2` | Emissions (kg CO2) |
| `kg_co2_per_tonne` | Emissions per tonne delivered |

The command prints the number of trips, total kilometres, total kg CO2 and kg CO2 per
tonne for the portfolio.

## Worked example

Harbor is 40 km from the supplier. On day 3 it orders 800 kg of nitrogen and 300 kg of
oxygen; on day 5 it orders 600 kg of nitrogen.

| Day | Products | Trip distance | kg CO2 |
|---|---|---:|---:|
| 3 | nitrogen + oxygen | 80 km | 72 |
| 5 | nitrogen | 80 km | 72 |
| **Total** | | **160 km** | **144** |

Two trips deliver 1.7 tonnes, so the intensity is 144 / 1.7 ≈ 84.7 kg CO2 per tonne.

## Interpreting results

- Higher base stock usually means fewer, larger orders and so fewer trips and lower
  emissions, at the cost of more inventory holding.
- kg CO2 per tonne falls when deliveries are combined or larger, which makes it the
  better measure for comparing policies than total kg CO2.

## Limits

- The emission factor is a single average for a loaded and empty bulk-gas truck; it does
  not vary with load, road type or vehicle.
- Trips serve one site; multi-stop routes (see the truck planning feature) are not
  combined here.
- Production and liquefaction emissions at the supplier are out of scope.
