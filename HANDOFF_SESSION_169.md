# Handoff — PIT-violation sensitivity study on synthetic data (5/5 green)

## What changed (this session)
Executed the precise next task from `HANDOFF_SESSION_168.md` /
`HANDOFF_SESSION_CURRENT.md`: a controlled look-ahead (point-in-time)
sensitivity study on SYNTHETIC data. Added ONE new file only:
`skills/quantitative-backtesting/tests/test_pit_violation_sensitivity_synthetic.py`.
No engine, fixture, pinned-hash, or inherited-catalog changes. Working tree
before/after: only that new file is untracked; `git diff` (tracked) empty.
NOTHING committed (not asked).

The test builds a driftless random-walk OHLCV panel via the repo's own
`generate_control_series(periods=640, inject_effect=False, seed=7)` and runs a
CONTROLLED PAIR that differs by exactly one bar of look-ahead:
- clean:      `signal[t] = 1{close[t]   > close[t-1]}`  (close[t]-based)
- look-ahead: `signal[t] = 1{close[t+1] > close[t]}`    (= clean.shift(-1))
Engine fills at `signals.shift(1+latency)`, so the look-ahead earns `|ret[t]|`
every bar (perfect foresight) — the textbook inflation.

## What was actually verified (evidence)
- `python3 tests/test_pit_violation_sensitivity_synthetic.py` → 5/5 PASS, OK.
- `python3 -m pytest tests/test_pit_violation_sensitivity_synthetic.py -q`
  → 5 passed.
- Recorded headline delta (look-ahead minus clean, the abort prevents this):
  - oos_sharpe:       clean=-1.7044  look=+8.8361  delta=+10.5405
  - total_oos_return: clean=-0.2374  look=+2.6771  delta=+2.9145  (periods=7)
- Controls inside the test:
  - clean signal PASSES `validate_point_in_time` (no violations);
  - look-ahead is FLAGGED (corr=0.545 > threshold 0.300, text names threshold);
  - gate OFF (`validate_pit=False`): look-ahead inflates both headline metrics
    by more than the asserted margins (Δsharpe>2.0, Δtotal>1.0);
  - gate WARN-ONLY (`pit_strict=False`): look-ahead completes but is detected
    (passed=False) — proves the abort is caused by strict mode, not a crash;
  - gate STRICT (`pit_strict=True`): clean completes (pit passed=True),
    look-ahead ABORTS with ValueError.
- GENUINE-GUARD PROOF: temporarily set the `walk_forward_analysis` strict abort
  at `walk_forward.py:869` to `if False and ...` → the strict test FAILED with
  "strict PIT did not abort on the look-ahead signal"; restored `walk_forward.py`
  byte-for-byte (`git diff` empty, line 869 back to original).
- Regression sanity: existing `tests/test_point_in_time_strict_abort_on_violation.py`
  → 6 passed (pytest). No interference.

## Environment note (updates prior "pytest absent" guidance)
This session's container had NO numpy/pandas/scipy/pytest, but pip DOES have
network for packages. Installed successfully (Python 3.14):
`python3 -m pip install numpy pandas scipy pytest` (got numpy 2.5.5, pandas
3.1.1, scipy 1.18.1, pytest 9.2.0). After that, tests run via either
`python3 <file>` or `python3 -m pytest <file>`. The `timeout_method` pytest
warning is a pre-existing config issue (pytest-timeout not installed), harmless.

## What remains unresolved
- DATA PROVENANCE (pre-existing): committed `real_market_data` CSVs are
  synthetic/placeholder (per HANDOFF_SESSION_164.md). `test_real_market_data_provenance.py`
  only checks fixtures match the committed manifest — NOT real securities.
  Do NOT fabricate or edit pinned hashes. (pip network ≠ source-data network.)
- The full 330-file `skills/quantitative-backtesting/tests/` suite has NOT been
  swept end-to-end in one pass. Confirmed green so far: walk-forward family 253
  (session 167) + 15 non-walk-forward (session 168) + this new file (5). The
  remaining ~60 per-strategy real-data sensitivity files are unswept.

## Approaches that already failed (do not repeat)
- Do NOT re-attempt offline data-provenance restoration; do not fabricate data
  or edit pinned hashes.
- Do NOT re-debug `estimate_capacity` / regime forwarding — present & guarded.
- `background_process` runs in a separate FS namespace where the repo is NOT
  visible — run test sweeps foreground with per-file `timeout`.
- The PIT corr construction `(next_ret>0)` reliably exceeds the 0.3 threshold
  (corr≈0.55); a subtler look-ahead may fall below it (see next-task alternative).

## One precise next task (bounded, evidence-based)
Sweep the remaining ~60 per-strategy real-data files under
`skills/quantitative-backtesting/tests/` for regressions, now that the
environment is provisioned. Method: foreground, per-file
`timeout 120 python3 -m pytest <file> -q` (or `python3 <file>`), offline,
committed fixtures only. Record pass/fail counts; treat ANY "profitable"
output as a synthetic/placeholder-data artifact ONLY (the panel is contested),
never as evidence about real securities. Scope: run tests only; do NOT modify
engine/fixtures/hashes/catalog. Do NOT commit unless asked.

Alternative if the sweep is judged low-value: add a companion test
`test_pit_threshold_boundary_synthetic.py` that tunes a look-ahead's
signal/next-return correlation to just ABOVE and just BELOW the 0.3 threshold,
showing (a) above → strict abort + inflation prevented, (b) below → the gate
PASSES yet the signal still inflates — an honest statement of the
correlation-threshold detector's limitation. New file only; no engine changes.

(End of file)