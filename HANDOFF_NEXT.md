# Handoff — per-path resolution in falsifiable example (2026-10-25)

## What changed
- `_test_resolution` already carries `resolution["paths"]` with per-path
  `minimum_detectable_sharpe`/`minimum_detectable_alpha` (and supporting counts)
  for out_of_sample, walk_forward, and cpcv. Verified example exits 0 and
  test_falsifiable_hypothesis_example.py passes (17/17 per prior record).

## What remains unresolved
- The resolution-block test only asserts top-level out-of-sample keys; no
  assertion yet that `resolution["paths"]` carries all three paths' MDA/MDS.

## One precise next task
- Add additive assertions to `test_the_example_reports_the_test_resolution`
  that `res["paths"]` contains out_of_sample/walk_forward/cpcv each with
  `minimum_detectable_sharpe` and `minimum_detectable_alpha`. Run focused test.

## Constraints
- Smallest reversible change; do not redesign orchestration.
