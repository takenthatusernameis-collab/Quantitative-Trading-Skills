# Handoff — Session (2026-11-16): TSMOM book-based capacity vs deployed capital

## Baseline (committed, green)
- HEAD `3617336` (session 126): capacity-sensitivity sweep + deployed-capital report committed; working tree was clean at session start.
- Full gate last confirmed green: `pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` -> **1470 passed, 0 failed** (before the `deployed_capital` test was committed, so that test was NOT in a full gate run).
- Previously flagged CPCV behavior-pin failures reconciled: `test_no_selection_diagnosis.py` -> **34 passed** (the 15 "failures" are gone). `test_resolution_vs_sample_size.py` slow, not re-run here.
- PIT/survivorship and reality-check/romano-wolf coverage already present.

## What changed (this session, UNCOMMITTED)
- **Modified** `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`:
  - `run_capacity_sensitivity_sweep` rows now include `oos_min_capacity_book` (worst-OOS-window book-based capacity) alongside `capacity`/`capacity_book`/`oos_min_capacity`.
  - `run_oos_min_capacity_vs_deployed_capital_report` now also reports `oos_min_capacity_book`, `capacity_constrained_book`, `flag_book` per impact level vs pinned `DEPLOYED_CAPITAL_REFERENCE=100000.0`. Basket-based `capacity_constrained`/`flag` unchanged (additive). Impact-disabled level -> `None` / "UNMEASURABLE (impact off)" for both.
- **Extended** `tests/test_walk_forward_time_series_momentum_oos_min_capacity_vs_deployed_capital_real_triple_aapl_msft_googl.py`: added book-based assertions (impact-0 UNMEASURABLE; impact-enabled levels finite book capacity, valid `flag_book`, `capacity_constrained_book` consistent with `flag_book`).
- Working tree has **uncommitted** source changes (not committed, per instructions).

## What was actually verified (evidence)
| Check | Result |
|-------|--------|
| Capacity sensitivity test | `pytest ...capacity_sensitivity_real_triple... -q` -> **1 passed (1.73s)** |
| Deployed-capital test (book-extended) | `pytest ...oos_min_capacity_vs_deployed_capital_real_triple... -q` -> **1 passed (1.72s)** |
| Combined | **2 passed in 2.65s, EXIT 0** |
| Compile | `py_compile` on both files -> clean |

## What remains unresolved
- Full quant gate NOT re-run after these uncommitted changes. Run `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` (EXIT 0, ~1472+ passed, ~48 min). Revert ONLY generated artifacts (`examples/example_output/*`, `scripts/results/*`) after — do NOT `git checkout -- .` blindly, as it would revert the uncommitted source changes above; commit them first if desired.
- Next methodological gap per AGENTS.md mission: borrow/funding cost realism or a new falsifiable hypothesis with OOS evidence net of costs — NOT another strategy falsification test.

## Approaches already tried / failed (do not repeat unchanged)
- None new this session.

## One precise next task
Run the full quant gate to confirm green after the uncommitted changes, reverting only generated artifacts (preserve uncommitted source). Then pick the next bounded methodological gap per AGENTS.md mission.
