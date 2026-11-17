# Handoff — Session 131 (2026-11-17): adjustment-provenance task verified; fixture defect fixed

## Baseline
- Branch `main`, up to date with `origin/main`. HEAD at session start: `6d29a31` (empty-message commit; not counted as progress).
- Working tree was clean at session start. No commits this session (commit not requested).

## What changed (bounded, verifiable)
- **No new code was written.** The task assigned by `HANDOFF_SESSION_130.md` was already implemented in the tree: `skills/quantitative-backtesting/tests/test_split_adjustment_provenance_cli.py` and `test_adjustment_integrity_cli_regression.py` both exist and cover the positive/negative controls end-to-end.
- **Fixed one stale fixture bug** in `skills/quantitative-backtesting/tests/test_split_adjustment_provenance_cli.py:36-44`: the clean-panel positive control built `adj_close = c/4.0` for AAA's pre-split rows, but `adjustment_integrity_guard` runs on the *original* data before split adjustment and expects `adj_close[t] == close[t] / cum_split_after[t]`, i.e. `c/2.0` pre-split (cum_split_after=2.0) and `c` on/after. The old value was off by a factor of 2, so the positive control failed deterministically (`n_mismatch: 30`, `max_relative_deviation: 0.5`). Changed `c/4.0` -> `c/2.0` and rewrote the inline comment to state the guard's actual convention.

## Why this gap (evidence-based)
- The prior handoff asked for an end-to-end CLI regression proving `adjustment_integrity_guard` and per-symbol split-adjustment provenance survive into `tear_sheet_summary.json`. Two such tests existed; running them exposed that one of them was a *broken* positive control that would have failed on every clean run, silently undermining the very invariant it claimed to guard. Fixing it is the smallest change that makes the guard's end-to-end evidence trustworthy.

## What was actually verified (evidence)
| Check | Result |
|-------|--------|
| Focused adjustment tests | `pytest tests/test_split_adjustment_provenance_cli.py tests/test_adjustment_integrity_cli_regression.py -q` -> **4 passed in 5.49s** (was 1 failed / 3 passed before the fix) |
| Full quant gate, run to completion | `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` -> **1491 passed, 0 failed, 518 warnings, EXIT 0** in **1973.36 s (32:53)** (baseline 1486; +5 from the two adjustment CLI tests) |
| Working tree after gate | Only `test_split_adjustment_provenance_cli.py` modified; no gate-dirtied generated artifacts to revert |

## Unresolved / constraints
- No profitability/capacity claim. The committed cross-sectional momentum verdicts remain NOT SUPPORTED; this change touches test fixtures only.
- `pytest-xdist` still not pinned in `skills/quantitative-backtesting/requirements.txt`; the `-n 4` full gate is not reproducible from a clean env. Dependency edit requires explicit user confirmation.
- Broader universe/corporate-action completeness and genuinely independent OOS data remain unresolved.

## Approaches already tried / failed
- The positive control failed deterministically because its fixture contradicted the guard's documented convention (`adj_close == close / cum_split_after` on the *original* frame). The fix is the fixture value, not a guard change; the guard was left untouched. Do not "fix" the test by weakening the guard or by loosening the assertion.
- Do not rerun the full gate unchanged as a blocking in-session command (~33 min at `-n 4`); use background + poll, or defer to CI.

## One precise next task (evidence-based)
Pick the next bounded methodological gap per the AGENTS.md quant mission. Candidate directions already evidenced in the tree:
1. **Point-in-time / survivorship-bias controls** on committed fixtures (e.g. extend `test_multi_symbol_pit_survivorship_real_panel.py` or add a genuinely out-of-sample falsification net of plausible costs).
2. **Realistic commissions/spreads/slippage** sensitivity on a long/short path where borrow is not inert.
Do NOT add another strategy falsification test, do NOT claim profitability or capacity, and do NOT tune parameters/costs/verdicts to force SUPPORT.

Constraints: offline committed fixtures only; preserve marketplace compatibility; do not `git checkout -- .` blindly; do not commit unless explicitly asked.

(End of file - total 55 lines)