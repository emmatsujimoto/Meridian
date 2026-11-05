# Comparing scenario files

`meridian scenario-diff` lists the settings that differ between two scenario JSON files.
It answers "what did I change?" before running a second scenario, or "why do these two
runs differ?" afterwards.

```bash
python -m meridian scenario-diff config/baseline.json config/higher_demand.json
```

```text
demand_multiplier: 1.0 -> 1.25
scenario_id: "baseline" -> "higher-demand"
```

When nothing differs the command prints `No differences`.

## What is compared

Both files are checked with the same rules as `meridian run`, so an invalid file is
reported as an error rather than compared. The comparison then uses the *effective*
settings, the values a run would actually use:

- A setting left out of a file is compared using its default. A file that omits
  `replications` and one that sets it to the default value of 4 do not differ.
- `stock_multipliers` are sorted before comparing, because the order does not affect a
  run. Entries are compared position by position after sorting, and extra entries are
  shown as added or removed, for example `stock_multipliers[3]: (none) -> 1.75`.
- Numbers are compared by value: `1` and `1.0` are the same setting.

Settings are listed in alphabetical order. Text values are shown in quotes, true/false
values as `true` and `false`, and a missing side as `(none)`.

## Options

| Option | Effect |
|---|---|
| `--ignore <setting>` | Leave out a setting, such as `scenario_id` or `seed`; repeat for several |
| `--json` | Print a JSON list with `setting`, `kind` (`added`, `removed` or `changed`), `before` and `after` |
| `--exit-code` | Exit with status 1 when the files differ and 0 when they match, like `diff` |

`--ignore` only accepts real setting names, so a typo is reported instead of silently
ignoring nothing.

`--exit-code` is useful in scripts, for example to check that a copied scenario differs
from the original only in its name:

```bash
python -m meridian scenario-diff config/baseline.json studies/copy.json \
  --ignore scenario_id --exit-code && echo "Only the name changed"
```

## JSON output

```bash
python -m meridian scenario-diff config/baseline.json config/quickstart.json --json
```

```json
[
  {"setting": "horizon_days", "kind": "changed", "before": 60, "after": 14},
  {"setting": "replications", "kind": "changed", "before": 4, "after": 2},
  {"setting": "scenario_id", "kind": "changed", "before": "baseline", "after": "quickstart"},
  {"setting": "stock_multipliers[0]", "kind": "changed", "before": 0.75, "after": 0.8}
]
```

`before` or `after` is `null` for an added or removed entry.

## Relation to other commands

- `meridian compare` compares the *results* of completed runs. Use `scenario-diff` first to
  see which inputs changed between them.
- Two runs whose scenario files show no differences, and that used the same lane CSV, have
  the same `input_sha256` in `summary.json`.

## Python use

```python
from meridian.scenario_diff import changed_settings, diff_settings, setting_changes

print(diff_settings("config/baseline.json", "config/higher_demand.json"))
for change in setting_changes("config/baseline.json", "config/quickstart.json"):
    print(change.path, change.kind, change.before, change.after)
print(changed_settings("config/baseline.json", "config/quickstart.json"))
```
