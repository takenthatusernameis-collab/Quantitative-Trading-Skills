# Handoff — CURRENT — PIT-violation sensitivity study done (5/5 green)

## What changed (this session)
Executed the next task from HANDOFF_SESSION_168.md: a controlled look-ahead
(point-in-time) sensitivity study on SYNTHETIC data. Added ONE new file:
`skills/quantitative-backtesting/tests/test_pit_violation_sensitivity_synthetic.py`.
No engine/fixture/hash/catalog changes; `git diff` (tracked) empty; NOTHING
committed. Controlled pair differs by one bar of look-ahead (clean =
`1{close[t]>close[t-1]}` vs look-ahead = `1{close[t+1]>close[t]}` =
clean.shift(-1)); engine fills at `signals.shift(1+latency)` so look-ahead earns
`|ret|` (perfect foresight).

## Verified (evidence)
- `python3 tests/test_pit_violation_sensitivity_synthetic.py` → 5/5 PASS, OK.
- pytest → 5 passed.
- Recorded delta the strict gate prevents: oos_sharpe clean -1.7044 vs look
  +8.8361 (Δ+10.54); total_oos_return clean -0.2374 vs look +2.6771 (Δ+2.91).
- Controls: clean passes PIT; look-ahead flagged (corr 0.545 > 0.300); gate OFF
  inflates; gate WARN-ONLY detects-but-continues; gate STRICT aborts look-ahead
  (ValueError) and passes clean.
- Genuine-guard proof: disabling the `walk_forward.py:869` strict abort makes the
  strict test FAIL; engine restored byte-for-byte (`git diff` empty).
- Regression: existing test_point_in_time_strict_abort_on_violation.py → 6 passed.

## Environment
Container had no numpy/pandas/scipy/pytest but pip has package network. Installed
`numpy pandas scipy pytest` (py3.14). Tests run via `python3 <file>` or
`python3 -m pytest <file>`. `timeout_method` warning is pre-existing/harmless.

## Unresolved
- Data provenance (blocked; committed real_market_data is synthetic/placeholder;
  do NOT fabricate or edit pinned hashes).
- Full 330-file suite not swept end-to-end; ~60 per-strategy real-data files
  unswept (walk-forward 253 + 15 non-WF + this 5 confirmed green).

## Approaches that already failed (do not repeat)
- No offline data-provenance restoration; no fabricating/editing hashes.
- No re-debug of estimate_capacity / regime forwarding (present & guarded).
- background_process FS namespace hides repo — run foreground with per-file timeout.

## One precise next task
Sweep the remaining ~60 per-strategy real-data files under
`skills/quantitative-backtesting/tests/` for regressions (foreground, per-file
`timeout 120 python3 -m pytest <file> -q`, offline, committed fixtures). Record
pass/fail; treat any "profitable" output as synthetic-data artifact only. Run
tests only; no engine/fixture/hash/catalog edits; do not commit unless asked.
Alternative: `test_pit_threshold_boundary_synthetic.py` demonstrating the 0.3
correlation threshold's limitation (above→abort, below→passes-yet-inflates).

See HANDOFF_SESSION_169.md for full detail.

(End of file)