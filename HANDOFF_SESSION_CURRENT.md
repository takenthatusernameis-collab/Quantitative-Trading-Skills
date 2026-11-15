# Handoff — Current Session: TSMOM extended to MSFT and GOOGL; full gate green

## What changed (this session)
- **Added MSFT and GOOGL falsifiable TSMOM hypothesis tests** following the session-120 AAPL pattern:
  - `skills/quantitative-backtesting/tests/test_time_series_momentum_hypothesis_real_msft.py` (2 tests)
  - `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_real_msft.py` (2 tests)
  - `skills/quantitative-backtesting/tests/test_time_series_momentum_hypothesis_real_googl.py` (2 tests)
  - `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_real_googl.py` (2 tests)
- **Extended `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`**: `main()` now iterates over AAPL, MSFT, GOOGL instead of AAPL only.
- All changes use pre-registered falsification criteria (pinned before inspection): oos_sharpe > 0, oos_total_return > 0, deflated_sharpe_pvalue < 0.10 (net of 3 bps round-trip costs). Criteria are identical across symbols — only the observed metrics differ.
- No source code changes to strategy_builder.py or walk_forward.py. Working tree: 1 modified file + 4 new test files, nothing committed.

## Honest observed results (committed fixtures only, not profitability claims)
| Symbol | oos_sharpe | total_oos_return | deflated_sharpe_pvalue | n_trials | Verdict |
|--------|-----------|-----------------|----------------------|----------|---------|
| AAPL   | -0.3885   | -0.0598         | 0.9746               | 5        | NOT SUPPORTED |
| MSFT   | -0.4138   | -0.1018         | 0.9569               | 5        | NOT SUPPORTED |
| GOOGL  | -0.1162   | -0.0245         | 0.6223               | 4        | NOT SUPPORTED |

GOOGL reports 4 DSR trials (not 5) because one grid point yielded no tradeable positions — observed property of the fixture, not a tuning choice.

## What was actually verified (evidence)
| Check | Result |
|-------|--------|
| New MSFT/GOOGL TSMOM tests (8 tests) | 8 passed, ~1 s |
| Full quant gate | **1465 passed, 0 failed, EXIT 0** (32:28, `-n 4`) |
| compileall on quant-backtesting | clean |
| Environment | Python 3.14.4, numpy 2.5.4, pandas 3.1.1, scipy 1.18.1, pytest-xdist 3.8.0 |

## What remains unresolved
- Pre-existing 17 CPCV behavior-pin failures (documented in HANDOFF.md) — root cause identified (CPCV indicator-warmup convention change), not introduced by this session. Reconciliation pending per HANDOFF.md next task.
- No CI workflow exists for the quant gate; only reproducible locally.

## Approaches already tried / failed (do not repeat unchanged)
- Full gate serial: timed out (~60 min). `-n 4` completes in ~33 min; use that.
- Do not flip criterion/verdict assertions or fabricate results to force SUPPORT (honesty / anti-tuning rule). All three symbols honestly return NOT SUPPORTED.
- Blindly re-pinning CPCV expected values: REJECTED (weakens guards).

## Next task (precise, for the next agent)
1. Reconcile the 17 pre-existing CPCV behavior-pin failures with the warmup convention per HANDOFF.md (re-pin expected values in `test_no_selection_diagnosis.py` and `test_resolution_vs_sample_size.py` to freshly measured values; document the warmup convention in a comment).
2. Re-run full gate: `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` — require EXIT 0 (~1465+ passed). Revert generated artifacts with `git checkout -- .` after.
3. Then select the next bounded methodological gap per AGENTS.md mission (point-in-time/survivorship-bias controls, or a new falsifiable hypothesis with OOS evidence net of costs).
4. Do not commit unless explicitly asked.

(End of file)
