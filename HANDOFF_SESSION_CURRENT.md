# Handoff — Session 136 (2026-11-19): capacity participation-rate cap wired into run_backtest; full gate GREEN (1535 passed)

## Baseline
- HEAD `157f83d`; branch `main`.
- Previous full gate: 1522 passed (`-n 4`).
- Working tree at session start already contained the incomplete
  `estimate_capacity(max_participation_rate=...)` implementation plus 9
  registered tests in `test_walk_forward.py`.

## What this session changed
- `scripts/run_backtest.py`: added `--max-participation-rate`, validated it
  loudly before the capacity `try/except`, passed it to `estimate_capacity`
  (so capacity and `capacity_trend` are capped), and recorded it in
  `results["config"]["max_participation_rate"]`.
- `tests/test_run_backtest.py`: `_Args` extended; 4 new registered tests
  (parse, cap binds with exact `rate * ADV_notional`, loose cap unchanged,
  invalid values raise).
- `SKILL.md` and `references/cost_models.md`: documented the cap formula,
  panel scaling, trend behaviour, and full-rebalance limitation.

## Verified evidence
| Check | Result |
|---|---|
| `test_walk_forward.py -k participation_rate` | 9 passed |
| `test_run_backtest.py` full file | 127 passed |
| Registry audit tests | passed (both files) |
| **Full quant gate** (`-n 4`) | **1535 passed, EXIT 0** (1459.84s) |
| CLI smoke on AAPL fixture, rate 0.001 | capacity = 11,614,740.3939 = exact `0.001 * ADV_notional`, trend last matches, EXIT 0 |

Gate-dirtied generated artifacts were reverted after inspection.

## What remains unresolved
- Cap is not yet plumbed through walk-forward / CPCV / OOS / Monte Carlo; those
  paths remain impact-model-only.
- No profitability or capacity claim; verdicts on committed fixtures remain
  `NOT SUPPORTED`.
- Changes are **uncommitted** (do not commit unless explicitly asked).

## Next task (see HANDOFF_SESSION_136.md for exact line numbers)
Thread `--max-participation-rate` through `walk_forward.py` (parser + the eight
`estimate_capacity` call sites: 1102, 1309, 4624, 4832, 6973, 7073, 7430,
10631, 11185), record it in the summaries, add one binding-cap test for a
per-period window and its summary, then re-run the full gate (`-n 4`, baseline
1535, require EXIT 0). Opt-in default `None` must leave all published numbers
unchanged.

## Do not repeat
- Do not re-run the full gate unchanged expecting a different verdict.
- Do not silently swallow an invalid participation rate into a `None` capacity.
- Do not tune costs/verdicts to force `SUPPORT`.
