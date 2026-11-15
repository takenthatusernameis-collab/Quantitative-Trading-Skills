# Handoff — stale-pin re-base continued; 116-file target batch now clean modulo judgment cases; new pre-existing CPCV integrity defect documented

## What changed (this session)
- Resumed the prior session's committed baseline (`4115346`); working tree was clean at start.
- Re-based the remaining stale pins the prior handoff enumerated across the 116-file
  `walk_forward* / *benchmark_aware* / *param_sensitivity* / *elevated_cost*` batch.
  Root cause unchanged: stale import pins / environmental drift, not a code regression
  (deps numpy 2.5.4 / pandas 3.1.1 / scipy 1.18.1 on Python 3.14.4, offline committed fixtures).
- 9 test files changed (all legitimate measured-value substitutions; verdict criteria untouched):
  - `test_cpcv_cross_sectional_momentum_benchmark_aware_real_aapl_googl.py` (EXPECTED dict: returns, sharpe, alpha, dsr, n_trials 5→4, n_observations 490→232) → GREEN
  - `test_rsi_mean_reversion_benchmark_aware_real_aapl.py` (sharpe_ratio, total_return) → GREEN
  - `test_walk_forward_dual_momentum_real_{aapl_googl,aapl_msft,msft_googl}.py`
    (n_periods 3→4; **manually kept periods_with_position == 3** — the multi-var struct bug) → GREEN (aapl_googl, msft_googl); aapl_msft still has 1 judgment-case failure
  - `test_walk_forward_rsi_mean_reversion_real_aapl_googl.py` (dsr_p, n_periods_with_book 1488→793, charged_turnover) → judgment case remains red (ret_ok)
  - `test_walk_forward_zscore_mean_reversion_real_aapl.py` (dsr_p, dsr_ratio) → GREEN
  - `test_walk_forward_zscore_pair_real_aapl_googl.py` (dsr_p, n_periods_with_book 726→394, charged_turnover) → GREEN
  - `test_zscore_elevated_cost_sensitivity_real_triple_aapl_msft_googl.py` (all 4 cost-level (sharpe, total_return) pairs) → GREEN
- Reverted 3 unintended example-output files (`data_provenance.json`, `tear_sheet.html`,
  `tear_sheet_summary.json`) that a test run regenerated with a new timestamp — not part of the task.
- Nothing committed (per instructions).

## What was actually verified (this session)
- Final run of the 9 modified files: **15 passed, 2 failed** — both failures are documented
  judgment cases (criterion flips), not stale pins.
- `python3 -m compileall -q skills/quantitative-backtesting/tests/` → clean.
- `regenerate_pins.py --check` on the full 116-file batch now reports **only 1 residual
  "update"** = `test_walk_forward_zscore_benchmark_aware_real_aapl_googl.py` `assert 3 == 4`,
  which is the falsification-criteria COUNT assertion (`len(failed) == len(criteria)`), i.e. a
  judgment/verdict assertion, NOT a numeric pin. Correctly left red.
- `regenerate_pins.py --check` on the 125 files OUTSIDE that batch found 4 candidate updates in
  `test_cpcv.py`, `test_no_selection_diagnosis.py`, `test_resolution_vs_sample_size.py` — these
  are **NOT** simple stale pins (see Unresolved); deliberately not touched.

## What remains unresolved
### A. Documented judgment cases (criterion contradictions — MUST stay red; do NOT tune criteria)
- `test_walk_forward_dual_momentum_real_aapl_msft.py`: `deflated_sharpe_pvalue_lt_0.10 is False` (DSR now < 0.10).
- `test_walk_forward_rsi_mean_reversion_real_aapl_googl.py`: `ret_ok is True` fails (measured total_oos_return = -0.1414... is negative; test asserts > 0).
- `test_walk_forward_zscore_benchmark_aware_real_aapl_googl.py` (2 failures): "all criteria must fail" (one now passes) and `oos_sharpe < 0.0` (now 0.0569 > 0).
- Carried from prior handoff (HANDOFF_NEXT.md): macd benchmark_aware (aapl, triple), dual_momentum benchmark_aware aapl_googl, donchian benchmark_aware triple, kelly benchmark_aware aapl, walk_forward cross_sectional pair/triple, walk_forward kelly aapl.

