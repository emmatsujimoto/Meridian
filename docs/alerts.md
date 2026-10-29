# Run alerts

Every `run` writes two extra files into its result bundle.

| File | Contents |
|---|---|
| `alerts.csv` | One row per alert: lane, kind, severity, value, message |
| `alerts.md` | The same alerts as a Markdown table, most severe first |

## Alert types

| Kind | Raised when | Severity |
|---|---|---|
| stockout | A validation replication has unmet demand on at least `stockout_streak_days` consecutive days (default 3) | critical at twice the limit, otherwise warning |
| service | The lane's mean validation fill rate is below the scenario's `service_target` | critical below 90%, otherwise warning |
| cost | With `--baseline`, mean lane cost rose by more than `cost_increase_pct` (default 10%) | warning |
| cost | With `--baseline`, the lane did not exist in the baseline run | info |

The baseline must be a completed bundle; its integrity is checked before use. Alerts are
derived from the synthetic validation samples and are not operational instructions.
