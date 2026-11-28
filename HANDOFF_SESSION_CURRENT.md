# Handoff — CURRENT — FULL regression sweep done (green baseline) + 1 stale-fixture fix

## What changed (this session)
Executed the next task from HANDOFF_SESSION_169.md: regression-sweep the test
suite. Swept ALL 330 `skills/quantitative-backtesting/tests/test_*.py` files in 4
foreground chunks (background_process can't see the repo). ONE tracked file
modified, test-only (no engine/fixture/hash/catalog change):
`skills/quantitative-backtesting/tests/test_test_window_observations.py`
(+17/-3). NOTHING committed. `git diff --stat` = that 1 file only.

## Verified (evidence)
- Chunk totals: 218 + (639+278) + (535+146) = 1816 passed; 12 failed.
- 11 failures were ALL `ModuleNotFoundError: matplotlib` in test_reporting.py →
  fixed by `pip install matplotlib` (3.11.2); test_reporting.py now 73 passed.
- 1 failure = stale parity fixture: legitimate `capacity_detail` key (commit
  646ad85) postdates the pre-rename baseline (6074e3b). All other metrics,
  returns, renamed key (=100) and summary Sharpe bit-identical. Fixed by
  allow-listing exactly `capacity_detail` + asserting it is present.
- Genuine-guard proof: injecting a bogus key still makes the guard FAIL.
- `pytest tests/test_test_window_observations.py` → 7 passed.
- Green baseline now 1828/1828 (0 failures).

## Environment
Python 3.14.4; numpy/pandas/scipy/pytest/pytest-timeout/matplotlib installed via
pip (package network available). Full suite ~55 min → must chunk. Heavy files:
test_resolution_vs_sample_size.py (~13m), test_walk_forward.py (~8m).

## Unresolved
- Data provenance (pre-existing): committed real_market_data is synthetic/
  placeholder; `_real_*` tests only check the manifest. Do NOT fabricate/edit
  hashes. Treat "profitable" output as synthetic-data artifact only.
- Suite re-dirties 4 generated runtime artifacts; I reverted them.

## Approaches that already failed (do not repeat)
- No offline data-provenance restoration; no fabricating/editing hashes.
- No re-debug of estimate_capacity / regime forwarding (present & guarded).
- background_process FS namespace hides repo — run foreground with timeout.
- Do NOT run all 330 files in one pytest call (killed >50 min); chunk it.

## One precise next task
Baseline is green. Higher-value next task: add NEW file
`test_pit_threshold_boundary_synthetic.py` tuning a look-ahead's next-return
correlation to just above/below the 0.3 PIT threshold, showing above→strict
abort (inflation prevented) and below→gate passes yet still inflates (honest
statement of the detector's limitation). New file only; no engine changes; run
tests only; do not commit unless asked.

See HANDOFF_SESSION_170.md for full detail.

(End of file)