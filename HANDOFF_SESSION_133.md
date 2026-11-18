# Handoff — Session 133 (2026-11-18): Full gate GREEN; example verdict run 743s → 8s

## What changed (UNCOMMITTED)
`skills/quantitative-backtesting/` only:

1. `examples/falsifiable_hypothesis_example.py`
   - Sections 7–8 (held-out-window resolution curve; minimum-detectable-alpha
     vs sample size, 15 `measure_synthetic` runs up to 10,000 bars) were moved
     out of `run_hypothesis_test()` into a new `print_resolution_measurements()`
     function. Body moved verbatim (only re-indented), so the printed numbers
     are unchanged.
   - `run_hypothesis_test(..., resolution_curves=False)` now runs them only when
     asked; the CLI flag `--resolution-curves` (also threaded through
     `_run_on_real_market`) opts in. Verdict, criteria, `resolution` (section 6)
     and the returned dict are unchanged.
   - Rationale: sections 7–8 are measurement-only and take ~75s per call. They
     were inside the verdict function, so the cost sweep (5 levels) re-ran them
     5 times and every direct-call test paid for them too.
2. `tests/test_falsifiable_hypothesis_example.py`
   - New guard `test_the_verdict_run_does_not_execute_the_expensive_resolution_curves`
     (patches `print_resolution_measurements` to raise; asserts default run and
     default argument), registered in `TEST_REGISTRY`.
3. `examples/README.md` — one paragraph documenting `--resolution-curves`.

## Correction of the previous handoff's attribution
The prior two handoffs called the 2 failures "environmental sandbox slowness".
That was wrong: a standalone run of the example took **742.86s wall** on an idle
machine (test timeouts are 480s/600s), and it was **deterministic** —
`run_hypothesis_test` executed the ~75s curve block, and the cost sweep called
`run_hypothesis_test` 5 more times (≈6 × 75s ≈ 450s of duplicate measurement).
Measured before the change: `WALL:742.86 USER:743.12`, EXIT 0.

## What was actually verified (evidence)

| Check | Result |
|-------|--------|
| Example default CLI | `WALL:8.25`, EXIT 0, verdict `NOT SUPPORTED`, 124 lines; asserts `TEST RESOLUTION`, `HOW TO READ THIS VERDICT:`, raw/deflated alpha p-values, `Test observations:` all present |
| Opt-in path | `--resolution-curves --no-cost-sweep` EXIT 0 inside a 150s timeout; prints `7. HELD-OUT…`, both `Series:`, and all 15 rows of `8. MINIMUM DETECTABLE…` — same numbers as the pre-change 743s run |
| New regression guard | PASS |
| `tests/test_resolution_vs_sample_size.py` + new guard | 80 passed in 1079.78s |
| Full `tests/test_falsifiable_hypothesis_example.py` | 33 passed in 263.12s |
| Both previously timing-out tests (`test_the_example_prints_the_resolution_and_the_reading_note`, `test_walk_forward.py::test_falsifiable_hypothesis_example_runs`) | PASS (part of the 34-passed focused run) |
| **Full quant gate** | `python3 -m pytest tests/ -q -n 4 -p no:cacheprovider` → **1505 passed, 0 failed, EXIT 0** in 2615.06s (43:35; the prior session needed 85 min and still failed) |

Gate-dirtied generated artifacts (`examples/example_reproducible_output/{data_provenance.json,tear_sheet.html,tear_sheet_summary.json}`, 1 line each, run timestamps) were reverted with a scoped `git checkout --` on that directory only.

## What remains unresolved
- The change is **uncommitted** (user has not asked for a commit).
- `pytest-xdist` is still not pinned in `requirements.txt`, so the `-n 4` gate
  is not reproducible from a clean checkout without an explicit install.
- No profitability/capacity claim. Verdicts on committed fixtures remain
  `NOT SUPPORTED`.
- **Methodological inconsistency found while verifying (next task):** the cost
  sweep silently disables criterion 5. `run_cost_sensitivity_sweep` defaults
  `benchmark_path` to `data_path.parent / "sample_benchmark.csv"`, so the
  per-level runs load **one** benchmark and `deflated_alpha_ratio` is `None`
  (`n_benchmarks = 1`), printed as `DAR N/A` and reported as
  `deflated_alpha_ratio_gt_0.90` *failing* in every row. Directly measured:
  `run_hypothesis_test(sample_ohlcv.csv, commission=0, slippage=0)` (no
  benchmark override, so `BENCHMARK_FILES` = 2) gives
  `DAR = 0.33238333944988946`; at 2bp+1bp, `DAR = 0.32860290711605894` with
  `n_benchmarks = 2`. The sweep's verdicts therefore mean something different
  from the headline verdict.

## Do not repeat
- Do NOT re-run the full gate hoping the example finishes: the deterministic
  cause is fixed and the gate is green (1505 passed).
- Do NOT delete sections 7–8 or their numbers: they are preserved behind
  `--resolution-curves` and covered by `tests/test_resolution_vs_sample_size.py`.
- Do NOT tune parameters/costs/verdicts to force SUPPORT.

## One precise next task (evidence-based)
Make the cost sensitivity sweep evaluate the **same** benchmark set as the
headline test so criterion 5 is genuinely evaluated:
- Inspect `examples/falsifiable_hypothesis_example.py:912+`
  (`run_cost_sensitivity_sweep`, the `benchmark_path` default) and how
  `run_hypothesis_test` resolves `BENCHMARK_FILES` when `benchmark_path is None`.
- Change the sweep to leave `benchmark_path=None` (or resolve `BENCHMARK_FILES`
  itself) so each row reports a real `deflated_alpha_ratio`, except when a
  caller explicitly passes one benchmark — and in that case say in the output
  that criterion 5 is unavailable, instead of listing it as failed.
- Add a regression asserting the sweep rows have `n_benchmarks >= 2` and a
  finite DAR on the committed sample, and that an explicit single-benchmark
  override is reported as unavailable rather than failed.
- Then run `tests/test_falsifiable_hypothesis_example.py` and the full gate
  (`-n 4`; baseline now **1505 passed**, ~44 min). Revert only
  `examples/example_reproducible_output/` if the gate dirties it.
