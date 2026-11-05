# Confidence intervals and result spread

Each scenario is simulated over several independent validation replications (demand
traces). Reported means are therefore estimates, and two scenarios whose means differ
slightly may not really differ. This page explains the uncertainty figures Meridian now
reports and how to use them.

## What is reported

| Where | Figure | Meaning |
|---|---|---|
| `summary.json`, `lanes.csv` | `cost_ci_low`, `cost_ci_high` | 95% confidence interval for the lane's mean validation cost (USD) |
| `summary.json`, `lanes.csv` | `fill_rate_ci_low`, `fill_rate_ci_high` | 95% confidence interval for the lane's mean fill rate, clipped to 0–1 |
| `summary.json`, `lanes.csv` | `cost_p5`, `cost_p50`, `cost_p95` | 5th, 50th and 95th percentiles of the lane's replication costs |
| `summary.json`, `lanes.csv` | `cost_cv` | Coefficient of variation of the lane's replication costs |
| `summary.json` | `total_cost_ci_95` | 95% confidence interval for the portfolio's mean total cost |
| `summary.json` | `replication_total_costs` | Portfolio cost of each replication |
| `summary.json` | `replications_for_2pct_precision` | Replications needed for the portfolio interval to be within ±2% of the mean |
| `report.md` | "95% CI (USD)" column and total interval | The cost intervals above |
| `report.html` | Full table | Intervals, percentiles and fill-rate intervals, with uncertain lanes shaded |
| `compare` output | `cost_difference_ci_95` | Mean and 95% interval of each scenario's cost minus the cheapest scenario's |

With a single replication no interval can be estimated, and the interval fields are left
out (`null` for the portfolio).

## How the intervals are calculated

Replications are independent, so the sample mean of *n* replication outcomes has a
standard error of *s* / √*n*, where *s* is the **sample standard deviation** (dividing by
*n* − 1). With the small numbers of replications typical of planning studies (4 to 20),
the interval uses the **Student t distribution** with *n* − 1 degrees of freedom:

mean ± t(0.975, n − 1) × s / √n

For example, with 4 replications t = 3.18, so the interval is noticeably wider than the
familiar ±1.96 standard errors, which only applies to large samples.

Percentiles interpolate linearly between sorted replication costs.

## Reading report.html

`report.html` is written to every bundle next to `report.md`. Rows are shaded when a lane
meets the service target on average but its fill-rate interval reaches below the target:
the run cannot yet say whether the policy really meets the target, and more replications
would settle it.

## Comparing scenarios

When scenarios share the same seed and number of replications, replication *r* of each
scenario faces the same demand. `compare` then pairs the replications and reports the
mean cost difference from the cheapest scenario with a 95% interval. If the interval
includes zero, the scenarios are not distinguishable at this number of replications.

Pairing removes most of the demand noise, so paired intervals are much narrower than the
overlap of two separate confidence intervals would suggest. Scenarios with different
seeds or replication counts are not paired (`cost_difference_ci_95` is `null`).

## How many replications?

`replications_for_2pct_precision` estimates how many replications would bring the
portfolio interval within ±2% of the mean, from the spread seen so far. It is never less
than the replications already run. Treat it as a guide: the estimate itself is uncertain
when few replications have been run.

| Situation | Suggestion |
|---|---|
| Interval within ±2% | Current replications are enough for cost comparisons |
| Shaded lanes in report.html | Increase replications before concluding a target is met |
| Paired difference interval includes 0 | Run more replications or treat the scenarios as equal |

## Skewed outcomes and the bootstrap

Fill rates near 100% are skewed: most replications sit at or just below 1. For such
outcomes `meridian.stats.bootstrap_interval(values, seed)` gives a percentile bootstrap
interval that respects the 0–1 range. It resamples the replications with replacement
2,000 times from a seeded generator, so it is reproducible.

```python
from meridian.stats import bootstrap_interval

fills = [0.991, 0.987, 1.0, 0.995]
print(bootstrap_interval(fills, seed=254))
```

## Worked example

A lane's four replication costs are $9,820, $10,110, $9,960 and $10,270.

| Quantity | Value |
|---|---|
| Mean | $10,040 |
| Sample SD | $193 |
| Standard error (SD / √4) | $96.5 |
| t(0.975, 3) | 3.18 |
| 95% interval | $10,040 ± $307 = $9,733 to $10,347 |

The interval is about ±3% of the mean. Reaching ±2% would take about 7
replications.

## report.md additions

`report.md` gains a "95% CI (USD)" column, the interval for the total cost, a line naming
lanes whose fill-rate interval reaches below the target, and, when the current number of
replications is too low for ±2% precision on total cost, a line suggesting how many to
run.

## Questions

**Why do intervals differ between lanes of similar size?** The width depends on the
spread of replication costs, which grows with demand variability and with how often a
lane runs short (backlog cost is lumpy).

**Should I always aim for ±2%?** No. For ranking clearly different scenarios a wider
interval is fine; look at the paired difference interval in `compare` instead.

**Do more replications change the policy?** They can: the training phase uses the same
number of replications, so a larger number gives the candidate choice more evidence too.

## Limits

- Intervals cover simulation noise only, not uncertainty in the inputs (demand
  parameters, costs or lead times).
- Fill-rate intervals use the normal approximation and can be wide with few
  replications.
