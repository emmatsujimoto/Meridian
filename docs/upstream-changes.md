# Recorded local changes to Stockpyl v1.0.2

Original file checksums are in `upstream-manifest.json`; current checksums for
modified files are in `upstream-local-hashes.json`. Algorithm authorship and MIT
notices are retained. Changes are fixes and compatibility maintenance, not seeded defects.

- `helpers.py`: use SciPy's vectorized Irwin-Hall implementation for the sum of
  continuous uniforms. The older custom CDF failed when newer NumPy/SciPy passed
  array arguments. Validate positive integer sample count and finite ordered bounds.
  The new application tests verify exact moments, vector inputs and support boundaries.
- `test_demand_source.py`: replace an approximate integration-derived standard
  deviation with the exact formula `sqrt(n * (hi-lo)^2 / 12)` for the continuous
  uniform-sum regression. Numerical tolerance is not weakened.
- `tests/settings.py`: enable the previously skipped list-parameter regression.
- Mathematical docstrings in `eoq.py`, `newsvendor.py`, `loss_functions.py` and
  `wagner_whitin.py`: escape literal backslashes that produced Python 3.12 syntax
  warnings. No numerical behavior is changed.

The application does not call jsonpickle deserialization. User-supplied configuration
is parsed with the standard JSON library. The retained Stockpyl fixture loader reads
the bundled public inventory examples.
