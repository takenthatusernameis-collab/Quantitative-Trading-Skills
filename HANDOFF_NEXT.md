# Handoff — Session 153: capacity cost-drag (borrow/funding) completed & tested

## What changed

The assigned task from `HANDOFF_NEXT.md` — "extend `estimate_capacity` with
borrow/funding costs" — was **already implemented and committed** in `fa2b537`
(the `estimate_capacity` signature, CLI flags, and threading through
walk_forward/cpcv/oos/mc paths were all in place). This session:

1. **Fixed two gaps** where `leverage`/`short_exposure` were *not* threaded
   into `estimate_capacity` summary calls (the per-period/per-fold/per-split
   calls already passed them, but the whole-sample summary calls used
   defaults, producing an inconsistency):
   - `walk_forward.py:7622` (`out_of_sample_validation` summary capacity) —
     now passes `leverage=leverage, short_exposure=short_exposure`.
   - `walk_forward.py:11485` (`run_monte_carlo` summary capacity) — now passes
     `leverage=getattr(args, "leverage", 1.0)` /
     `short_exposure=getattr(args, "short_exposure", 0.0)`.

2. **Added `--leverage` / `--short-exposure` to `run_backtest.py`** CLI
   (it previously lacked them, so single-backtest capacity could not reflect
   the cost drag). The capacity call now passes them; config records them.

3. **Added 8 focused tests** (5 in `test_walk_forward.py`, 3 in
   `test_run_backtest.py` + 1 CLI parse test) covering:
   - leverage×funding drag reduces capacity by `1 + cost_drag/ann_factor`.
   - short_exposure×borrow drag reduces capacity.
   - zero drag (default leverage=1.0/short=0.0 or zero costs) is bitwise
     identical to baseline.
   - invalid (negative/non-finite) cost/leverage/short_exposure raise
     `ValueError`.
   - the drag also scales every period of `capacity_trend`.

4. **Documented** the cost-drag capacity in
   `references/cost_models.md` (new "Borrow/funding cost drag" section) and
   `SKILL.md` (run_backtest bullet).

## What was actually verified

- `test_walk_forward.py` full: **232 passed** (was 227, +5 new).
- `test_run_backtest.py` full: **131 passed** (was 127, +4 new incl. CLI parse).
- Combined walk_forward + run_backtest with `-n 4`: **363 passed** in 4m42s.
- Borrow/funding cost sweep tests (3 files): **4 passed**.
- Focused capacity/participation/cost-drag subset: **72 passed**.
- End-to-end smoke test: leverage=2.0/funding=0.04 reduces capacity by exactly
  `1/(1+0.04/252)` (ratio 0.99984 matches expected 0.99984).
- CLI `--help` for both `run_backtest.py` and `walk_forward.py` shows the
  `--leverage` / `--short-exposure` flags.

## What remains unresolved

- 9 pre-existing `test_reporting.py` failures (tear sheet/heatmap PNG
  generation, matplotlib backend issues) — unrelated to this work, unchanged.
- Full quant gate (all tests) was **not** re-run to completion this session
  (it exceeds the 30-min single-command budget). The combined walk_forward +
  run_backtest run (363 passed) plus the targeted sweep runs cover the changed
  surface; the reporting failures are the only known baseline delta.
- No profitability/capacity claim: committed-fixture verdicts remain
  `NOT SUPPORTED`. This is a methodology/capacity-model improvement, not
  evidence any strategy is profitable.

## Approaches already tried / failed

- None this session. The implementation was already present; the work was
  gap-closing (2 missing call-site threadings + run_backtest CLI parity),
  test coverage, and docs.

## One precise next task

Run the **full quant gate** to completion to confirm the baseline holds:

```bash
cd skills/quantitative-backtesting
python3 -m pytest tests/ -p no:cacheprovider -q -n 4
```

Require: core tests all pass; only the 9 pre-existing `test_reporting.py`
failures are acceptable. Expected count is now ~1546+ passed (baseline was
1538 + 5 walk_forward + 4 run_backtest = ~1547, minus the 9 reporting
failures). If any *new* failure appears outside `test_reporting.py`, bisect
against commit `fa2b537` to confirm it is not a regression from this
session's changes (`run_backtest.py` CLI + `walk_forward.py` two call-site
threadings + tests + docs).

## Constraints for next session

- Do not commit unless explicitly asked.
- Do not weaken existing `try/except` or CLI validation.
- Use `-n 4`; the full gate needs >30 min — run it as a background process
  or with a raised timeout.
- The capacity cost-drag is a *measurement*, not a charged cost — it must
  never change backtest returns, P&L, or Sharpe. Any test asserting
  otherwise indicates a regression.