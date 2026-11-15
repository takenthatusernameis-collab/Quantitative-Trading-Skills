# Handoff — CPCV book-pricing diagnostic warmup fixed; 17 pre-existing CPCV behavior-pin failures remain (root cause identified)

## What changed (this session)
- Resumed at committed HEAD `94e003c` (working tree clean). The prior commit `94e003c`
  added CPCV book-pricing code (`_window_book_diagnostic(..., warmup_data=...)`) and three
  `test_cpcv.py` book-pricing tests, but left 2 of them failing.
- Root cause of the 2 failures: in `cpcv_analysis`, the per-fold call
  `_window_book_diagnostic(...)` at `skills/quantitative-backtesting/scripts/walk_forward.py:4220`
  was NOT passing `warmup_data`, while the return calculator for the same fold DOES use
  `warmup_data` (lines 4001-4011). So the diagnostic re-derived the target book on the bare
  25-bar test window, where rolling indicators are still NaN -> the book read as flat
  (`gross_book == 0.0`) and its `return_gap_total` did not match the measured
  net-exposure-minus-book return gap.
- Fix (1 file, +6 lines): pass `warmup_data=fold.get("warmup_data")` to
  `_window_book_diagnostic` in the CPCV fold loop. The fold already carries `warmup_data`
  (set at line 3931/3942). This makes the diagnostic measure the book on exactly the bars
  the returns were computed on. Measurement-only change: no return, cost, impact or capacity
  number is altered.
- NOT committed (per instructions).

