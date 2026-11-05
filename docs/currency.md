# Costs in other currencies

All simulation costs are computed in US dollars. For sites and stakeholders outside the
US, `meridian convert` restates a completed bundle's costs in another currency, for
example euros or pounds, without re-running the scenario.

```bash
python -m meridian convert results/<bundle>/summary.json --currency EUR --rates rates.json \
    --output results/eur
```

The command verifies the bundle first (completion manifest and file hashes), then writes
two files to the output folder and prints a cost table:

| File | Contents |
|---|---|
| `summary_<CUR>.json` | The bundle's summary with every cost converted, plus `currency` and `exchange_rate_per_usd` |
| `lanes_<CUR>.csv` | The lane table with converted costs |

The original bundle is never modified.

## Several currencies side by side

Add `--also` to write `costs_by_currency.csv`, with each lane's mean cost and the total in
the target currency and every extra currency listed:

```bash
python -m meridian convert results/<bundle>/summary.json --currency EUR --also USD GBP \
    --rates rates.json --output results/eur
```

| lane | mean_cost_EUR | mean_cost_USD | mean_cost_GBP |
|---|---:|---:|---:|
| Harbor:nitrogen | 9,108.00 | 9,900.00 | 7,821.00 |
| … | … | … | … |
| TOTAL | 55,285.80 | 60,093.26 | 47,473.68 |

Repeated codes are listed once. The figures above are illustrative.

## Exchange rates

Rates are units of the target currency per US dollar, in a JSON file:

```json
{
  "rates": {
    "EUR": 0.92,
    "GBP": 0.79
  }
}
```

- Currency codes are three capital letters (ISO 4217), for example `EUR`, `GBP`, `CHF`.
- Rates must be positive. USD is always 1 and need not be listed.
- Use the rate for the period the scenario represents, and record its source, so that
  converted reports can be reproduced.

Without `--rates`, built-in example rates for USD, EUR and GBP are used. They are for
illustration only; pass a rates file for any figure you share.

## What is converted

| Converted | Not converted |
|---|---|
| Total mean cost | Fill rates and service flags |
| Each lane's mean cost and cost standard deviation | Quantities in kg (base stock, ending inventory, backlog) |
| Holding, backlog, delivery and purchase cost components | Input settings, lane inputs and the input fingerprint |

Every converted figure uses the same rate, so lane costs still add up to the converted
total.

## Comparing converted reports

`compare` accepts USD reports only, so that scenarios are never compared across
currencies by mistake. Compare the original bundles, then convert the ones you want to
present.

## Symbols

Amounts in the printed table use `$`, `€` and `£` for USD, EUR and GBP. Other currencies
show the code after the amount, for example `1,234.50 CHF`.

## Limits

- One rate applies to the whole horizon; exchange-rate movements during the scenario are
  not modelled.
- Unit costs in the lane inputs stay in USD; to plan natively in another currency,
  convert the inputs before running the scenario.
