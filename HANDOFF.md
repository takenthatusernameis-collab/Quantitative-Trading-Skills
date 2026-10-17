# HANDOFF

## Repository state (as of this session)

- Working tree: changes to `skills/quantitative-backtesting/scripts/reporting.py` and `skills/quantitative-backtesting/tests/test_reporting.py`.
- Test suite: **293/293 passing** (`python3 -m pytest skills/quantitative-backtesting/tests/ -q`).
- Baseline: previous HANDOFF (per-benchmark provenance linkage complete; `bias_controls_engaged` threaded onto all five CLI paths).

## What changed this session

**Surfaced the survivorship-bias detection artifact in the tear sheet, mirroring the data-provenance / point-in-time / bias-controls pattern.**

Prior audit (the HANDOFF's next task) asked whether `survivorship_bias` report artifacts are threaded onto `report_results` consistently across all paths. Investigation found:

- `survivorship_bias` is produced **only** by `run_backtest.py` (`--multi-symbol` mode, `detect_survivorship_bias` in `data_loader.py:494`). It is set on `results["survivorship_bias"]` at `run_backtest.py:385` and persisted to `survivorship_bias.json` at `run_backtest.py:747`.
- The walk-forward / CPCV / Monte Carlo / OOS CLI paths in `walk_forward.py` do **not** load panel data and have no `--multi-symbol` flag, so they never produce a survivorship artifact. There is nothing to thread there; the gap is a missing feature (panel support in those CLIs), not an inconsistency.
- The real defect was on the **reporting** side: `generate_tear_sheet` surfaced `data_provenance`, `point_in_time_validation`, and `bias_controls_engaged` but silently dropped `survivorship_bias`, so a panel backtest's universe-selection analysis was invisible in the tear sheet even though it was persisted to disk.

Changes in `reporting.py`:

- Hoisted the inline `fmt_prov` formatter to module-level `_fmt_prov` (`reporting.py`) so the new section can reuse it.
- Added a standalone "Survivorship Bias Detection" tear-sheet section rendering `bias_score`, `surviving_symbols`, `entered_symbols`, `exited_symbols`, `insufficient_data`, `large_gaps`. It is rendered outside the `data_prov or pit_val or bias_flag` guard so it appears even on a plain panel run without `--validate-point-in-time`.
- Surfaced `results["survivorship_bias"]` into `tear_sheet_summary.json` under the same key (omitted when absent, backward compatible).

Tests added in `test_reporting.py` (3 new):

- `test_generate_tear_sheet_surfaces_survivorship_bias` — HTML section + JSON key present.
- `test_generate_tear_sheet_omits_survivorship_bias_when_absent` — omitted when absent.
- `test_generate_tear_sheet_survivorship_bias_without_provenance` — renders without any provenance/PIT/bias-controls artifacts.

End-to-end verified: `run_backtest --multi-symbol` now writes `Survivorship Bias Detection` into `tear_sheet.html` and `survivorship_bias` (bias_score=1.0) into `tear_sheet_summary.json`.

## What was verified

- Full skill test suite: 293/293 passed (was 290; +3 new tests).
- End-to-end CLI: `run_backtest --multi-symbol --strategy cross_sectional_momentum` writes the survivorship section to the tear sheet HTML and the survivorship_bias dict to the JSON summary.

## What remains unresolved

1. **`bias_controls_engaged` does not reflect survivorship screening.** The flag is `bool(pit_results is not None)` everywhere (e.g. `walk_forward.py:573`, `reporting.py` fallback). On a `--multi-symbol` run **without** `--validate-point-in-time`, `pit_results` is None so `bias_controls_engaged` reports False — yet `detect_survivorship_bias` *did* run and `survivorship_bias` is populated. The flag's docstring ("point-in-time validation, survivorship screening, and multiple-testing deflation") therefore overstates what it measures on that path. Small fix: OR the survivorship artifact into the flag on the run_backtest path (and only there, since the other paths have no survivorship concept).

2. **No panel/multi-asset support in the walk-forward / CPCV / Monte Carlo / OOS CLIs.** A multi-asset universe can currently only be backtested via `run_backtest --multi-symbol`, which runs a single panel backtest with no rolling validation. There is no walk-forward or CPCV over a multi-symbol universe, and no survivorship detection there. This is a larger feature gap, not a small enhancement; defer unless a concrete research need arises.

## Next task (precise, evidence-backed)

Fix #1 above: make `bias_controls_engaged` on the run_backtest path reflect survivorship screening, so a `--multi-symbol` run without `--validate-point-in-time` still reports `bias_controls_engaged=True` when `survivorship_bias` is present. Evidence: `run_backtest.py:383-385` sets `results["survivorship_bias"]` independently of `pit_result` (set at `run_backtest.py:168-170` only when `args.validate_point_in_time`), and `reporting.py:1043` reads `bias_flag = results.get("bias_controls_engaged")` without consulting `survivorship_bias`. Bounded change: in `run_backtest` set `results["bias_controls_engaged"] = bool(pit_result is not None or survivorship is not None)`; add a test that a multi-symbol run without `--validate-point-in-time` surfaces `bias_controls_engaged=True` in the tear-sheet JSON. Run full test suite after.

(End of file - total 44 lines)