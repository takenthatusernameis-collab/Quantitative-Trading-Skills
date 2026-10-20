# HANDOFF_NEXT

## Next task: focus on the falsifiable hypothesis example or extend thin-evidence gating

### Why
The `--min-position-fraction` gating added is working and tested. The canonical
partial case now fails as expected under a floor, passes by default, and the
artifact includes `summary.thin_evidence_failure`. All tests in the
quantitative-backtesting suite pass (34/34 in test_no_selection_diagnosis.py
including the new gating tests; all other 15 test files pass).

Another concrete, quant-focused task: the falsifiable hypothesis example
(`skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`)
tests all pass structurally, but the verdict is `NOT SUPPORTED` on shipped
sample data (criterion `deflated_alpha_ratio_gt_0.90` fails). Investigate
whether this is a sign of weak sample data, overly strict thresholds, or a
real signal. If we can make the criteria more principled or adjust the example
to be more illustrative without fabricating results, that would improve the
methodological example - but must follow the repo's rules: no hype, explicit
assumptions, falsification criteria, and evidence-based changes only.

Alternatively, consider extending the thin-evidence measurement to other paths
or adding more granular reporting. Pick one bounded, verifiable task.

### Evidence to inspect first
- `skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py`
- `skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py`
- `skills/quantitative-backtesting/scripts/performance.py` (deflated alpha logic)
- `skills/quantitative-backtesting/scripts/walk_forward.py` (how thin evidence is computed)

### Definition of done
- One concrete change improving quant methodology quality
- Tests updated/added and passing
- Evidence documented (what changed, verified, remains unresolved)
- No change to parity for unrelated behavior
