# Handoff — Next Session (2026-11-21): baseline verified; fat_tail_crash detector thread exhausted

## Baseline
- HEAD `6cef808`, branch `main`; working tree clean except one uncommitted change (the `TEST_REGISTRY` fix below). Do NOT commit unless asked.
- Session 148 completed the crash-trigger detector experiment for `fat_tail_crash` (see `HANDOFF_SESSION_148.md`). Detector-tuning thread is EXHAUSTED: uniform target_vol 0.20 is best; no regime-sizing variant recovers the degradation. Best deltas vs default: SMA -0.0533, EMA -0.3701 (uniform tv=0.20). All results are point estimates on synthetic adversarial data (DSR p ≈ 1.0); no profitability claim.

## What changed this session
- Ran full quant suite: `skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` → **1541 passed, 1 failed** (was 1540 passed, 2 failed before the fix).
- Fixed deterministic failure: `test_out_of_sample_summary_carries_sharpe_ratio_alias` (`skills/quantitative-backtesting/tests/test_walk_forward.py:1393`) was defined but missing from `TEST_REGISTRY` (line 6985). Registered it → `test_main_registers_every_module_level_test` now passes. This is a one-line addition to `TEST_REGISTRY`.
- Reverted unrelated timestamp regenerations in `results/simple_momentum_hypothesis.json` and `skills/quantitative-backtesting/examples/example_reproducible_output/{data_provenance.json,tear_sheet.html,tear_sheet_summary.json}` caused by test-suite output rewrites (load_timestamp/generated_at). Working tree contains only the `TEST_REGISTRY` addition.
- `skills/quantitative-backtesting/requirements.txt` already pins `pytest-xdist==3.8.0`; `/tmp/venv` has pytest 9.2.0 + pytest-xdist.

## What was actually verified
- `test_walk_forward.py`: **226 passed, 0 failed** (single worker and `-n 4` parallel).
- Full suite: **1541 passed, 1 failed**. The sole remaining failure is a pre-existing `sharpe_ratio` summary key-set assertion that reproduces ONLY under full-suite `-n 4`, never in any isolated file run — not caused by this session's change (pytest does not use `TEST_REGISTRY`).
- Evidence: full-suite set diff shows `sharpe_ratio` missing/extra among keys `{book_diagnostic, capacity*, test_sharpe, test_total_return, test_volatility}`.

## What remains unresolved
- Identify/fix the non-reproducible full-parallel `sharpe_ratio` key-set failure (appears only in full-suite `-n 4`). Not blocking focused verification.
- Then begin the new quant research thread (below).

## Approaches already failed (do not repeat)
- Crash-trigger / crash-only / per-regime target_vol detector tuning on `fat_tail_crash` (session 148): all worse than uniform tv=0.20; thread exhausted.

## One precise next task
Start the new quant research methodology thread recommended in `HANDOFF_SESSION_148.md`:
**Option 2 — Returns-based regime detection on `fat_tail_crash` at uniform tv=0.20.**
Detect `bear_high` from cumulative negative returns instead of volatility quantiles; reuse `detect_combined_regime` + `walk_forward_analysis`; no statistical-significance or profitability claims; synthetic adversarial data; do not commit unless asked. Compare delta vs the uniform-tv=0.20 baseline (SMA -0.0533, EMA -0.3701).

Evidence locations: `skills/quantitative-backtesting/scripts/crash_only_detector.py`, `skills/quantitative-backtesting/examples/crash_only_results.json`, baseline repo-root `adversarial_stress_test_results.json`. Environment: `source /tmp/venv/bin/activate`.
