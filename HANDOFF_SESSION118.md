# Handoff — Session 118: pin/criteria guard extended to runtime criteria

## What changed (this session)
- Extended `skills/quantitative-backtesting/tests/test_pin_criteria_consistency.py` to cover the runtime `assert passes["NAME"] is <bool>` / `assert criteria["NAME"] is <bool>` pattern used by walk-forward and CPCV tests (previously only the `expected_criteria` dict pattern was guarded).
  - New `_runtime_asserts()` collects these asserts via AST.
  - Added `oos_total_return_positive` (`total_oos_return > 0`) to `derive_criteria` and `KNOWN_CRITERIA`.
  - New self-test `test_guard_detects_injected_runtime_inconsistency`.
  - Fixed early-return: files pinning `expected_criteria` with inline metric assertions (no `EXPECTED` literal) are skipped, not failed.
- No production code changed. Working tree: one modified test file; nothing committed.

## What was actually verified (evidence)
- Standalone guard: 5/5 PASS, EXIT 0.
- Checkable benchmark-aware files: 21/33 (19 via `expected_criteria` dict, 2 via runtime pattern), 0 runtime criteria skipped.
- pytest on guard + donchian breakout benchmark-aware + walk-forward kelly + walk-forward dual momentum benchmark-aware triple + walk-forward rsi benchmark-aware pair: 13 passed, 21.18 s.
- Earlier focused suites: 35 passed (regime cost multiplier, adjustment integrity guard, deflated sharpe, BH FDR).

## What remains unresolved
- Full gate not re-run this session (in-session budget); session 117 reported EXIT 0, 1451 passed (~31 min with `-n 4`). Next step: run `pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` in CI / adequate-budget environment and require EXIT 0.
- No CI workflow for the quant gate.

## Approaches already tried / failed
- Full gate serial: timed out (~60 min). `-n 4` is the viable mode.
- Flipping criterion/verdict assertions to force EXIT 0: rejected (anti-tuning rule).

## One precise next task (for the next agent)
Run the full gate with `-n 4`, require EXIT 0, revert dirtied artifacts afterwards (`git checkout -- .`). Only then: per AGENTS.md mission, pick the next bounded methodological gap (PIT/survivorship-bias controls, or a new falsifiable hypothesis with OOS evidence net of costs). Do not commit unless asked.
