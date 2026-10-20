# Handoff — 2026-10-20 (session)

## What changed

`scripts/measure_resolution_vs_sample_size.py` now measures the resolution-vs-sample-size ladder **for every analysis path**, not only the out-of-sample one, and reports the deflation floor (SR*) as a first-class number per path and per rung.

- `scripts/measure_resolution_vs_sample_size.py`:
  - New path runners `_run_walk_forward` (line 234) and `_run_cpcv` (line 263) call the framework's own `walk_forward_analysis` / `cpcv_analysis` at the shipped configuration (`WF_TRAIN_MONTHS/TEST/STEP = 6/2/2`; `CPCV_N_SPLITS, CPCV_TEST_SIZE = 5, 0.2`, line 139). The out-of-sample path keeps its own configuration.
  - `_measure_path` (line 291) reads the framework's **own** `summary["test_resolution"]` block for a path (plus its Deflated Sharpe/Alpha block for SR*) — it does not rebuild it. The out-of-sample path still uses `_build_test_resolution` exactly as before, so its numbers are unchanged.
  - `_measure_sample` (line 339) returns the primary path's fields at the top level (unchanged names, unchanged values) plus a new `"paths"` mapping with one block per measured path (`min_detectable_sharpe`, `min_detectable_alpha`, `expected_max_sharpe`, `n_test_observations`, `n_parameter_trials`, `sharpe_beyond_plausible_bound`, `n_windows`, …).
  - `_summarize_path` (line 563) is now per path; `summarize` (line 698) keeps the primary path's summary at the top level and adds `summary["by_path"]` for every measured path. Each path reports its crossing point (`first_size_all_within_bound` / `first_size_any_within_bound`), the floor per rung (`per_size[*].max_expected_max_sharpe`), `floor_at_largest_size`, and `floor_beyond_plausible_bound` (true only when the floor is above the bound at **every** measured rung — the "no sample size at all" answer).
  - `print_table` / `print_path_summary` print one table and one summary per path; `main` (line 803) gained `--paths` (default: all three; the out-of-sample path is always measured because the pre-registered criteria live on its held-out test window).
  - Two honest-reporting fixes found while doing this: a path whose resolution is **not computable** now prints `n/a` instead of "within bound", and a draw that did not resolve no longer counts towards "every draw inside the bound".
- `tests/test_resolution_vs_sample_size.py`: 4 -> 9 tests (5 new: every path is measured and reports its own resolution; each path's block equals the framework's own `summary["test_resolution"]` on a directly re-run analysis; the three paths cross the plausibility bound at **different** sample sizes; SR* is reported per path and per rung; no threshold/flag/verdict moves on any path).
- `references/validation_methods.md`: new subsection "The three analysis paths answer it differently" (measured table + mechanism + what it does not establish); "What this does not establish" gained the per-path caveat.
- `SKILL.md` (script description and the resolution bullet) and `examples/README.md` updated with the per-path result.

## What was verified

- `tests/test_resolution_vs_sample_size.py`: **9/9** (90 s).
- Neighbouring suites, unchanged by this work: `test_test_resolution.py` 38/38, `test_cpcv.py` 29/29, `test_run_backtest.py` 104/104, `test_walk_forward.py` 183/183.
- `pyflakes` clean on both changed files (4.0.3).
- Full default ladder run (`python3 scripts/measure_resolution_vs_sample_size.py`, 5 rungs x 3 seeds x both series, ~2 min) — the numbers quoted in the docs come from that run; the out-of-sample path's numbers are byte-identical to the pre-change script (e.g. 2,500 bars: 2.3975 / 2.4011, SR\* 1.4403 / 1.4985), so the primary path did not move.
- JSON output (`--json`) still parses and now carries `rows[].paths` and `summary.by_path`.

### The measured result (control fixture, 3 seeds x both series)

| Path | min confirmable annualized Sharpe at 2,500 bars | at 10,000 bars | first rung every draw is inside the bound | SR\* at the largest rung |
| --- | --- | --- | --- | --- |
| out-of-sample (held-out test window) | 2.13 – 3.23 | 1.52 – 1.82 | 10,000 bars | 1.38 |
| walk-forward (pooled OOS windows) | 1.74 – 2.26 | 1.12 – 1.45 | 5,000 bars | 1.21 |
| CPCV (pooled OOS folds) | 1.41 – 1.95 | 0.67 – 1.15 | 2,500 bars | 0.70 |

The out-of-sample path is the binding constraint: it prices criterion 2 on the held-out window (20% of the sample), so its test observations grow at a fifth of the rate the sample grows. The CPCV path's floor is the lowest (0.45 – 1.04 against 1.24 – 2.23 at 2,500 bars) because it evaluates far fewer configurations per fold (75 against 233 trials).

## What remains unresolved

- The crossing points are properties of the synthetic control fixture and the shipped configuration; no real history was measured (the repo has no real market data, and `--data` is untested on one).
- The walk-forward and CPCV paths are measured on the **whole** sample, while the out-of-sample path's test is on its held-out window. That asymmetry is the finding, but it also means the three curves are not "the same experiment run three ways".
- The alpha resolution (criteria 3 and 5) is carried per path in the table but is not summarised per path the way the Sharpe resolution is.

## Approaches that failed

- One test assertion was wrong on the first run: I asserted the out-of-sample path's "some draw inside the bound" crossing was 10,000 bars; it is 5,000 (two of the six draws at 5,000 bars are inside the bound). Fixed by reading the measured ladder, not by relaxing the assertion.
- A duplicate `"floor_beyond_plausible_bound"` key in the summary dict literal silently overrode the corrected per-rung definition with the old "max over the ladder" one; caught by re-reading the printed summary, then removed.

## Next task (one, precise)

**Measure the out-of-sample path's resolution as a function of the held-out fraction (`test_frac`)** — i.e. answer "how much of my data should I hold out, so that the held-out test window can resolve a plausible effect?".

The session's finding makes this the natural next question: the out-of-sample path is the binding constraint *because* criterion 2 is evaluated on the held-out window. Sweep `test_frac` (holding `val_frac = 0.2` and `train_frac = 0.8 - test_frac`) at a fixed sample size, on the same control fixture, and report per `test_frac`: `min_detectable_sharpe`, SR\*, and the crossing point. The trade-off to measure: a larger held-out window gives more test observations (better resolution) but a shorter training window, which raises the SR\* floor (the trial Sharpes are estimated on less data).

- Tool: `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py` — the shipped split is module constants (`TRAIN_FRAC, VAL_FRAC, TEST_FRAC`, line 133); `measure_synthetic` (line 432) / `measure_ladder` (line 507) / `_measure_sample` (line 339) / `_run_validation` (line 202, the `out_of_sample_validation` call) is the per-sample chain; `main` (line 803) is the CLI entry point. The framework call is `out_of_sample_validation(train_frac=…, val_frac=…, test_frac=…)`.
- Constraints: the shipped 0.6/0.2/0.2 split must stay the default and must not change; the sweep is a measurement beside the verdict (no threshold, bound, criterion or verdict moves); re-use the framework's own `summary["test_resolution"]` block rather than re-deriving it; the fixture is the synthetic control (a formula, not a market).
- Verification: extend `tests/test_resolution_vs_sample_size.py` with a pin that the sweep's numbers equal the framework's own blocks for the same split, and that the shipped default split is unchanged.
- Subsequent options after that: summarise the **alpha** resolution per path (criteria 3 and 5 cross the 10% bound later than criterion 2 crosses the 2.0 bound — e.g. CPCV at 10,000 bars still reports 12.6% on one draw), and the `test_n_periods` rename (an API change needing its own parity harness).
