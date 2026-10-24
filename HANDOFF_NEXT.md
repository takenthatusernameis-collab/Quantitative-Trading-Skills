# Handoff — data_loader inspection + trading_costs coverage strengthened (2026-10-23)

## What changed
- `skills/quantitative-backtesting/tests/test_examples_coverage.py`:
  - Strengthened `test_trading_costs_robustness_example_shows_cost_sensitivity` with numerical cost-reduction guards: the strategy cost-sweep impact block must show higher per-trade costs reduce net Sharpe (`sharpe_end < sharpe_start`) and net return (`ret_end < ret_start`). Previously the test only asserted string presence ("Sharpe", "0 bps", "Strategy transaction costs"); now it actually guards the cost-sensitivity property HANDOFF.md requested ("that higher cost reduces net return").
- Reverted unintended side-effect changes to `skills/quantitative-backtesting/scripts/results/*` (metrics.json, tear_sheet.html, report.txt, PNGs) that the full test suite regenerated as a side effect (sma_crossover→rsi_mean_reversion). Working tree now contains only the test_examples_coverage.py edit.

## What was actually verified
- `tests/test_examples_coverage.py -k trading_costs` → 3 passed.
- `tests/test_examples_coverage.py` (full file) → 37 passed.
- `tests/test_data_loader.py` → 32 passed (baseline green before/after).
- Empirically confirmed trading_costs example's cost-sensitivity claim: 0→15 bps cuts Sharpe -0.210→-0.298 and return -9.56%→-13.65%; CPCV OOS Sharpe 0.200→0.103 low→high cost.
- data_loader.py inspected against references/data_schema.md:
  - Date handling (parse/sort/dup-date failure), validation rules 1-7 (required cols, nulls warning-only non-strict, non-positive prices, high>=low>=open/close, low<=open/close, no dupes, no negative volume) all present and correct.
  - Split adjustment (`_adjust_for_splits`: divides pre-split by cumulative ratio, split-date return zero, volume scaled up) verified correct incl. multi-split accumulation.
  - `validate_point_in_time`: true look-ahead (`signal[t]=close[t+1]>close[t]`) flagged (corr=0.543); legitimate close[t]-based momentum/mean-reversion/SMA signals pass.
  - `detect_survivorship_bias`: entries/exits/insufficient/large-gap (63-day gap detected) all detected correctly.
- Full suite `tests/` was green (775 passed) prior to reverting artifact side-effects.

## What remains unresolved
- No code defect found in data_loader.py point-in-time / survivorship / look-ahead controls; nothing to fix there (controls verified correct). Constraint honored: validation not weakened.
- HANDOFF.md trading_costs coverage task is now fully satisfied (coverage existed; numerical assertion added).

## Approaches already tried
- Grep/read of data_loader.py + data_schema.md + test_data_loader.py (all pass).
- Empirical probes of validate_point_in_time (look-ahead + legitimate signals) and detect_survivorship_bias (large internal gap) — both behave correctly; no defect to fix.

## One precise next task
Prevent the test suite from mutating tracked `scripts/results/` artifacts (reproducibility / byte-stability regression). Running the full `tests/` suite regenerated tracked outputs (metrics.json, tear_sheet.html, report.txt, PNGs) as a side effect. Identify the culprit test/example, redirect its output to a temp dir, and add a regression test asserting `git status --porcelain skills/quantitative-backtesting/scripts/results/` is clean after the suite. Relevant files: `skills/quantitative-backtesting/scripts/results/*`, tests that run `real_data_pipeline_example.py`/`full_pipeline_example.py`/hypothesis examples. Do not commit unless asked.
