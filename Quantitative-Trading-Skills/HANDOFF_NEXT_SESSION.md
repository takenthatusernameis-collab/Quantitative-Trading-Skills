# Handoff — session 2026-10-28

## What changed
- Added `test_falsifiable_machinery_on_independent_real_market_data` to
  `skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`
  and registered it in TEST_REGISTRY (now 20 entries). It runs the example's
  `run_hypothesis_test` machinery (chronological 0.6/0.2/0.2 train/val/test,
  point-in-time validation, walk-forward selection, Deflated Sharpe +
  Deflated Alpha criteria, test-resolution block) on committed real market
  data `assets/example_data/real_market_data/sample_ohlcv.csv` (AAPL
  universe) with benchmarks `sample_ohlcv.csv` + `sample_benchmark.csv`
  (N=2). Labelled real-market evidence, not synthetic; the verdict
  (SUPPORTED / NOT SUPPORTED) is NOT asserted — both are valid scientific
  outcomes.
- Fixed a pre-existing, unrelated regression-guard defect in the same file:
  `test_the_example_records_its_methodology_block` asserted a stale
  `param_grid` (`fast_period [5,10,15,20]`, `slow_period [20,30,40,50]`)
  that did not match the example's actual `PARAM_GRID`
  (`fast_period [10,20]`, `slow_period [30,40]` at
  `examples/falsifiable_hypothesis_example.py:124`). Aligned the assertion
  with the example source of truth.

## What was actually verified
- New real-market test → PASS. Full suite → 20/20 passed, exit 0.
- Real-market run on the committed data: VERDICT = NOT SUPPORTED (a valid,
  falsified scientific outcome — not a profitability claim). Criteria 1
  (OOS Sharpe > 0) and 4 (OOS total return > benchmark) pass; criteria 2
  (deflated Sharpe p<0.10, p=0.223), 3 (raw alpha p<0.05, p=0.114), and 5
  (DAR > 0.90, DAR=0.816) fail once selection-bias and multiple-testing
  corrections are applied. OOS split clean (disjoint/chronological, 0
  overlaps; train 1509/val 503/test 503); point-in-time validation passed;
  bias controls engaged; 503 test observations; N=2 benchmarks.
- `test_the_example_records_its_methodology_block` → PASS after the fix
  (it failed on the unmodified baseline).

## What remains unresolved
- Independent real-market evidence beyond these committed fixtures. The
  bounded real-data fetch in `scripts/data_loader.py` (single public OHLCV
  source, bounded retries with backoff, honor 429) was NOT added: a direct
  probe to Yahoo Finance returned HTTP 429 (rate-limited), so the
  network-fetch approach is blocked for this session. Reproducible next
  step: fetch URL/schema + CLI invocation for `data_loader.py`, then run the
  falsifiable machinery on a fresh real series and add a focused real-market
  test. Relevant files:
  `skills/quantitative-backtesting/scripts/data_loader.py`,
  `skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`,
  `skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`.
- Full suite is slow (each `run_hypothesis_test` prints resolution-curve
  sections); pre-existing, not introduced this session.

## Approaches already tried / failed
- Real-data fetch probe: `curl -sI https://query1.finance.yahoo.com` → HTTP 429
  (rate limited). Abandoned fetch-in-`data_loader.py` for this session; used
  the committed local real-market CSVs instead (materially different,
  evidence-based approach).

## One precise next task
- Extend real-market out-of-sample coverage: either implement the bounded
  real-data fetch in `scripts/data_loader.py` honoring 429/backoff (no blind
  retries) and run the machinery on a fresh real series, or add focused
  real-market tests on the other committed equities (GOOGL/MSFT) and/or a
  multi-asset panel. Label results clearly as real-market evidence (not
  synthetic, not a profitability claim); record the exact fetch URL, expected
  OHLCV schema, and CLI invocation as a reproducible next step if the network
  remains rate-limited. Do not commit unless explicitly asked.
  Relevant files: `skills/quantitative-backtesting/scripts/data_loader.py`,
  `skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`,
  `skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`.

(End of file)
