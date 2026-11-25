# Next Session Task — Protocol-sensitivity walk-forward regression coverage

## Task
Run regression coverage of the protocol-sensitivity walk-forward family directly
with `python3`, confirming no regressions from accumulated additive tests.

## Target files (protocol-sensitivity only, triple panel / summary, offline
committed fixtures, direct `python3`, no commits):
1. `test_walk_forward_sma_crossover_protocol_sensitivity_real_triple_aapl_msft_googl.py`
2. `test_walk_forward_sma_crossover_protocol_sensitivity_real_triple_summary.py`
3. `test_walk_forward_cross_sectional_momentum_protocol_sensitivity_real_triple.py`
4. `test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py`
5. `test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple_summary.py`
6. `test_walk_forward_dual_momentum_protocol_sensitivity_real_triple_aapl_msft_googl.py`
7. `test_walk_forward_rsi_mean_reversion_protocol_sensitivity_real_triple_aapl_msft_googl.py`
8. `test_walk_forward_rsi_mean_reversion_protocol_sensitivity_real_triple_summary.py`
9. `test_walk_forward_ema_crossover_protocol_sensitivity_real_aapl.py`
10. `test_walk_forward_bollinger_protocol_sensitivity_real_aapl.py`
11. `test_walk_forward_donchian_protocol_sensitivity_real_aapl.py`
12. `test_walk_forward_macd_protocol_sensitivity_real_aapl.py`
13. `test_walk_forward_kelly_criterion_protocol_sensitivity_real_aapl.py`
14. `test_walk_forward_volatility_targeting_protocol_sensitivity_real_aapl.py`
15. `test_walk_forward_volatility_targeting_protocol_sensitivity_real_googl.py`
16. `test_walk_forward_volatility_targeting_protocol_sensitivity_real_msft.py`
17. `test_walk_forward_volatility_targeting_protocol_sensitivity_real_triple_summary.py`
18. `test_walk_forward_zscore_mean_reversion_protocol_sensitivity_real_triple_summary.py`
19. `test_walk_forward_zscore_multi_pair_protocol_sensitivity_real_triple.py`

## Success criteria
- Each runs to completion with `python3 <file>` and exit code 0.
- No cell flips to SUPPORTED (all committed verdicts remain NOT SUPPORTED).
- PIT validation passes; no flat-signal warnings.
- If any file is slow, bound the run per-file; leave passing direct-`python3`
  evidence.
- Do not commit unless explicitly asked.

## Context
- HEAD `8002b6a`; working tree clean.
- Base walk-forward family (4 tests) just verified green with NOT SUPPORTED
  verdicts.
- Quant gate baseline green at SESSION_159 (1782 tests) plus additive test
  files since, all individually verified green.
- `pytest` unavailable on PATH; verify via direct `python3` only.