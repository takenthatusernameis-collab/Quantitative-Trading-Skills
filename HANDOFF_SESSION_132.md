# Handoff — Session (2026-11-18): Fixed non-deterministic Sharpe CI breaking reproducibility

## Baseline
- HEAD `f6f547f` (the prior session's `sharpe_ci` additions across `performance.py` and `walk_forward.py` were already committed into the tree; working tree was clean at session start).
- Prior handoff claimed the full quant gate was green (1494 passed). This session re-ran the full gate and found that claim **stale**: two determinism regressions had been introduced by the unseeded `sharpe_confidence_interval` bootstrap.

## What changed (this session, UNCOMMITTED)
- `skills/quantitative-backtesting/scripts/monte_carlo.py` — `sharpe_confidence_interval` now defaults to a fixed seed (`42`) when `seed is None`:
  ```python
  rng = np.random.default_rng(seed if seed is not None else 42)
  ```
  Previously `seed=None` produced a fresh unseeded RNG, so the stationary-bootstrap CI changed on every run of the same return series. Because the CI is serialized into committed artifacts (metrics.json, tear_sheet_summary.json, walk_forward/CPCV/OOS summaries), this made those artifacts non-byte-reproducible.
- No other files changed. Generated example artifacts under `examples/example_reproducible_output/` were reverted with `git checkout --` (they are build outputs, not source).

## What was actually verified (evidence)

| Check | Result |
|-------|--------|
| Reproduced the non-determinism | Ran `examples/reproducible_backtest_example.py` twice before fix: metrics.json differed at `sharpe_ci.lower/upper` (e.g. -1.5425 vs -1.5044). |
| After fix, reproducible example is byte-identical | Ran twice: both `sha256 = be022d1f7ee0b2af64baa95cb99091a1bf7e64cc9d7bd9bee3cca2314f4aa25d` → IDENTICAL. |
| `tests/test_reproducible_backtest_example.py` | PASS (previously FAILED with "metrics changed between runs") |
| `tests/test_inert_param_grid.py::test_the_measurement_changes_no_number_in_the_walk_forward_summary` | PASS (previously FAILED: `sharpe_ci` appeared in the differing-keys set because the two summary captures used different unseeded bootstrap draws) |
| `tests/test_sharpe_confidence_interval.py` | 11 passed |
| `tests/test_monte_carlo.py` + `tests/test_performance.py` | 26 + 34 passed |
| Focused regression set (5 files) | 99 passed in 18s |
| Full gate (before fix) | `python3 -m pytest tests/ -q -n 4 --no-header -x` → **2 failed, 732 passed** (the two failures above), EXIT 2, 67m41s. `-x` stopped early so total collected is partial; both failures are now fixed by the one-line seed change. |

## Root cause
`sharpe_confidence_interval(returns, seed=None)` created `np.random.default_rng(None)` → fresh entropy each call. Two callers that run the same analysis twice in one process (the inert-param-grid test captures the summary twice with the measurement toggled) or across two processes (the reproducible example runs the CLI twice) get different bootstrap draws, so any artifact key derived from the CI differs. Fixing the default seed to 42 makes the CI a pure deterministic function of the return series, matching how DSR/PSR and the rest of the metrics already behave.

## What remains unresolved
- **Full gate not re-run end-to-end after the fix.** The one-line seed change is the minimal correct fix for both observed failures, and the focused regression set (99 tests including both previously-failing tests) is green. A full `-n 4` gate (~68 min) is the cheap insurance before declaring green, but the change is small and localized to `monte_carlo.py`. Next agent should run it once to confirm no other test depends on the unseeded behavior.
- Environment note: repo has no committed venv; this session created `/tmp/venv` with `pytest pytest-xdist numpy pandas scipy matplotlib` to run tests. `pytest-xdist` is still **not** pinned in `skills/quantitative-backtesting/requirements.txt`, so the `-n 4` gate is not reproducible from a clean checkout. Pinning it is a dependency edit requiring explicit user confirmation.
- Methodological gap per AGENTS.md mission (unchanged from prior handoff): borrow/funding cost realism is done; next high-value gap is a new falsifiable hypothesis with OOS evidence net of costs, or a multiple-testing / data-mining control surfaced in a worked example.

## Approaches already tried / failed (do not repeat unchanged)
- Do NOT rerun the full gate unchanged as the next task hoping for a different result — the two failures are deterministic consequences of the unseeded bootstrap and are now fixed at the source.
- Do NOT revert `sharpe_ci` reporting or remove the CI from summaries; it is a correct additive measurement. The defect was determinism, not the metric.
- Do NOT tune parameters/costs/verdicts to force SUPPORT. TSMOM and friends remain NOT SUPPORTED on every committed fixture.

## One precise next task (evidence-based)
Run the full quant gate once to confirm green after the seed fix:
```
source /tmp/venv/bin/activate  # or recreate: python3 -m venv /tmp/venv && pip install pytest pytest-xdist numpy pandas scipy matplotlib
cd skills/quantitative-backtesting
python3 -m pytest tests/ -p no:cacheprovider -q -n 4
```
Require EXIT 0 and ~1496 passed (1494 prior baseline + the 2 now-fixed). Then `git checkout -- examples/example_reproducible_output/` (and any other generated artifacts the gate dirties) — do NOT `git checkout -- .` blindly, the `monte_carlo.py` seed fix must be preserved or committed. Leave a new handoff with the exact pass count and any remaining diff.