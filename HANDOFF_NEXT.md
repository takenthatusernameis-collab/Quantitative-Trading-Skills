# Handoff: next task (session ending 2026-11-15)

## State of baseline
- Working tree has **one uncommitted modification**:
  `skills/quantitative-backtesting/tests/test_pin_criteria_consistency.py`
  (guard extended to the runtime `passes`/`criteria` assert pattern; +186/-27 lines).
  Nothing committed this session (per instruction: do not commit unless asked).
- Committed baseline at HEAD `ce728d2` includes the regenerate_pins.py fixes, full pin rebase, the regime-cost-multiplier feature (8497210), and the original pin/criteria consistency guard (session 117).
- Session 117 evidence: full gate `pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` -> 1451 passed, 0 failed, EXIT 0 (~31 min 23 s). Not re-run this session.

## One precise next task
Run the full gate in CI / an adequate-budget environment and require EXIT 0:

```bash
python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4
```

Constraints and evidence:
- Use `-n 4` (~31 min); serial full gate timed out (~60 min) — do not repeat serial unchanged.
- The gate dirties `examples/example_output/*` and `scripts/results/*`; revert with `git checkout -- .` after any run.
- Expect EXIT 0 modulo nothing (session 117: 0 failures). If failures appear, inspect before acting; do not flip criterion/verdict assertions to force green (honesty / anti-tuning rule).
- Do not commit unless explicitly asked.

## After the gate is green
Per the AGENTS.md mission, select the next bounded methodological gap: point-in-time / survivorship-bias controls, or a new falsifiable hypothesis with out-of-sample evidence net of costs. Do not expand generic catalog tooling or re-organize inherited marketplace assets.
