# Handoff — Session 120: standalone Time-Series Momentum (TSMOM) hypothesis

## What changed (this session)
- **Registered standalone TSMOM strategy** in `skills/quantitative-backtesting/scripts/strategy_builder.py`:
  - Exposed existing `TimeSeriesMomentumStrategy` (class at ~line 902) via `STRATEGY_REGISTRY` as `time_series_momentum`, and added it to `list_strategies()` and `get_strategy_defaults()` (`lookback=252`, `allow_short=False`). Previously TSMOM logic existed only as an internal base inside `VolatilityTargeting`/`KellyCriterion` and was not buildable by name.
- **Added falsifiable hypothesis example** `skills/quantitative-backtesting/examples/time_series_momentum_hypothesis.py`:
  - Walk-forward evaluation on committed AAPL fixture, train 24 / test 12 / step 12 months, pre-registered grid `{"lookback":[126,189,252]}` (N=3 trials), 3 bps round-trip costs, PIT validation engaged.
  - Criteria pinned before inspection: `oos_sharpe_gt_zero`, `oos_total_return_positive`, `deflated_sharpe_pvalue_lt_0.10` (DSR multiple-testing corrected).
  - Honest verdict on committed fixture: **NOT SUPPORTED** (all 3 criteria fail).
- **Added regression/pin tests**:
  - `skills/quantitative-backtesting/tests/test_time_series_momentum_hypothesis_real_aapl.py` — runs hypothesis, asserts verdict/criteria structure and pins observed metrics (NOT SUPPORTED).
  - `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_real_aapl.py` — direct walk-forward run with pinned summary/DSR metrics and criteria.

Design notes (pre-registered, not tuned): 252d lookback requires windows long enough for the signal to be defined; 24m-train/12m-test yields 3 periods with positions (a 12m-test window leaves 252d undefined for the whole window — verified during probing). Walk-forward chosen to provide genuine chronological OOS/deflation context on the committed panel.

## What was actually verified (evidence)
| Check | Result |
|-------|--------|
| Strategy registration smoke | `build_strategy('time_series_momentum','{"lookback":252}')` on AAPL: signals {1.0:1080, 0.0:427} |
| CLI probe (single backtest) | `run_backtest.py --strategy time_series_momentum ... --run-split test --validate-point-in-time` on AAPL (lb=252, 3bp): EXIT 0, PIT passed, Sharpe 0.2669, total return 0.0410 vs benchmark 0.1778, DSR p=0.384 (1 trial) |
| Walk-forward probe (pinned config) | train24/test12/step12, grid [126,189,252]: n_periods=3, periods_with_position=3, oos_sharpe=-0.38851059506816554, total_oos_return=-0.05984304746520375, DSR p=0.9745512685295135 (n_trials=5), bias_controls_engaged True, PIT passed |
| Focused tests (this change) | `pytest skills/quantitative-backtesting/tests/test_time_series_momentum_hypothesis_real_aapl.py skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_real_aapl.py skills/quantitative-backtesting/tests/test_pin_criteria_consistency.py -q` -> **9 passed** (0.87s) |
| Environment | Python 3.14.4, pandas/numpy/scipy per repo baseline; offline committed fixtures only |

Pinned honest outcome (committed AAPL, 3bp round-trip, net of costs): OOS Sharpe negative, total return negative, DSR p-value far above 0.10 -> **HYPOTHESIS NOT SUPPORTED** (all 3 criteria fail). Not a profitability claim.

## What remains unresolved
- **Full gate not re-run this session** (time/cost). Last known green: session 119 `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` -> 1453 passed, EXIT 0 (32:19). Expected after this change: 1453 + 4 new tests = **1457 passed** (verify).
- `pytest-xdist` may be missing in fresh containers; install `pip install pytest-xdist` first. Serial gate times out (~60 min); use `-n 4`. Gate dirties `examples/example_output/*`, `scripts/results/*` — revert with `git checkout -- .` after run.
- No CI workflow for the quant gate.

## Approaches already tried / failed (do not repeat unchanged)
- Walk-forward with `train=12/test=12/step=12` and `lookback=252` produced `periods_with_position=0` / `no_selection_diagnosis` because the 252d signal is undefined for the whole 12m window; resolved by using `train=24/test=12/step=12` (pre-registered, evidence-based), not by tuning to force SUPPORT.
- Serial full gate times out; chunked/serial retries without `-n 4` are not a viable substitute for the full gate.

## One precise next task (for the next agent)
1. Run the full gate and confirm green with the new TSMOM tests included:
   ```bash
   python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4
   ```
   Require EXIT 0 (~32 min). Revert dirtied artifacts with `git checkout -- .` after. If xdist missing, `pip install pytest-xdist`.
2. If green, select the next bounded methodological gap per AGENTS.md mission (e.g. extend TSMOM evidence to the other committed real fixtures MSFT/GOOGL or the multi-asset panel via walk-forward/book pricing with pinned criteria, or another demonstrable PIT/survivorship/cost/robustness control). Do not flip criteria/verdicts to force SUPPORT (anti-tuning). Do not commit unless explicitly asked.
