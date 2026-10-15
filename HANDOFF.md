# HANDOFF

## Session 2026-10-15 — Borrow/funding cost sweeps (COMPLETED)

### What was done

Added `--borrow-costs` and `--funding-costs` sweeps to the `monte-carlo` and `cpcv` CLI paths, mirroring the `--impact-coefficients` sweep from the prior handoff. The single-float args (`--borrow-cost`, `--funding-cost` on `common_parser`) already existed and were threaded to all `run_*` entry points, but none of them varied them. Now a user can pass multiple costs (e.g. `--borrow-costs 0 0.03 0.10`) and the pipeline (parameter selection, cost backtest, Deflated Sharpe correction, Monte Carlo / CPCV) runs once per cost, capturing borrow/funding sensitivity in a single artifact.

**Implementation (`skills/quantitative-backtesting/scripts/walk_forward.py`):**
- `--borrow-costs` / `--funding-costs` (nargs="+", type=float) added to `mc_parser` and `cpcv_parser` only — single-cost behavior is 100% untouched.
- Sweep helpers `_monte_carlo_sweep_coefficient` / `_cpcv_sweep_coefficient` generalized to accept `borrow_cost` / `funding_cost` kwargs (defaulting to `args.borrow_cost` / `args.funding_cost` when `None`), so the same helper serves the impact, borrow, and funding sweeps. The returned per-coefficient row now also carries `borrow_cost` and `funding_cost` fields.
- `_borrow_sweep` / `_funding_sweep` branches in `run_monte_carlo` and `run_cpcv`: when the corresponding list has >1 values, run the sweep, write `monte_carlo_borrow_sweep.json` / `monte_carlo_funding_sweep.json` / `cpcv_borrow_sweep.json` / `cpcv_funding_sweep.json` (costs + per-cost results), print a degradation table, and return 0 before the single-run path. Single cost → original code path, byte-for-byte behavior preserved.

**Verification:**
- Full suite: **233 passed** (229 baseline + 4 new tests).
- CLI sweep end-to-end on real sample data: monte-carlo borrow sweep writes `monte_carlo_borrow_sweep.json` with coefficients `[0.0, 0.03, 0.1]`; probability of ruin degrades 5% → 7% → 14% as borrow cost rises.

**Files changed (2):**
- `skills/quantitative-backtesting/scripts/walk_forward.py` — sweep args + generalized helpers + sweep branches (~150 lines added).
- `skills/quantitative-backtesting/tests/test_walk_forward.py` — `test_cli_monte_carlo_borrow_sweep`, `test_cli_cpcv_borrow_sweep`, `test_cli_monte_carlo_funding_sweep`, `test_cli_cpcv_funding_sweep`.

### Prior handoff status
- Market-impact cost root-cause fix: **complete** (prior session, 227 tests).
- Multiple-testing/Deflated Alpha benchmark correction: **complete** (prior session).
- Market-neutral borrow + funding demonstration: **complete** in baseline.
- Market-impact sweeps in monte-carlo/cpcv: **complete** (this session's predecessor).
- Borrow/funding sweeps in monte-carlo/cpcv: **complete** (this session).

### What remains unresolved
Nice-to-have extensions, not defects:
1. **Real-data cost sweep example** — needs network/data; defer.
2. **README mentions market-neutral variant** — done.
3. **Walk-forward (`walk-forward` subcommand) sweep variants** — the `--impact-coefficients` / `--borrow-costs` / `--funding-costs` list flags exist only on `monte-carlo` and `cpcv` parsers. The `walk-forward`, `optimize`, and `out-of-sample` subparsers still take only the single-float forms. Mirroring the sweep onto those paths is mechanical (the helpers already accept the cost kwargs) but was out of scope for this bounded task.

### Next task (suggested)
None outstanding from the handoff chain. If a new task is desired, the natural continuation is the walk-forward/optimize/out-of-sample sweep variants listed above, or a real-data cost-sensitivity demonstration. Both are bounded and reuse the machinery already in place.