# Handoff — per-path resolution assertions added (2026-10-25)

## What changed
- Added additive assertions to `test_the_example_reports_the_test_resolution`
  in `skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`
  that `res["paths"]` contains `out_of_sample`, `walk_forward`, and `cpcv`,
  each with `minimum_detectable_sharpe` and `minimum_detectable_alpha`.

## What was actually verified
- Focused test passes: 1/1 in 37.7s.

## One precise next task
- Re-run the slow framework suite (test_walk_forward.py, test_cpcv.py,
  test_resolution_vs_sample_size.py) to confirm no regression, then pick one
  bounded quant research task.
