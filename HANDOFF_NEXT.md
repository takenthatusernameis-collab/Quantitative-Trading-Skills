# Handoff — session 2026-10-28 (split-separation positive control verified)

## What changed
- Verified the positive-control test `test_verify_split_separation_rejects_overlap_and_non_chronological`
  already present in `skills/quantitative-backtesting/tests/test_out_of_sample_window.py`:
  overlapping train/val and non-chronological splits are rejected (strict raises ValueError;
  non-strict reports `disjoint is False` / `chronological is False`); clean split passes.
- No code changes this session; test suite green.

## What was actually verified
- `tests/test_out_of_sample_window.py` → 12/12 passed, including the positive control.
- `_verify_split_separation` implementation intact in `walk_forward.py`.

## What remains unresolved
- Independent real-market out-of-sample evidence. All verdicts remain on synthetic/local fixtures.
  `scripts/data_loader.py` reads local CSV/Parquet only; a Yahoo Finance probe returned HTTP 429.
  Resolving requires a bounded real-data fetch (single public OHLCV source, retries with backoff,
  honor 429) plus running falsifiable machinery on the real series, with a focused test asserting
  a determinate verdict and OOS split separation. If still rate-limited, record the exact HTTP
  status and preserve a reproducible next step (fetch URL, expected OHLCV schema, CLI invocation).

## One precise next task
- Add independent real-market out-of-sample evidence per the above. Relevant files:
  `skills/quantitative-backtesting/scripts/data_loader.py`,
  `skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`,
  `skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`.
