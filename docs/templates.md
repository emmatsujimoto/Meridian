# Scenario templates

`meridian new-scenario` writes a pair of starter files for a new study: a scenario JSON and
a product-location CSV. Both are valid as written, so the usual workflow is to generate a
scenario, run `meridian validate` once, then edit the numbers that matter for the study.

## Quick start

```bash
python -m meridian new-scenario tank-study
python -m meridian validate --data tank-study_sites.csv --config tank-study.json
python -m meridian run --data tank-study_sites.csv --config tank-study.json
```

The command prints the paths it wrote and the matching `validate` command.

## Templates

| Template | Lanes | Horizon | Use it for |
|---|---:|---:|---|
| `quickstart` | 2 | 14 days | A fast first run with one site's nitrogen and oxygen |
| `standard` | 6 | 60 days | All three example sites; the same lanes as `data/synthetic_sites.csv` |
| `high-demand` | 6 | 60 days | The example sites with a 25% demand multiplier |
| `single-lane` | 1 | 90 days | Studying one product-location with more replications and a finer stock grid |

`quickstart` is used when `--template` is not given. List the templates and their
descriptions with:

```bash
python -m meridian new-scenario --list
```

## Options

| Option | Default | Effect |
|---|---|---|
| `scenario_id` | required | Name of the scenario; also the start of both file names |
| `--template <name>` | `quickstart` | Template to start from |
| `--folder <path>` | current folder | Where to write the files; the folder must already exist |
| `--horizon <days>` | template value | Override the template's `horizon_days` |
| `--replications <n>` | template value | Override the template's `replications` |
| `--force` | off | Replace files that already exist |
| `--list` | off | List templates instead of writing files |

The scenario name follows the usual `scenario_id` rules: it starts with a letter and
contains up to 64 letters, digits, hyphens or underscores.

Overrides are checked with the same limits as a hand-written scenario (for example 1-366
days), and nothing is written when an override is invalid:

```bash
python -m meridian new-scenario long-study --template standard --horizon 180 --replications 12
```

## Files written

For `meridian new-scenario tank-study --template high-demand` the command writes:

- `tank-study.json`, the scenario settings, with `scenario_id` set to `tank-study`:

  ```json
  {
    "scenario_id": "tank-study",
    "horizon_days": 60,
    "replications": 4,
    "seed": 254,
    "demand_multiplier": 1.25,
    "service_target": 0.95,
    "stock_multipliers": [0.75, 1.0, 1.25, 1.5]
  }
  ```

- `tank-study_sites.csv`, the product-location inputs, with the same columns as
  `data/synthetic_sites.csv`.

See [input_dictionary.md](input_dictionary.md) for the meaning and limits of every field.

## Existing files

If either file already exists, `new-scenario` keeps it and stops, so an edited scenario is
never lost by running the command twice. Use `--force` to start again from the template;
the command then lists every file it replaced.

## Editing a generated scenario

Typical first edits:

1. Change `horizon_days` and `replications` in the JSON to the size of study needed. Large
   values take longer to run; start small and increase once the inputs look right.
2. Replace the example sites in the CSV with the product-locations being studied. Keep one
   row per site and product; duplicate rows are rejected.
3. Adjust `stock_multipliers` to widen or narrow the grid of base-stock levels tried for
   each lane.
4. Keep `seed` unchanged when comparing scenarios, so differences between runs come from
   the inputs rather than from different random demand.

Run `meridian validate` after each round of edits. It reports the first problem with a
row number, which is quicker to fix than a failed run.

## Using templates from Python

```python
from meridian.templates import scenario_files, write_scenario

files = scenario_files("tank-study", "quickstart")  # {file name: text}
written = write_scenario("tank-study", "studies", template="single-lane")
print(written["settings"], written["lanes"])
```

`write_scenario` checks the generated files with the same loaders as `meridian run` before
returning, and reports any files that already existed in `written["replaced"]`.