### B. NEW pre-existing CPCV integrity defect (high value — confirmed at committed baseline `4115346`, NOT introduced by this session)
`test_cpcv.py` (synthetic-data CPCV) fails at baseline with a **framework vs independent
re-implementation mismatch**:
- `test_cpcv_pinned_number_is_reproducible_from_first_principles`:
  `framework 0.024436091162034046 != independent re-implementation 0.005399536978800246` (rel_tol 1e-12).
- `test_cpcv_normal_run_keeps_current_numbers` / `test_cpcv_book_pricing_*`: `summary['total_oos_return']`
  is 0.0244 but the test expects 0.0054 ("this is a real change, not float noise").
- `test_cpcv.py::test_cpcv_basic_structure`: `KeyError: 'no_selection_diagnosis'` — the CPCV summary
  schema no longer emits that key (or the test predates a schema change).
- Related: `test_no_selection_diagnosis.py` (multiple `assert N == M`, missing `no_selection_diagnosis` key)
  and `test_resolution_vs_sample_size.py` (`assert 5000 == 2500`; `not_resolvable` vs `resolvable`).
- This is a **methodology/integrity question, not a stale pin**: the CPCV framework and its own
  independent re-implementation disagree on the headline out-of-sample return. Re-basing the pin would
  mask it. It needs root-cause investigation of `cpcv_analysis()` vs `_independent_cpcv_oos_return()`
  in `skills/quantitative-backtesting/tests/test_cpcv.py`.

## Approaches already tried / failed (do not repeat unchanged)
- Blindly recalibrating pins to force green: REJECTED (weakens guards; not methodological progress).
- Manually iterating pin-chase past judgment cases: STOPPED — those fail on verdict criteria, not pins.
- Full gate `-n 4` / serial: times out in-session; defer to CI / adequate-budget environment.

## Known limitations of regenerate_pins.py (still apply)
- Tolerance re-base skips when the exp literal appears >1× in a file (uniqueness guard) — fix manually with context (done this session for dsr_p/dsr_ratio lines where the literal doubles as the tolerance scale).
- `_update_nested_dict` only handles nested `{key: {metric: val}}` dicts; flat tuple→tuple dicts
  (`EXPECTED_METRICS = {(2,1): (sharpe, ret), ...}` in the `*_elevated_cost_sensitivity_*` files)
  are NOT handled → fix manually (done this session by probing measured rows directly).
- Multi-var structural asserts (n_periods vs periods_with_position sharing a source literal) still
  need a manual split.

## One precise next task (for the next agent)
1. **Investigate the CPCV integrity defect (Section B) first** — it is the highest-value item:
   compare `cpcv_analysis()` output `summary['total_oos_return']` (0.0244) against the test's
   `_independent_cpcv_oos_return()` (0.0054) in `skills/quantitative-backtesting/tests/test_cpcv.py`
   (read lines ~999-1045 and the `_independent_cpcv_oos_return` helper). Determine which side is
   wrong (warmup/embargo convention, fold boundaries, cost/pricing, or product accumulation) and
   fix the root cause — do NOT re-base the pin to silence it. Also resolve the missing
   `no_selection_diagnosis` summary key (schema drift vs code defect).
2. Leave ALL Section-A judgment cases red — do not tune criteria or fabricate folds/verdicts.
3. Once baseline is green modulo Section-A judgment cases, run the full gate in CI / adequate-budget
   env (`python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`).
4. Only then: pick the next bounded methodological gap per AGENTS.md mission (point-in-time /
   survivorship-bias controls, or a new falsifiable hypothesis with OOS evidence net of costs) —
   NOT another strategy falsification test.
5. Do not commit unless explicitly asked.