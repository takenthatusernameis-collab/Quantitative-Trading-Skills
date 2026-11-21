# Handoff — Current State: CPCV EMA/SMA crossover audit complete

## Audit findings

**EMA crossover (test_cpcv_ema_crossover_real_aapl.py):**
- 5/5 folds trade — EMA with `adjust=False` produces valid values from bar 1, no warmup needed
- No lookback/window mismatch
- Pinned metrics verified

**SMA crossover (test_cpcv_sma_crossover_real_aapl.py):**
- 4/5 folds trade — fold 0 has no warmup data (starts at index 0), SMA needs 50 bars for first valid value, 60-bar test window leaves only 10 valid bars, no crossover occurs
- This is documented and expected: `folds_with_position == 4`, `partial_selection_diagnosis` correctly identifies `no_position_in_validation_window`
- Pinned metrics verified on the 4 trading folds

**Vacuous NaN metrics:**
- None found — code correctly returns `None` (not NaN) for metrics when no folds trade
- `no_selection_diagnosis` and `partial_selection_diagnosis` provide clear explanations
- All summary metrics are either finite numbers or `None`

**Other CPCV tests with 4/5 folds (same root cause — fold 0 lacks warmup):**
- dual_momentum (lookback=252)
- kelly_criterion (lookback=63)
- volatility_targeting (lookback=63)
- All properly document and assert the partial selection

## Verdict

No fix needed. The CPCV warmup mechanism works correctly for folds 1-4. Fold 0 cannot have warmup data because it's at the start of the dataset — this is a fundamental limitation, not a bug. Tests honestly record the partial selection.

## Next task

Investigate CPCV Kelly criterion and volatility targeting tests (both expect 4/5 folds with lookback=63) to verify their partial selection diagnosis is as complete as the dual_momentum test, which explicitly asserts on `partial_selection_diagnosis.cause == "no_position_in_validation_window"`.