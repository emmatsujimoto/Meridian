# Suggested stock transfers

`python -m meridian run ... --transfers` adds two files to the result bundle.

| File | Contents |
|---|---|
| `transfers.csv` | One row per suggested transfer: product, from, to, kg, cost, days of cover |
| `transfers.md` | The same suggestions grouped by product, with totals |

## How suggestions are made

1. For each lane, position = starting inventory minus the recommended base stock (kg).
   Positive is a surplus, negative a deficit.
2. Within each product, deficits are filled largest first from every site with a surplus.
   Transfers smaller than 100 kg are not suggested.
3. Cost = number of trucks (20,000 kg each, rounded up) x the source site's delivery charge
   per 100 km x road distance.
4. Days of cover = transferred kg / the destination's mean daily demand.

## Distances

Built-in distances cover the sample sites. For other sites pass `--distances FILE`; the
file holds a mapping of site pairs to km, for example `{("Harbor", "Summit"): 140}`.
A pair with no known distance is never suggested.

Suggestions are for planners to review. They ignore truck schedules, driver hours,
tank pressure limits and product purity checks.
