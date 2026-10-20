# Handoff — 2026-10-20 (session)

## What changed
Extended test-resolution (minimum detectable effect) reporting from `run_backtest.py`'s cost sweeps to every remaining sweep surface in `walk_forward.py`:

- `scripts/run_backtest.py`: moved `_sweep_sharpe_below_resolution`, `_sweep_resolution_fields`, `_print_sweep_resolution_note` to `scripts/utils.py` (deduplicated; `run_backtest.py` re-exports them, so existing `from run_backtest import ...` tests keep working). Restored `_print_sweep_table`, which the relocation clobbered. Dropped now-unused imports (`math`, `Optional`, `Tuple`).
- `scripts/utils.py`: hosts the three helpers (added `math`, `List`, `Optional`, `Tuple` imports).
- `scripts/walk_forward.py`: all five sweep row builders (`_walk_forward_sweep_coefficient`, `_cpcv_sweep_coefficient`, `_oos_sweep_coefficient`, `_monte_carlo_sweep_coefficient`, `_optimize_sweep_coefficient`) attach `test_resolution` + `sharpe_below_resolution` per sweep point. Monte Carlo builds its own block via `_build_test_resolution({"deflated_sharpe": dsr}, returns)` on the base returns. Parameter optimization reports explicitly unresolved (`null` block, `null` flag): `top_sharpe` is an in-sample selection statistic and no held-out returns exist in the sweep helper. Every sweep table (cost sweeps plus latency/fill-rate via the shared `_run_latency_fill_rate_sweep`) prints `minSR | note` beside the swept Sharpe and ends with the shared "Test resolution (measurement, not a correction)" note. Added `_resolution_cells` helper.
- `tests/test_test_resolution.py`: 28 -> 38 tests (11 new: each path's points carry their own resolution + flag; tables print threshold beside Sharpe; parameter optimization explicitly unresolved; no-significance-test sweep says so).
- `references/validation_methods.md`, `SKILL.md`: write-up (new subsection "The other analysis paths report the same resolution"; swept-Sharpe bullet extended to all five paths).

## What was verified
- `test_test_resolution.py`: 38/38. `test_run_backtest.py`: 104/104. `test_walk_forward.py`: 183/183. Remaining suite green except 9 pre-existing `test_reporting.py` failures (matplotlib missing; identical at HEAD).
- `pyflakes` clean on `run_backtest.py`, `utils.py`, `test_test_resolution.py` (`walk_forward.py` has 5 pre-existing notes on untouched lines).
- Empirical HEAD->now parity on commission sweeps for all six paths: `run_backtest` artifacts byte-identical; the five paths' pre-existing keys/values unchanged; only `test_resolution`/`sharpe_below_resolution` added; flags match `|Sharpe| < minSR`. Single-run artifacts and `test_output/` snapshot untouched.

## What remains unresolved
Nothing from the assigned task; it is complete.

## Approaches that failed
None (first-pass implementation passed; the relocation clobbered `_print_sweep_table`, caught by the suite and restored).

## Next task (one, precise)
Extend `scripts/measure_resolution_vs_sample_size.py` so its resolution-vs-sample-size ladder also covers the walk-forward and CPCV paths (it currently measures out-of-sample only): at each sample rung call `walk_forward_analysis`/`cpcv_analysis` and read `summary["test_resolution"].min_detectable_sharpe` plus `expected_max_sharpe` (SR*), on the same synthetic control fixture (`--data` also supported). Evidence: `scripts/measure_resolution_vs_sample_size.py:439` (`main`), lines 79-92 (imports), line 146 (`out_of_sample_validation` call). Subsequent options after that: SR* (floor) as a first-class reported number, and the `test_n_periods` rename.
