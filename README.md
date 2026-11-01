# Meridian Gas Planner

An internal inventory-planning application for **Meridian Industrial Gases**, a
fictional supplier of bulk nitrogen, oxygen and argon. It helps an analyst compare
replenishment policies for product inventories at hypothetical customer locations.
All company, location, demand and cost data is synthetic. No real customer data,
credentials or operating-system connections are included.

The Python repository combines a focused, attributed subset of **Stockpyl v1.0.2**
with a new command-line application, validated inputs, reproducible experiments,
reports and automated correctness tests. It is a clean baseline: no intentionally
seeded defects, compromised dependencies or dummy credentials are included.

## What it does

1. Reads a CSV containing each location's product demand, starting inventory,
   lead time and cost assumptions.
2. Builds several daily replenishment policies using Stockpyl inventory models.
3. Compares their cost and service on identical synthetic demand samples.
4. Selects the least-cost candidate meeting the configured training service target.
   If none qualifies, it reports that explicitly and selects the highest-service candidate.
5. Evaluates the selected policy on separate demand samples.
6. Exports a readable report, cost breakdown, candidate comparison and daily results.

This is a planning study, not a delivery dispatch or plant-control system. The
model does not represent tank safety, pressure, boil-off, shared fleet capacity,
vehicle routes, gas purity or operating procedures.

## Quick start

Requires Python 3.12 or newer. Run from the repository root:

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS / Linux instead: source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m meridian validate --data data/synthetic_sites.csv --config config/quickstart.json
python -m meridian run --data data/synthetic_sites.csv --config config/quickstart.json --output results
python -m pytest
```

Every run prints a unique result folder. Open its `report.md` for the concise
summary, or `summary.json` for the complete settings and structured results.
`COMPLETE.json` confirms all outputs were written and records their hashes.
The result folders are ignored by Git, so rerunning the tool does not change source files.

For the full example, use `config/baseline.json`. To study a hypothetical 25% demand
increase, use `config/higher_demand.json`.

```bash
python -m meridian benchmark --data data/synthetic_sites.csv --config config/quickstart.json
python -m meridian compare results/<run-one>/summary.json results/<run-two>/summary.json
```

To base demand on recent history instead of typed assumptions, see
[docs/forecast.md](docs/forecast.md):

```bash
python -m meridian forecast --data data/synthetic_sites.csv --history history.csv
```

The `benchmark` command provides EOQ and Wagner-Whitin calculations. They have
different assumptions from the stochastic simulation and are labeled separately.

## Repository map

| Location | Contents |
|---|---|
| `src/meridian/models.py` | Product-location inputs, settings, result objects and validation |
| `src/meridian/inputs.py` | Strict CSV/JSON loading and understandable input errors |
| `src/meridian/demand.py` | Seeded synthetic demand, separated into training and validation |
| `src/meridian/engine.py` | Adapter to the Stockpyl inventory simulator |
| `src/meridian/planning.py` | Candidate selection, EOQ and deterministic lot-sizing benchmarks |
| `src/meridian/reporting.py` | Cost summaries, CSV/JSON exports and scenario comparison |
| `src/meridian/forecast.py` | Demand estimates from daily history |
| `src/meridian/cli.py` | Local command-line interface |
| `src/stockpyl/` | Selected upstream inventory algorithms and their required network objects |
| `data/` | Six fictional product-location input rows |
| `config/` | Quickstart, baseline and higher-demand scenarios |
| `tests/meridian/` | New application correctness and integration tests |
| `tests/test_*.py` | Selected upstream algorithm regression tests |
| `docs/` | Model assumptions, input definitions, provenance and validation evidence |
| `scripts/` | Reproducible source-size and repository-integrity checks |
| `.github/workflows/` | GitHub automated checks |
| `azure-pipelines.yml` | Equivalent portable checks for a future Azure DevOps import |

## Size and provenance

This baseline contains **8,500 Python code lines across the application,
selected upstream modules, tests and maintenance scripts**. Counted code excludes
blank lines, comment-only lines and docstrings. Total physical lines are higher
because the upstream algorithms retain their explanatory documentation.
Run `python scripts/count_lines.py` for the exact breakdown. Data rows, JSON,
Markdown, installed dependencies and generated reports do not count toward the target.

| Component | Code lines |
|---|---:|
| New application | 664 |
| Selected Stockpyl source | 4,251 |
| New application tests | 545 |
| Retained Stockpyl regression tests | 2,897 |
| Maintenance scripts | 143 |
| **Total** | **8,500** |

There are 41 Python files and 20,825 physical Python lines including comments,
docstrings and blank lines. This convention makes the requested code-size target
explicit; it does not imply 8,500 newly written application lines.

Stockpyl is vendored so the selected algorithms are available for review in this
repository. **Do not also install the standalone Stockpyl package into the same
environment**, because both provide the `stockpyl` import namespace. This subset is
not advertised as a complete replacement for upstream Stockpyl.

Original algorithms and retained regression tests: Larry Snyder and Stockpyl
contributors, MIT license. New application, tests and documentation: AI-assisted
implementation for this fictional project. Full attribution and recorded changes
are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Development checks

```bash
python -m pytest --cov=meridian --cov-report=term-missing
python -m ruff check src/meridian tests/meridian scripts
python -m ruff format --check src/meridian tests/meridian scripts
python scripts/count_lines.py
python scripts/check_repository.py
python -m build
```

Linting applies to the new code; upstream formatting is preserved and tracked
separately. Tests exercise normal and invalid inputs; an invalid-input test is
not an intentionally broken application path. A passing test suite does not prove
the absence of every possible software defect.

Start with [docs/model.md](docs/model.md) to understand the assumptions and
[docs/input_dictionary.md](docs/input_dictionary.md) to change a scenario.
