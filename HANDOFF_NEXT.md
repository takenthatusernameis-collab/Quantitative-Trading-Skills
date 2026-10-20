# HANDOFF_NEXT

## The one precise next task

**Surface the execution warmup convention in backtest results/metadata** so the
two-bar warmup is observable to consumers (not just buried in docs/comments),
and make it consistent across the CLIs without changing any pinned numbers.

### Why

- The warmup convention is now explicit in `walk_forward.py` (non-book path)
  and documented in `references/validation_methods.md`, but `results` from
  `run_backtest.py` and the summaries from `walk_forward.py`/`cpcv_analysis`
  do not record how many bars were dropped or which convention was used.
- The cross-path parity tests pin that `run_backtest` and `walk_forward`
  drop a different number of warmup bars for the net-exposure path (run_backtest
  opens the position on the first executable bar; walk_forward drops the
  undefined bars) — this difference must remain intact and must stay test-covered.
- Making the convention explicit in metadata aids reproducibility and prevents
  confusion when comparing runs across entry points.

### Concrete steps

1. **Define a stable metadata key** (e.g., `execution_warmup_bars` and/or
   `warmup_convention`) in the results/config dicts.
   - In `walk_forward._calculate_strategy_returns` (and any place that drops
     bars due to warmup), record `execution_warmup_bars` in the returned info if
     possible, or thread it through to callers.
   - In `run_backtest.py`, record it in `results["config"]` / `results` metadata
     (e.g., `"warmup_convention": "run_backtest_open_first_executable"` vs
     `"walk_forward_drop_undefined"`), without changing return series.
   - For walk-forward/CPCV/monte-carlo/out-of-sample summaries, add the same
     metadata when relevant.

2. **Keep behavior unchanged**: do not alter the dropping/reindexing logic.
   All existing pins must hold:
   - CPCV: `CPCV_OOS_RETURN_REFERENCE`, `CPCV_OOS_BAR_COUNT` (92), selected
     lookbacks unchanged; `test_cpcv_pinned_number_is_reproducible_from_first_principles`
     must pass.
   - Walk-forward bar counts and pinned numbers unchanged.
   - Cross-path parity: `test_run_backtest_panel_matches_walk_forward_return_calculator`
     and `test_run_backtest_dict_panel_matches_walk_forward_return_calculator`
     must still pass (the warmup difference must remain).

3. **Document briefly** in the skill docs or references if helpful, but keep
   changes minimal and reversible.

### Evidence to look at

- `skills/quantitative-backtesting/scripts/walk_forward.py:1713-1714,1774-1778,1844-1846`
- `skills/quantitative-backtesting/scripts/run_backtest.py:335,381-400,449`
- `skills/quantitative-backtesting/tests/test_run_backtest.py:1382-1455` (cross-path parity)
- `skills/quantitative-backtesting/tests/test_cpcv.py` (pinned numbers and first-principles reproduction)
- `skills/quantitative-backtesting/references/validation_methods.md` ("The Warmup Bars of a Window")

### Constraints

- **No behavior change.** Metadata only. Do not "fix" the warmup difference
  between entry points — it is intentional and pinned.
- **Preserve all pinned values.** Run the full quant test suite (all files
  under `skills/quantitative-backtesting/tests/`) before and after; every test
  must pass.
- **Keep it bounded.** Add metadata fields only where they are cheap and
  don't require restructuring the return pipelines.
