# HANDOFF_NEXT

## The one precise next task

Run the HEAD-vs-new parity harness and confirm **zero changed numbers with the default
`panel` aggregation**, in both `net-exposure` and `book` modes.

### Why this task

The notional-weighted impact convention is implemented and opt-in (default `panel`), and
the full test suite is green, but verification criterion (c) from the prior handoff was
defined against the dedicated parity harness (HEAD-vs-new diff), not the test suite.
Closing it confirms nothing moved under the default before any further methodological
work.

### Where the harness lives

`/home/runner/work/_temp/kilo-tmp/kilo/` contains `baseline_capture.py`,
`book_cap_probe.py`, `baseline_before.json` / `baseline_after.json` (the prior session's
captures against commit `65b8274`). Reuse those scripts rather than rebuilding them.

### What to do

1. Confirm the working tree is at this session's state (four modified files under
   `skills/quantitative-backtesting/`; last commit `65b8274`). `git status` should be
   clean except for those files and `HANDOFF.md` / `HANDOFF_NEXT.md`.
2. Capture this commit's outputs with `baseline_capture.py` for `run_backtest`,
   `walk_forward` and `cpcv` in both `net-exposure` and `book` modes, using the default
   `panel` aggregation.
3. Diff against the prior capture (`baseline_before.json`).
4. Expect: **zero changed numbers** — no return, cost, capacity, Sharpe or bar-count
   change. The only acceptable additions are `capacity_notional_weighted` /
   `capacity_notional_weighted_trend`, which must be `None` under the default.
5. Record the result (pass / which keys changed / evidence) on the board, then either
   (a) declare the opt-in convention complete and propose the next methodological item
   (`fill_rate` convention or the linear-impact caveat), or (b) if anything changed,
   investigate and fix before anything else.

### Constraints

- Do **not** change the default aggregation (`"panel"`).
- Do **not** re-quote the published book-mode return (-15.68 %) without re-running the
  parity harness.
- Do **not** use blind `replaceAll` across call sites that use different variable names
  (this session already fixed a `book_weights` cross-contamination caught by the test
  suite).

### Evidence already in the repo

- `tests/test_run_backtest.py`: `test_default_impact_aggregation_is_panel`,
  `test_notional_weighted_charges_the_notional_weighted_measurement`,
  `test_notional_weighted_capacity_is_the_dw2_inverse` (all pass, 103/103).
- Full suite: all test files exit 0.
