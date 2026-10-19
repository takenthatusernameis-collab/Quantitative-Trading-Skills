# HANDOFF_NEXT

## The one precise next task

Decide — deliberately, with the number change accepted — whether the **second
warmup bar** of every priced window should be dropped, and make the warmup
convention explicit in the code rather than an emergent property of the cost
term.

### Why

`scripts/walk_forward.py:1709` builds the position series as
`positions = signals.shift(1 + latency) * fill_rate`, so `positions[0]` is
`NaN` (the lag-1 execution warmup). The cost term at
`scripts/walk_forward.py:1769-1770` is
`costs = positions.diff().abs() * (commission + slippage)`, and
`positions.diff()` inherits that `NaN` on the **second** bar as well
(`positions[1] - positions[0]`), so `NaN * 0.0 = NaN` and every window loses
its first **two** bars rather than one.

The second bar is a flat-position bar (the strategy's signal is still warming
up), so its return is `0.0`. Measured consequences:

- the compounded OOS return is **unaffected** (the dropped bar multiplies the
  product by `1.0`) — re-running CPCV with
  `position_changes.fillna(0.0) * (commission + slippage)` gives the same
  total (`0.005399536978800024`) but 24 usable bars per fold instead of 23
  (96 OOS bars instead of 92);
- the **training** sample used to select parameters loses one observation,
  and fold 0's selection is a close call (training Sharpes 2.681 / 2.747 /
  2.738 for lookback 15 / 20 / 30 — a 0.34% margin between the best and the
  runner-up), so a change here can flip the selected parameter in that fold
  and move the OOS result materially.

The convention is now **documented** and **pinned** (this session), not
changed: `references/validation_methods.md` -> "The Warmup Bars of a Window",
and the invariants `CPCV_OOS_BAR_COUNT` / `WALK_FORWARD_OOS_BAR_COUNT` /
`test_cpcv_pinned_number_is_reproducible_from_first_principles`.

### Evidence

- `scripts/walk_forward.py:1709` (the lag) and `scripts/walk_forward.py:1769-1770`
  (the cost term) — the two lines whose interaction drops the bar.
- `tests/test_cpcv.py` -> `CPCV_OOS_BAR_COUNT = 92` with the comment
  "23 usable bars" per 25-bar test window; `_independent_cpcv_oos_return`
  re-derives the same two-bar drop independently.
- Negative test (reverted, `git diff scripts/` is clean): changing
  `costs = position_changes * (commission + slippage)` to
  `costs = position_changes.fillna(0.0) * (commission + slippage)` makes
  `cpcv_normal_run_keeps_current_numbers` and
  `cpcv_pinned_number_is_reproducible_from_first_principles` fail on the
  usable-bar count (23 -> 24 per fold) while the compounded return stays
  identical.
- The same perturbation on the execution lag
  (`shift(1 + latency)` -> `shift(2 + latency)`) fails all three CPCV
  guards, including the value guard.

### Constraints

- This is a **number-changing** decision. If the second bar is kept, the
  pinned values (`CPCV_OOS_RETURN_REFERENCE`,
  `WALK_FORWARD_OOS_RETURN_REFERENCE`), the usable-bar counts
  (`CPCV_OOS_BAR_COUNT`, `WALK_FORWARD_OOS_BAR_COUNT`), the
  `test_output/` snapshot and the walk-forward numbers must be re-derived and
  re-pinned **in the same commit**, and reported as a methodology change with
  the before/after numbers — not as a bug fix.
- If the convention is kept as-is, make it explicit in the code (a named
  constant, or an explicit drop of the undefined warmup bars on the position
  series) so the two-bar drop is intentional rather than emergent from NaN
  propagation through a zero cost.
- Do not weaken the new guards to accommodate the change: the
  first-principles reproduction test and the structural bar-count pins are
  what make the pinned number meaningful.

### Verification

Re-run the whole suite (all 11 files must exit 0; `test_cpcv` is 29/29 and
`test_walk_forward` 177/177 today) and re-derive the pinned values with
`tests/test_cpcv.py` -> `_independent_cpcv_oos_return` before re-pinning.
