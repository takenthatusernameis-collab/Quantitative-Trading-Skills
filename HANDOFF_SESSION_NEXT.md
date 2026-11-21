# Handoff — Next Task: Verify TSMOM borrow/funding cost realism does not flip the NOT SUPPORTED verdict

## What changed / was verified this session

- **CPCV partial-selection diagnosis contract (assigned task, HANDOFF_SESSION_150.md / HANDOFF_SESSION_NEXT.md): verified.**
  - Confirmed `test_cpcv_kelly_criterion_real_aapl.py:120-123`, `test_cpcv_volatility_targeting_real_aapl.py:117-120`, and `test_cpcv_dual_momentum_real_aapl_googl_structure.py:134-137` all assert `summary["no_selection_diagnosis"] is None` and `partial_selection_diagnosis["cause"] == "no_position_in_validation_window"`.
  - Ran the three files: `python3 -m pytest <the three files> -p no:cacheprovider -q` → **6 passed, 0 failed** (14 s), offline, committed fixtures only.

- **Cost-realism audit (session-149 open item): executed and recorded.**
  - Ran `test_walk_forward_time_series_momentum_cost_sensitivity_real_triple_aapl_msft_googl.py` → **1 passed** (6.7 s).
  - Sweep output (triple panel AAPL/MSFT/GOOGL, time-series momentum, walk-forward):
    - 0bp+0bp: Sharpe -0.1082, Return -0.1333, NOT SUPPORTED (all 3 criteria fail)
    - 1bp+0bp: Sharpe -0.1135, Return -0.1369, NOT SUPPORTED
    - 2bp+1bp (advertised): Sharpe -0.1241, Return -0.1443, NOT SUPPORTED
    - 5bp+2.5bp: Sharpe -0.1479, Return -0.1606, NOT SUPPORTED
    - 10bp+5bp: Sharpe -0.1877, Return -0.1871, NOT SUPPORTED
  - Conclusion: hypothesis is NOT SUPPORTED even frictionless; higher costs only degrade net performance; directional claim holds. **No profitability claim.** (time_series_momentum_hypothesis.py:68-74, :223-278)

- **Already in tree, no work needed:** `--max-participation-rate` CLI arg (walk_forward.py:12222) is threaded through `walk_forward_analysis`/`cpcv_analysis`/`out_of_sample_validation`/`estimate_capacity`, recorded in summaries, and validated (walk_forward.py:628, 4168, 6635, 3646). Borrow/funding cost-sweep tests already exist for the TSMOM triple panel.

## What remains unresolved

- Nothing blocking; full suite is green (session 150: 1546 passed, 0 failed). Working tree clean.

## Approaches already tried / failed (this session)

- None; both verification runs passed on the first attempt.

## One precise next task

Verify borrow/funding cost realism on the TSMOM triple panel and report whether it changes the NOT SUPPORTED verdict:

Run the two committed-fixture tests offline from repo root:
- `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_borrow_funding_cost_sweep_real_triple_aapl_msft_googl.py`
- `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_borrow_cost_realism_short_capable_real_triple_aapl_msft_googl.py`

Report the net numbers per borrow/funding level (Sharpe, total return, DSR p-value, verdict) and state explicitly whether the verdict flips from NOT SUPPORTED. Note the module caveat (time_series_momentum_hypothesis.py:90-99): long/flat TSMOM never shorts so borrow is inert for it; funding applies to gross exposure above 1x and can bite on the triple panel where several assets can be long concurrently. This is a sensitivity analysis, not a profitability claim — do not tune to force SUPPORT.

Constraints: offline/committed fixtures only (`assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv`); do not widen scope into unrelated files; require focused-test EXIT 0; do not commit unless explicitly asked.
