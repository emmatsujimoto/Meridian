# Inventory snapshot comparison

`meridian snapshot-diff` compares where two completed runs leave stock at the end of the
planning horizon. It answers questions such as "after raising the demand multiplier, which
product-locations finish with less nitrogen on hand?" without opening two sets of CSV files.

## What a snapshot is

A snapshot is read from one completed result bundle (the folder printed by
`meridian run`). For every product-location it records:

| Field | Source | Meaning |
|---|---|---|
| `lane` | `summary.json` | Product-location key, `<site>:<product>` |
| `base_stock_kg` | `summary.json` | Base-stock level selected for the lane |
| `ending_inventory_kg` | `daily_results.csv` | Mean on-hand inventory on the final day, across validation replications |
| `ending_backlog_kg` | `daily_results.csv` | Mean unmet demand still owed on the final day, across validation replications |

The final day is the run's `horizon_days`. Only validation replications are written to
`daily_results.csv`, so training demand never affects a snapshot.

Bundles are checked with the same integrity rules as `meridian compare`: the folder must
contain `COMPLETE.json`, every listed file must match its recorded SHA-256 digest, and the
input fingerprints must agree. A bundle that was edited after the run is rejected.

## Running a comparison

```bash
python -m meridian run --data data/synthetic_sites.csv --config config/baseline.json
python -m meridian run --data data/synthetic_sites.csv --config config/higher_demand.json
python -m meridian snapshot-diff results/<baseline>/summary.json results/<higher>/summary.json
```

The first bundle is treated as "before" and the second as "after". Both runs must use the
same `horizon_days`; comparing a 90-day run with a 30-day run is refused because the final
days are not comparable.

### Options

| Option | Default | Effect |
|---|---|---|
| `--format table\|json\|csv` | `table` | Markdown table, JSON document or CSV rows |
| `--status <status>` | all | Only show lanes with this status; repeat to include several |
| `--top <n>` | all | Only show the `n` lanes with the largest absolute inventory change |
| `--by-product` | off | Sum lanes per product (table or JSON only) |
| `--save <file>` | none | Also write the output to a new file; existing files are never replaced |

`--status` is applied before `--top`, so `--status "less stock" --top 5` shows the five
lanes that lost the most ending inventory.

## Statuses

Each lane receives one status:

| Status | Meaning |
|---|---|
| `more stock` | Ending inventory rose between the runs |
| `less stock` | Ending inventory fell between the runs |
| `changed` | Ending inventory is the same, but backlog or base stock moved |
| `unchanged` | Inventory, backlog and base stock all match |
| `added` | The lane appears only in the second bundle |
| `removed` | The lane appears only in the first bundle |

Inventory is checked first, so a lane whose inventory and backlog both moved is reported
as `more stock` or `less stock`. Differences smaller than 0.01 kg are treated as equal so
that floating-point noise in CSV round trips does not mark a lane as changed.

## Output formats

### Table

The default output is a Markdown table that can be pasted into a planning note:

```text
# Inventory snapshot comparison: baseline -> higher_demand

Horizon: 90 days. Lanes compared: 12.
Net change in ending inventory: -4,180 kg.

| Product-location | Status | Base stock before | Base stock after | ... |
|---|---|---:|---:|---|
| Allentown:nitrogen | less stock | 42,000 | 42,000 | ... |
```

A short count of lanes per status follows the table. Missing values for added or removed
lanes are shown as `-`.

### JSON

```json
{
  "before": {"scenario_id": "baseline", "input_sha256": "..."},
  "after": {"scenario_id": "higher_demand", "input_sha256": "..."},
  "horizon_days": 90,
  "totals": {"lanes": 12, "more_stock": 0, "less_stock": 9, "...": "..."},
  "lanes": [{"lane": "Allentown:nitrogen", "status": "less stock", "...": "..."}]
}
```

Values for a missing side are `null`. Both input fingerprints are included so a saved
comparison can be traced back to the exact input files.

### CSV

CSV output always uses this column order:

1. `lane`
2. `status`
3. `base_stock_before_kg`
4. `base_stock_after_kg`
5. `inventory_before_kg`
6. `inventory_after_kg`
7. `inventory_change_kg`
8. `backlog_before_kg`
9. `backlog_after_kg`

Missing values are written as empty cells.

### Per-product totals

`--by-product` adds up every site for each product. Lanes present in only one run count
towards that run's totals, so opening or closing a site shows up as a change for its
product:

```text
| Product | Lanes | Ending inventory before | Ending inventory after | Change (kg) | Backlog change (kg) |
|---|---:|---:|---:|---:|---:|
| argon | 3 | 18,400 | 17,950 | -450 | +0 |
| nitrogen | 6 | 96,200 | 91,300 | -4,900 | +120 |
```

With `--format json` the same totals are returned as a list of objects. CSV output is not
available for per-product totals.

## Reading the results

- `inventory_change_kg` is after minus before. A negative value means the second run
  finishes with less stock on hand.
- Ending inventory is a single day's position. A lane that finishes low may still have met
  its fill-rate target earlier in the horizon; use `report.md` for service measures.
- Ending backlog above zero means some demand was still unmet on the final day.
- A change in base stock usually explains a change in ending inventory. When base stock is
  unchanged, the difference comes from demand or lead-time settings.
- Because snapshots are means across replications, small changes between runs with
  different seeds are expected even when settings are the same.

## Python use

The same functions are available for notebooks and scripts:

```python
from meridian.snapshots import diff_snapshots, diff_totals, load_snapshot

before = load_snapshot("results/baseline-1a2b3c/summary.json")
after = load_snapshot("results/higher_demand-4d5e6f/summary.json")
rows = diff_snapshots(before, after)
print(diff_totals(rows))
```

`filter_rows`, `largest_changes`, `diff_table`, `diff_json`, `diff_csv` and `write_diff`
mirror the command-line options.

## Errors

| Message | Cause |
|---|---|
| `Provide a completed bundle's summary.json` | The path does not point at a `summary.json` file |
| `Result file failed integrity check` | A file in the bundle changed after the run |
| `Snapshots must cover the same horizon to be compared` | The runs use different `horizon_days` |
| `daily_results.csv has no final day for <lane>` | The daily file is missing rows for a lane |
| `<file> already exists; choose a new file name` | `--save` would replace an existing file |

All errors exit with status 2 and print a single line to standard error.
