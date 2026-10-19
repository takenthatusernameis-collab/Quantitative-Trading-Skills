# HANDOFF_NEXT

## The one precise next task

Adapt the parity harness (`baseline_capture.py`) to the current guard behavior: run the symmetric cross-sectional variant under `--panel-pricing book` (or skip it in net-exposure mode), and capture net-exposure + book numbers for the asymmetric variant and single-asset SMA in both modes. Then diff against a fresh baseline to confirm zero changed numbers under default `panel` aggregation.

### Why

The harness as stored cannot run unchanged: the symmetric cross-sectional variant is market-neutral (flat net exposure), and `run_backtest` now correctly rejects it in net-exposure mode with a clear message. `baseline_before.json`/`baseline_after.json` are empty, so no prior capture exists to diff.

### Evidence

- `tests/test_run_backtest.py`: 103/103 pass.
- Full suite green per prior handoff.
- Guard message directs users to `--panel-pricing book` for flat-signal books.

### Constraints

- Do not change default aggregation (`panel`).
- Do not weaken the guard.
- Preserve symmetric variant only under book mode.