## What was actually verified (this session)
- `python3 -m pytest skills/quantitative-backtesting/tests/test_cpcv.py -p no:cacheprovider -q`
  -> **30 passed** (was 28 passed, 2 failed). Both previously-red book-pricing tests now green:
  - `test_cpcv_book_pricing_backtests_a_market_neutral_book`
  - `test_cpcv_book_pricing_differs_by_the_measured_return_gap`
  - `test_cpcv_pinned_number_is_reproducible_from_first_principles` passes (framework and
    `_independent_cpcv_oos_return` both agree at the 0.024436091162034046 reference; the
    prior session's warmup rewrite of the independent re-implementation is what made them agree).
- `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py
  skills/quantitative-backtesting/tests/test_panel_reference_pinned.py -k "book or cpcv"`
  -> **39 passed** (no regression in the non-CPCV walk-forward book-diagnostic path, whose
  `_window_book_diagnostic` calls at lines 6495/6590 intentionally use the bare window because
  that path also computes signals on the bare window).
- `python3 -m compileall -q skills/quantitative-backtesting/` -> clean.

## What remains unresolved (pre-existing, NOT introduced by this session)
### 17 failures, all tracing to ONE root cause: the CPCV indicator-warmup convention change
The CPCV path now generates signals on `warmup_data + test_data` (indicator warmup from the
bars immediately preceding the test window; strictly pre-test, so no leakage). This is
methodologically sound, but it changed CPCV out-of-sample behavior and invalidated pinned
expectations in two files (both last touched at baseline `c47a7c0`; they were already failing
at `4115346` per the previous handoff):

- `test_no_selection_diagnosis.py` — 15 failed / 96 total in the pair run:
  `test_cpcv_analysis_records_the_no_selection_diagnosis`,
  `test_cpcv_diagnosis_names_the_effective_out_of_sample_fraction`,
  `test_cpcv_cli_prints_the_diagnosis_next_to_the_fold_count`,
  `test_the_remedy_names_flags_the_path_actually_accepts`,
  `test_the_overfitting_risk_verdict_is_not_applicable_when_nothing_was_selected`,
  `test_the_diagnosis_changes_no_number`,
  `test_the_all_flat_case_still_uses_the_no_selection_diagnosis`,
  `test_the_partial_run_is_reproducible`,
  `test_the_pre_fix_artifact_named_no_cause_for_the_flat_folds`,
  `test_the_cpcv_partial_diagnosis_names_every_flat_fold`,
  `test_the_overfitting_risk_verdict_is_qualified_but_unchanged`,
  `test_the_partial_diagnosis_changes_no_number`,
  `test_the_partial_run_carries_a_thin_evidence_warning`,
  `test_the_thin_evidence_warning_changes_no_number`,
  `test_min_position_fraction_rejects_the_partial_run`.
  Evidence of the behavior shift (measured this session): the default CPCV run
  (`n_splits=10, test_size=0.1`, 5-bar windows) that used to select NOTHING now reports
  `n_folds=10, folds_with_position=7, total_oos_return=0.01885897762984934,
  oos_sharpe=1.0180341648451239`. The canonical partial run (`n_splits=5, test_size=0.2`)
  now selects in 4 of 5 folds (tests pin 2 of 5; `folds_with_position == 4` vs pinned `2`).
- `test_resolution_vs_sample_size.py` — 2 failed:
  `test_the_alpha_bound_is_crossed_later_than_the_sharpe_bound`
  (`CPCV first_size_any_within_alpha_bound` now 5000, test pins 2500) and
  `test_an_unpriceable_alpha_floor_is_reported_as_unpriceable` (CPCV Deflated Alpha criterion
  is now `resolvable`, test expects `not_resolvable`). Same cause: more usable CPCV bars per
  fold changes the resolution ladder.

These are pinned-behavior tests that must be reconciled with the (sound) warmup convention:
either re-pin to freshly measured values after confirming the warmup is the intended,
non-leaky convention, or (only if evidence shows the warmup leaks) revert the warmup. Do NOT
blindly re-pin to silence: re-derive each expected number from a measured run and record the
convention in a comment.

## Approaches already tried / failed (do not repeat unchanged)
- Blindly recalibrating pins to force green: REJECTED (weakens guards; not methodological progress).
- Manually iterating pin-chase past judgment cases: STOPPED — those fail on verdict criteria, not pins.
- Full gate `-n 4` / serial on the whole tests dir: times out in-session; defer to CI / adequate-budget env.
- "Fix" the 2 book-pricing tests by re-deriving expected values: NOT NEEDED — the defect was a
  real missing-argument bug, fixed at the source (see What changed).

## Known limitations of regenerate_pins.py (still apply)
- Tolerance re-base skips when the exp literal appears >1x in a file (uniqueness guard).
- `_update_nested_dict` only handles nested `{key: {metric: val}}`; flat tuple->tuple dicts
  (`EXPECTED_METRICS = {(2,1): (sharpe, ret), ...}`) are not handled.
- Multi-var structural asserts (n_periods vs periods_with_position sharing a source literal)
  still need a manual split.

## One precise next task (for the next agent)
Reconcile the 17 pre-existing CPCV behavior-pin failures with the warmup convention, in this order:
1. Confirm the warmup is causal (it is: `warmup_data = data.iloc[warmup_start_idx:test_start_idx]`,
   strictly before the test window; used only to initialize rolling indicators). State this in a
   short comment so a future reader does not "fix" it back.
2. In `test_no_selection_diagnosis.py`, re-pin the CPCV default/partial-run expectations
   (`folds_with_position`, `best_params_per_fold`, thin-evidence details, overfitting-risk reason
   counts) to freshly measured values, keeping the tests' intent (they assert the diagnosis
   schema, not specific numbers). The default run now selects 7/10 folds; the partial run 4/5.
3. In `test_resolution_vs_sample_size.py`, re-pin the CPCV ladder expectations
   (`first_size_any_within_alpha_bound`, `alpha_status`) to measured values; if CPCV is now
   `resolvable` at the pinned history length, update the test to assert the resolvable case and
   keep a separate reproducer that exercises the genuinely-unpriceable case (or drop that test's
   premise if the framework can now always price it — document why).
4. After green: run the full gate in CI / adequate-budget env
   (`python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`).
5. Then pick the next bounded methodological gap per AGENTS.md mission (point-in-time /
   survivorship-bias controls, or a new falsifiable hypothesis with OOS evidence net of costs) —
   NOT another strategy falsification test.
6. Do not commit unless explicitly asked.