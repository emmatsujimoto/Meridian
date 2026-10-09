# Sources and attribution

## Stockpyl

- Project: https://github.com/LarrySnyder/stockpyl
- Author: Lawrence V. Snyder and contributors.
- Release: v1.0.2.
- Source commit: `097d99e2c0cd469465933f1aec3608796177010d`.
- License: MIT; preserved in `licenses/STOCKPYL-LICENSE.txt`.
- API documentation: https://stockpyl.readthedocs.io/
- Tutorial: Snyder, L. V. (2023), *Stockpyl: A Python Package for Inventory
  Optimization and Simulation*, INFORMS TutORials in Operations Research.

Selected source modules, algorithm regression tests and their public fixtures
are copied from that tagged release. `docs/upstream-manifest.json` identifies
every copied file and its original SHA-256 checksum. Local changes, if any, are
recorded in `docs/upstream-changes.md`; the integrity script verifies current hashes.

The selected modules include EOQ, newsvendor, Wagner-Whitin, demand sources,
inventory simulation and the supporting network/state classes. Other upstream
optimization families, notebooks, built documentation and full test suites are
not included. The upstream package's documentation/build dependencies are not
needed at runtime here.

## New work

`src/meridian`, `tests/meridian`, repository maintenance scripts, configuration,
synthetic site data and project documentation are AI-assisted new work for this
fictional application. The company name and all operational numbers are invented.
The repository contains no client exports, real customer information, logos or
identifying client references.

Third-party Python dependencies remain under their respective licenses and are
installed separately. Their source is not counted in the repository size.
