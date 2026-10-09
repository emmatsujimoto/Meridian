# Baseline validation

Validated locally on October 8, 2026, using Python 3.12.14 on Windows. Runtime and
development versions are recorded in `requirements.lock` and `requirements-dev.lock`.

Final result: **341 tests passed, none skipped; 98% statement coverage for the new
application (456 of 463 statements)**. Ruff lint and formatting checks passed.
The baseline contains exactly 8,500 counted Python code lines across 41 Python
files; the component breakdown and counting definition are in `line-count.json`.

The final verification covers:

- Application and selected upstream regression tests, including all retained
  upstream tests previously guarded by `RUN_ALL_TESTS`.
- Application statement coverage, reported separately from upstream algorithms.
- Ruff lint and format checks for the new application, tests and maintenance scripts.
- Package installation and wheel/source-distribution builds.
- Full baseline and higher-demand example runs, export hashes and report comparison.
- Source import closure, upstream attribution checksums and reproducible line counts.
- Runtime dependency audit using the public PyPI advisory service. No known
  vulnerabilities were reported for the seven pinned runtime packages at check time.

## Reproducible example observations

Both scenarios use six fictional product-location streams, 60 days, four validation
replications and seed 254. Outputs are examples, not observed business costs.

| Scenario | Mean horizon cost, USD | Volume-weighted immediate fill rate |
|---|---:|---:|
| Baseline | 60,093.26 | 99.9757% |
| Demand multiplier 1.25 | 68,952.75 | 99.9712% |

The larger demand scenario scales both mean and standard deviation. These are
finite-horizon policy experiments; do not interpret the difference as a verified
real-world financial forecast. No intentionally seeded defects were added.

## Limits of verification

Tests do not prove absence of all defects. The selected upstream test suite is a
subset of the original project's tests. Scenario checks use synthetic data. The
Azure pipeline is supplied as a template and has not been executed in an Azure
DevOps environment. Remote GitHub workflow status must be checked after publication.
No load test, production security certification, or industrial safety assessment is claimed.
