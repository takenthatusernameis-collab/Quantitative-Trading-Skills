# Handoff — next task

## What changed (this session)
Completed the prior handoff's next task: added benchmark-aware (alpha p-value + Deflated Sharpe multiple-testing correction) falsification test + pinned regression guard for RSI mean reversion on the committed triple panel (AAPL/MSFT/GOOGL). See HANDOFF.md for details. New test: 2 passed, verdict NOT SUPPORTED (honest, not tuned). No regressions across existing RSI / strategy_builder / run_backtest tests.

## One precise next task
Run the full quant-backtesting test suite (`pytest skills/quantitative-backtesting/tests/`) to confirm no regressions from the shared `strategy_builder.py` panel change. If green and the user asks, commit the three changed/new files:
- `skills/quantitative-backtesting/scripts/strategy_builder.py` (RSI panel support)
- `skills/quantitative-backtesting/examples/rsi_mean_reversion_hypothesis.py` (benchmark-aware machinery)
- `skills/quantitative-backtesting/tests/test_rsi_benchmark_aware_real_triple_aapl_msft_googl.py` (pinned regression guard)

Evidence/constraints:
- Offline, committed fixtures only; MSFT as buy-and-hold benchmark; relative tolerance only; no tuning to force SUPPORT.
- Env: system python3.12, pandas 3.1.0, numpy 2.5.4, pytest 9.2.0 (+matplotlib); `export PATH=/home/runner/work/_temp/kilo-home/.local/bin:$PATH`
- Relevant files: `skills/quantitative-backtesting/tests/test_rsi_benchmark_aware_real_triple_aapl_msft_googl.py`, `skills/quantitative-backtesting/examples/rsi_mean_reversion_hypothesis.py`, `skills/quantitative-backtesting/scripts/strategy_builder.py`
