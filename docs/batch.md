# Scenario batches

`python -m meridian batch --data data/synthetic_sites.csv --scenarios config/scenarios`
runs every scenario JSON file in the folder against the same product-location CSV.

## Behavior

1. All inputs are validated before any simulation starts, and duplicate
   `scenario_id` values are rejected.
2. Scenarios run one at a time, in file-name order, each in its own process.
3. If any scenario fails, the batch stops at that scenario and exits with status 2,
   so a partial index is never mistaken for a complete one.
4. After each completed scenario, `batch_index.csv` and `batch_report.md` in the output
   folder are rewritten, ranked from lowest to highest mean total cost.

## Outputs

| File | Contents |
|---|---|
| `batch_index.csv` | Scenario, config file, mean total cost, fill rate and bundle folder |
| `batch_report.md` | The same ranking as a Markdown table |
| `<scenario>-<id>/` | The normal result bundle for each scenario |

Costs are synthetic USD over each scenario's own horizon. Compare scenarios with
different horizons only after normalizing them.
