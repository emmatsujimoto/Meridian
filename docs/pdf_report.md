# Multi-scenario PDF report

`meridian pdf-report` writes one PDF that summarises several completed result bundles. It
is meant for sharing a set of scenarios with people who will not open CSV files: a
planning review, a steering meeting or an email attachment.

```bash
python -m meridian pdf-report results/baseline-*/summary.json results/higher-demand-*/summary.json \
  --output reviews/october.pdf --title "October scenario review"
# PDF report written to reviews/october.pdf
```

| Option | Default | Meaning |
|---|---|---|
| `reports` | required | One to 12 `summary.json` files |
| `--output <file>` | required | PDF file to write; an existing file is never replaced |
| `--title <text>` | `Scenario comparison` | Title on the first page and in every footer |
| `--order <order>` | `given` | Scenario order: `given` (command-line order), `name`, `cost` (cheapest first) or `fill-rate` (best-served first) |

Every bundle is verified before it is used, with the same checks as `meridian compare`. If
any bundle fails, no PDF is written.

## What the report contains

### First page: comparison

- The title, the generation time (UTC) and the number of scenarios.
- A table with one row per scenario: horizon, number of product-locations, mean total
  cost and volume-weighted fill rate.
- A bar chart of mean total cost by scenario.
- A table of contents with the first page of each section.

Scenarios appear in the order chosen with `--order`; by default, the order they were
given on the command line.

### One section per scenario

Each scenario starts on a new page with:

- The scenario name, horizon, replications, mean total cost and fill rate.
- A one-line callout naming any product-locations that missed the service target on
  validation, so they are not lost in the table.
- A single stacked bar splitting total cost into holding, ordering (delivery and
  purchase) and backlog cost, with each component's share in the legend.
- A bar chart of mean cost by product-location.
- A table of product-locations with base-stock level, mean cost, fill rate and whether the
  service target was met on validation.
- The scenario comparison chart again at the bottom of the page, so each page can be read
  on its own when printed.

Tables longer than 16 rows continue on further pages, headed "continued, part 2" and so
on. Each continuation page repeats the scenario's facts and charts.

### Product-locations across scenarios

With two or more scenarios, a page lists every product-location present in all of them,
with its mean cost and fill rate in each scenario side by side, for example
`16,703 (100%)`. Up to five scenarios and 40 product-locations fit on the page; the page
says when more were left out. Product-locations missing from any scenario are not listed.

### Model assumptions

The last page lists the model notes recorded in the bundles, each note once, so readers
see the assumptions behind the numbers without opening the bundles.

Every page has the report title and page number in the footer.

## Comparing scenarios fairly

The report places scenarios side by side but does not check that they are comparable.
`meridian compare` refuses to compare runs with different horizons, currencies or lane
portfolios; the PDF report accepts them so that, for example, a 14-day quickstart run can
be shown next to a 60-day baseline. Check the horizon column on the first page before
comparing total costs, because longer horizons accumulate more cost.

## Page format

Pages are A4 portrait. The report uses the standard Helvetica fonts that every PDF
reader provides, so nothing is embedded and files stay small (typically 10-30 kB).
Characters outside Latin-1 are replaced with `?`; scenario names and lane names are
always plain ASCII, so this only affects custom titles.

## Python use

```python
from meridian.pdf_report import build_report, write_report

data = build_report(["results/a/summary.json", "results/b/summary.json"], title="Review")
path = write_report(["results/a/summary.json"], "single.pdf")
```

`build_report` and `write_report` also take `order` with the same values as `--order`.
`build_report` returns the PDF as bytes, for example to attach it to an email without
writing a file. `meridian.pdf` contains the small PDF writer used by the report: a
`Document` of `Page` objects with `text`, `line` and `rect` drawing operations.

## Frequently asked questions

**Why is a scenario's chart repeated on every page?** Each page is designed to be read
on its own when printed or forwarded as a single page, so the comparison chart is shown
at the bottom of every scenario page.

**Can I change the page size or fonts?** Not at present: pages are A4 portrait and text
uses Helvetica. US Letter readers can print with "fit to page"; the margins leave room
for the small difference in size.

**How do I include more than 12 scenarios?** Split them into several reports, for
example one per study, or compare them first with `meridian compare` and include only
the scenarios worth discussing.

**Why are some product-locations missing from the cross-scenario page?** The page only
lists product-locations present in every scenario, so that each row compares like with
like. A lane added in one scenario appears on that scenario's own page.

**Does the report change the bundles?** No. Bundles are only read and verified; the PDF
is written to the `--output` path.

**The PDF shows `?` in my title.** Titles are limited to Latin-1 characters because the
report uses the standard PDF fonts. Replace symbols such as subscripts with plain text,
for example `CO2` instead of `CO₂`.

## Errors

| Message | Cause |
|---|---|
| `Provide at least one summary.json` | No bundles were given |
| `At most 12 bundles fit in one report` | Too many bundles; split them into several reports |
| `Provide a completed bundle's summary.json` | A path is not a bundle's `summary.json` |
| `Result file failed integrity check` | A bundle changed after its run |
| `<file> already exists; choose a new file name` | `--output` points at an existing file |

All errors exit with status 2 and write nothing.
