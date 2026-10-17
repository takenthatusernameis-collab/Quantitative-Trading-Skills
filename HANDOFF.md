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

- Full skill test suite: 294/294 passed.
- End-to-end CLI: `run_backtest --multi-symbol --strategy cross_sectional_momentum` writes the survivorship section to the tear sheet HTML and the survivorship_bias dict to the JSON summary.
- Item #1 (bias_controls_engaged reflects survivorship) verified end-to-end: a `--multi-symbol` run without `--validate-point-in-time` reports `bias_controls_engaged=True` in `tear_sheet_summary.json` (test `test_cli_multi_symbol_survivorship_sets_bias_controls_engaged`, passing).

## What remains unresolved

**No panel/multi-asset support in the walk-forward / CPCV / Monte Carlo / OOS CLIs.** A multi-asset universe can currently only be backtested via `run_backtest --multi-symbol`, which runs a single panel backtest with no rolling validation. There is no walk-forward or CPCV over a multi-symbol universe, and no survivorship detection there. This is a larger feature gap, not a small enhancement; defer unless a concrete research need arises.

Item #1 (`bias_controls_engaged` reflecting survivorship screening on the run_backtest path) is **resolved**: `run_backtest.py:391-392` sets `results["bias_controls_engaged"] = True` when `pit_result is not None or survivorship is not None`, and reporting.py threads it into `tear_sheet_summary.json`. Covered by `test_cli_multi_symbol_survivorship_sets_bias_controls_engaged`; full suite passes.

## Next task (precise, evidence-backed)

Item #1 is complete and verified (see above). The only remaining known gap is item #2 (panel/multi-asset walk-forward / CPCV / Monte Carlo / OOS support), which the prior HANDOFF explicitly defers as a larger feature gap unless a concrete research need arises.

**Next task:** Before touching item #2, confirm a concrete research need. If none arises, treat the quant backtesting skill as stable — no further change required; full suite 294/294 passing. If a research need arises, the bounded entry point is adding single-strategy panel universe support to the walk_forward CLI with survivorship detection, verified end-to-end via `tear_sheet_summary.json` reporting `bias_controls_engaged=True` and `survivorship_bias` present. Constraint: do not implement item #2 without a concrete research need (per prior deferral).

(End of file - total 44 lines)