# Handoff: next task (session ending 2026-11-19): wire participation-rate cap through walk-forward

## Latest verified baseline
- **Full quant gate: 1535 passed, EXIT 0** in 1459.84s with `-n 4`
  (`/tmp/venv/bin/python -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`).
- 1535 = previous 1522 + 9 walk-forward capacity-cap tests + 4 run_backtest cap tests.
- `run_backtest.py --max-participation-rate` verified end-to-end by CLI smoke:
  capacity equals `rate * ADV_notional` exactly on the AAPL fixture.
- Working tree (uncommitted): `scripts/walk_forward.py` (estimate_capacity cap),
  `scripts/run_backtest.py` (flag + validation + config), both test files,
  `SKILL.md`, `references/cost_models.md`, this handoff set.

## What is complete
- `estimate_capacity(..., max_participation_rate=r)` caps the point estimate,
  the panel basket estimate (least-liquid constituent x n_assets), and every
  period of `capacity_trend`; rejects non-positive/non-finite values.
- `run_backtest.py` exposes `--max-participation-rate`, validates before the
  capacity `try/except`, and records `results["config"]["max_participation_rate"]`.
- Docs describe the `min(impact_capacity, r * ADV_notional)` semantics and the
  full-rebalance limitation.
- Default `None` leaves the impact-only numbers unchanged (tested).

## What remains unresolved
- `walk_forward.py` CLI paths (`walk-forward`, `optimize`, `cpcv`, `monte-carlo`,
  `out-of-sample`) still compute capacity without the cap. Their per-period and
  summary capacity numbers therefore use a different liquidity convention than
  `run_backtest`.
- No profitability/capacity claim. Committed-fixture verdicts remain `NOT SUPPORTED`.
- Uncommitted (do not commit unless the user asks).

## One precise next task
1. Add `--max-participation-rate` to `common_parser` in `scripts/walk_forward.py`
   (~line 12050), default `None`, validated once per subcommand.
2. Thread the value into `walk_forward_analysis`, `cpcv_analysis`,
   `out_of_sample_validation`, and the two Monte Carlo summary paths, and pass
   it to every `estimate_capacity` call:
   lines **1102** (per period), **1309** (WF summary), **4624** (per fold),
   **4832** (CPCV summary), **6973** / **7073** (OOS val/test), **7430** (OOS
   summary), **10631** and **11185** (Monte Carlo).
3. Record the value in each summary (same key name as run_backtest) and add a
   focused test that a cap tighter than the impact capacity binds in both
   `periods[i]["capacity"]` and `summary["capacity"]` (and in the trend).
4. Run focused capacity tests, then the full gate with `-n 4`; require EXIT 0
   (baseline **1535**). Revert only inspected generated artifacts.

## Constraints
- Default `None` must be bitwise identical to today's published numbers.
- Do not weaken the capacity `try/except` or CLI validation.
- Use `-n 4` with ~25 min budget.
- Do not `git checkout -- .` blindly; revert only inspected artifact paths.
- Do not commit unless explicitly asked.
