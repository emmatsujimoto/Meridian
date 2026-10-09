# Development

Use an isolated Python 3.12+ environment and install `.[dev]`. Keep application
changes in `src/meridian`. Avoid changing the vendored algorithms unless a
regression test demonstrates the need; record any such changes in the provenance files.

Before proposing a change, run the tests, Ruff checks, source-size report and
integrity checks described in the README. New numerical behavior should include
an independently checkable example or invariant, not only a test duplicating its implementation.

Preserve kg/day and USD conventions or introduce explicit, tested conversions.
Describe assumptions when introducing a new planning method. Never commit real
company data, generated credentials or private result files. Do not add code simply
to reach a line-count target.

This baseline has no intentionally planted defects. Negative tests use invalid
inputs to verify rejection; they do not weaken production code. Future experimental
changes belong in separate branches with their own documented scope.
