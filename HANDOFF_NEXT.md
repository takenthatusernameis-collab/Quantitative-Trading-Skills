# HANDOFF

## What changed this session

Removed the unused `target_years: float = 1.0` parameter from `performance.py:_annualization_factor`. No callers passed it; signature now matches `monte_carlo.py` and `walk_forward.py` copies. Tests pass (32/32).

## What was verified

- `test_performance.py`: 32/32 pass.
- grep confirmed no callers pass `target_years`.

## What remains unresolved

`_annualization_factor` is duplicated across three modules (`performance.py`, `monte_carlo.py`, `walk_forward.py`) with independent maps. They currently agree, but drift is possible. Consider consolidating into a single shared implementation in a future task, with tests guarding parity.

## Next task (precise, bounded)

Add a parity test asserting `_annualization_factor` returns identical values for the same index across all three modules (performance, monte_carlo, walk_forward) for a representative set of frequencies (B, D, h, min, ME, MS, QE-DEC). Place in `test_performance.py`, register in TEST_REGISTRY. Do not change production code unless a mismatch is found.

## Relevant files

- `skills/quantitative-backtesting/scripts/performance.py:20`
- `skills/quantitative-backtesting/scripts/monte_carlo.py:24`
- `skills/quantitative-backtesting/scripts/walk_forward.py:1503`
