# Handoff — Quantitative Trading Skills Repository

  **Last updated:** 2026-10-13, after implementing the buy-and-hold benchmark baseline integration in the `run_backtest` CLI path (`--benchmark` flag, `run_backtest()` benchmark parameter, `benchmark_provenance.json` artifact, buy-and-hold returns aligned to strategy returns via inner join on common dates), adding 4 tests to `test_run_backtest.py` and 2 to `test_reporting.py`, and regenerating the pinned snapshot (only `load_timestamp` differs, by design). Full suite: **223 tests passing**.

## Current repository state

- Default branch: `main`.
- Main package: `skills/quantitative-backtesting/` (strategies, scripts, tests, and validation references).
 - Dependencies used by the test suite include `pandas` and `numpy`; plotting tests require Matplotlib to be available.

## Recent durable work

1. **Provenance / point-in-time / survivorship integration (prior sessions, code at HEAD):** `run_backtest.py` captures `DataProvenance` at load time (`return_provenance=True`), serializes it into `results["data_provenance"]` and a `data_provenance.json` artifact, runs `validate_point_in_time` on data + strategy signals when `--validate-point-in-time` is passed (recording the outcome in `results["point_in_time_validation"]`, aborting in strict mode via `--point-in-time-strict`), and supports `--multi-symbol` which loads the full symbol universe via `load_multi_symbol`, runs `detect_survivorship_bias`, prints the report, and persists `survivorship_bias.json`. The walk-forward CLI (`walk_forward.py`) shares `--validate-point-in-time` / `--point-in-time-strict` across all four subcommands via `_load_and_validate_data`.
2. **Integration regression tests (this session):** the integration code existed but had no CLI-level coverage. Added 10 tests to `test_run_backtest.py` and 1 to `test_data_loader.py` covering: provenance serialization into results (single-asset and per-symbol panel forms), backward-compatible omission when no provenance is captured, PIT outcome recording (clean pass, duplicate-timestamp violation, per-symbol panel validation, non-strict completion), the strict-abort semantics of `_handle_point_in_time_results` (aborts only on violations, never warnings), `parse_args` wiring of the three new flags, and two end-to-end `main()` tests verifying the `data_provenance.json` and `survivorship_bias.json` artifacts are written with checksums, source paths, entered/exited symbols, and a non-empty panel backtest on the overlapping window.
3. **Multi-symbol provenance defects fixed (this session, `scripts/data_loader.py` `load_multi_symbol`):** (a) per-symbol `DataProvenance` now carries a checksum (`_compute_checksum`) and `date_range_final` — previously both were `None`, so the multi-symbol provenance artifact could not support integrity verification or reproducibility; (b) the aggregate stacked frame no longer emits a spurious "Data validation failed: Duplicate dates in index" warning — cross-symbol duplicate timestamps are expected in panel files and per-symbol validation (which drops failing symbols) is the authoritative check.
4. **Test-suite count correction:** the previous handoff's stated total (183) did not match the sum of its per-file counts (196). The authoritative totals are recomputed below from the tests actually executed.
5. **Tear-sheet provenance rendering and PIT persistence completed (this session).** The prior commit `dd6fad5` (blank message) added a "Data Provenance" section to `generate_tear_sheet` and wired PIT capture into `_load_and_validate_data`, but left three defects that this session fixed:
    - **`reporting.py` wrong field names:** the section looked for keys `filters`, `symbol`, `validation`, `transformations`, `per_symbol`, `panel_shape` — none of which exist in `DataProvenance.to_dict()`. Only `source_path`, `checksum`, `date_range_final` happened to match, so filters and validation outcome were silently dropped. Rewrote the section to iterate the actual dataclass fields (`source_path`, `load_timestamp`, `file_format`, `file_size_bytes`, `symbol_filter`, `start_date_filter`, `end_date_filter`, `date_range_original`, `date_range_final`, `original_shape`, `final_shape`, `columns_original`, `columns_final`, `validation_passed`, `validation_messages`, `transformations_applied`, `checksum`), and added handling for the per-symbol panel form (`{symbol: prov_dict}`) so each symbol's provenance renders under a `symbol / field` key. Also surfaced the results-level `point_in_time_validation` dict (which lives at `results["point_in_time_validation"]`, not inside `data_provenance`) in both the HTML section and the JSON summary.
    - **`walk_forward.py` dead code in `run_parameter_optimization`:** removed the placeholder `if 'pit_results' in locals() or True: pass` block; `pit_results` is now persisted to `point_in_time_validation.json` alongside `parameter_optimization.json` (the results format is a ranked list, so the PIT dict is saved to a separate file to preserve the existing schema).
    - **`walk_forward.py` `block_size` regression in `run_monte_carlo`:** the config dict line `"block_size": args.block_size` was replaced by `"point_in_time_validation": pit_results`, losing `block_size` from the saved config. Restored `"block_size": args.block_size` and kept `point_in_time_validation` in config for consistency with CPCV/walk-forward. Also attached `pit_results` to `mc_base_results` before `generate_tear_sheet` so the Monte Carlo tear sheet renders the same Data Provenance + PIT section as CPCV and walk-forward.

## Verification status — measured this session

 - **Full test suite:** 217 tests passing across all 9 test entry points.
   - `test_data_loader.py`: 17/17
   - `test_performance.py`: 13/13
   - `test_reporting.py`: 40/40 (`unittest`, `OK`) (was 36; +4 provenance-section tests: presence, omission, per-symbol panel, PIT outcome)
   - `test_run_backtest.py`: 35/35
   - `test_strategy_builder.py`: 27/27
   - `test_walk_forward.py`: 61/61 (was 56; +5 PIT-persistence CLI tests: walk-forward summary, backward-compat omission, CPCV summary, Monte Carlo `block_size` regression + PIT, parameter-optimization separate-artifact)
   - `test_cpcv.py`: 16/16
   - `test_monte_carlo.py`: 7/7
   - `test_generate_sample_data.py`: 1/1
 - **End-to-end CLI verification (manual):**
   - Single-asset run with `--validate-point-in-time` exits 0, prints "Point-in-time validation passed", and writes `data_provenance.json` with source path, checksum, transformations, and validation outcome.
   - `--multi-symbol` run on a crafted 3-symbol panel (one survivor, one late entry, one early exit) with `cross_sectional_momentum` exits 0, reports bias_score 1.0 with the correct entered/exited symbols, and writes `survivorship_bias.json` plus per-symbol `data_provenance.json` with checksums.
   - Walk-forward CLI with `--validate-point-in-time` persists `point_in_time_validation` (passed=True) in `walk_forward_summary.json` config and top-level, and the tear sheet HTML renders the Data Provenance table with both provenance fields and the PIT outcome.
 - **Pinned snapshot stability:** regenerating `test_output/` via the canonical command in SKILL.md reproduces byte-identical `report.txt` and `metrics.json`. `tear_sheet.html` and `tear_sheet_summary.json` were regenerated with the corrected Data Provenance section now rendering all `DataProvenance.to_dict()` fields (previously only `source_path`, `checksum`, `date_range_final` matched); `tear_sheet_summary.json` also includes the full `data_provenance` dict. Differences in `plot_files` (absolute output-directory paths) and `load_timestamp` remain environment/time-dependent by design.
- **Research limitation:** this package's strategy tests and examples are largely synthetic. No out-of-sample evidence of live-trading profitability is established by these tests.
- **Modeling limitations:** market impact is a linear participation model; borrow and funding rates are constant annualized with data-frequency-aware per-period conversion; market impact, borrow rates, and funding rates are not time-varying. The PIT signal/next-return correlation check (threshold 0.3) cannot distinguish genuine alpha from look-ahead — it is a screening heuristic, not proof.

## Next agent task

The provenance/point-in-time/survivorship reproducibility chain is now complete at the results/artifact/tear-sheet level:

- `run_backtest.py` captures `DataProvenance` at load time, serializes it into `results["data_provenance"]` and `data_provenance.json`, runs `validate_point_in_time` on data + signals, and records the outcome in `results["point_in_time_validation"]`.
- `generate_tear_sheet` renders a "Data Provenance" section (source path, checksum, date range, filters, transformations, validation outcome) plus the PIT outcome in the HTML, and surfaces both keys in the JSON summary — for single-asset and per-symbol panel forms.
- The walk-forward CLI (`walk_forward.py`) persists `point_in_time_validation` in the CPCV, walk-forward, and Monte Carlo summary/result JSON artifacts and in the per-command tear sheets, and in a separate `point_in_time_validation.json` for parameter optimization.

**Completed this session — same-bar (contemporaneous) look-ahead check:**

- `validate_point_in_time` in `data_loader.py` now also correlates signal changes with *same-bar* returns (`df["close"].pct_change()`, no shift), in addition to the existing next-period correlation. Same-bar correlation is a stricter look-ahead indicator: no information should flow from a signal to the return of the same bar. The 0.3 threshold and existing next-period check are unchanged; the same-bar check is a supplementary violation, so existing tests stay green.
- Added `test_validate_point_in_time_detects_same_bar_lookahead` in `test_data_loader.py`: a frame whose signal equals the same-bar return (guaranteeing corr=+1.0) is flagged as a violation with a "same-bar" message.
- Full suite: **217 tests passing** (17 data_loader + 13 performance + 40 reporting + 35 run_backtest + 27 strategy_builder + 61 walk_forward + 16 cpcv + 7 monte_carlo + 1 generate_sample_data).
- The `_validate_point_in_time` wrapper in `run_backtest.py` (line 57) calls `validate_point_in_time(check_df, signal_column="_pit_signal")` for single-asset data, so the refinement propagates to `run_backtest` and walk-forward `--validate-point-in-time` automatically.

**Completed this session — buy-and-hold baseline integration:**

Implemented the buy-and-hold baseline end-to-end in the `run_backtest` CLI path:

1. **`run_backtest.py` — `run_backtest()` function:** Added a `benchmark=None` parameter (a DataFrame of benchmark OHLCV indexed by date). When provided, `validate_point_in_time`-style buy-and-hold returns are computed as `benchmark["close"].pct_change()` (close-to-close, no `shift(-1)` — the strategy already trades at next-period open, so this is an apples-to-apples comparison window). The benchmark returns are aligned to the strategy returns index via `strategy_returns.align(benchmark_returns, join="inner")` (inner join on common trading dates), and attached as `results["benchmark"]`. The benchmark file path is also recorded in `results["config"]["benchmark"]` for reproducibility.
2. **`run_backtest.py` — `parse_args()`:** Added `--benchmark` (type `str`, default `None`).
3. **`run_backtest.py` — `main()`:** Loads the benchmark with `load_data(args.benchmark, return_provenance=True)`, validates it, passes it to `run_backtest`, and persists a `benchmark_provenance.json` artifact (with `source_path`, `checksum`, `file_format`, `file_size_bytes`, `validation_passed`, `date_range_final`) next to `data_provenance.json`. Backward compatible: when `--benchmark` is absent, no benchmark artifact or `results["benchmark"]` key is emitted.
4. **`reporting.py` — `generate_tear_sheet()`:** Added the missing `benchmark_annualized_return` row to the HTML "Benchmark Comparison" table. (`benchmark_total_return`, `correlation_with_benchmark`, `alpha`, `beta` were already rendered; the text report in `performance.py:370-379` already included `benchmark_annualized_return`.) Both HTML and JSON summary now surface all five benchmark metrics when `calculate_metrics` produces them.
5. **`test_run_backtest.py`:** Added 4 tests:
   - `test_run_backtest_with_benchmark_attaches_aligned_returns` — benchmark returns attached, aligned on common dates, values match `pct_change()` with no shift.
   - `test_run_backtest_without_benchmark_omits_key` — backward compat: no `benchmark` key when benchmark is None.
   - `test_benchmark_superset_aligns_correctly` — a benchmark with extra dates before/after the strategy data aligns via inner join without crashing or leaking extra dates; alpha/beta/correlation computed on the aligned series.
   - `test_cli_benchmark_writes_artifact_and_metrics` — end-to-end CLI with `--benchmark` writes `benchmark_provenance.json` (source path, checksum, validation outcome) and the metrics JSON contains `benchmark_total_return`, `benchmark_annualized_return`, `correlation_with_benchmark`, `alpha`, `beta`.
6. **`test_reporting.py`:** Added 2 tests:
   - `test_generate_tear_sheet_includes_benchmark_section` — HTML renders "Benchmark Comparison" with "Benchmark Annualized Return" and the JSON summary includes the benchmark metrics.
   - `test_generate_tear_sheet_omits_benchmark_when_absent` — section omitted when no benchmark metrics.

**What was actually verified this session:**
- **Full test suite:** 223 tests passing across all 9 test files.
  - `test_data_loader.py`: 17/17
  - `test_performance.py`: 13/13
  - `test_reporting.py`: 42/42 (was 40; `unittest` OK)
  - `test_run_backtest.py`: 39/39 (was 35; +4 benchmark tests)
  - `test_strategy_builder.py`: 27/27
  - `test_walk_forward.py`: 61/61
  - `test_cpcv.py`: 16/16
  - `test_monte_carlo.py`: 7/7
  - `test_generate_sample_data.py`: 1/1
- **End-to-end CLI verification (manual):** single-asset run with `--benchmark <path>` exits 0, prints "Loaded benchmark" with checksum, writes `benchmark_provenance.json` (source path, checksum, validation_passed=True, date_range_final), and `metrics.json` contains `benchmark_total_return` (0.1945), `benchmark_annualized_return` (0.1953), `correlation_with_benchmark` (0.0518), `alpha` (-0.2463), `beta` (0.0389). The HTML tear sheet renders the "Benchmark Comparison" table including "Benchmark Annualized Return".
- **Pinned snapshot stability:** the canonical command (`run_backtest.py --data .../sample_ohlcv.csv --params '{"fast_period": 10, "slow_period": 30}' --output .../test_output`) reproduces byte-identical `report.txt` and `metrics.json`; only `load_timestamp` differs (time-dependent by design).

**What remains unresolved:**
- Benchmark support is only wired through the `run_backtest` CLI path, not the walk-forward / CPCV / Monte Carlo CLI subcommands in `walk_forward.py`.
- The benchmark is a simple buy-and-hold (close-to-close); it does not model benchmark dividends, splits, or benchmark trading costs.
- No out-of-sample evidence of live-trading profitability is established.

**Next task — extend buy-and-hold baseline to the walk-forward CLI:**

`walk_forward.py` supports `--walk-forward`, `--cpcv`, `--monte-carlo`, and `--optimize` subcommands, each of which computes OOS returns. None compare OOS performance against a buy-and-hold baseline, so OOS alpha/beta/correlation vs. the market are not reported — a methodological gap when evaluating whether walk-forward OOS returns reflect genuine alpha or simply tracking the benchmark.

Extend the `--benchmark` flag (already in `argparse` at `run_backtest.py` but absent from `walk_forward.py`) to the walk-forward CLI:

1. Add `--benchmark` to `walk_forward.py`'s argument parser.
2. Load the benchmark OHLCV with `load_data` (capture provenance), compute `benchmark["close"].pct_change()` as the buy-and-hold series, and align it to the strategy's full OOS return index (inner join).
3. In each OOS aggregation path (walk-forward, CPCV, Monte Carlo), compute OOS alpha/beta/correlation between the strategy OOS returns and the benchmark buy-and-hold returns on the common OOS dates, and surface them in the `*_summary.json` artifacts.
4. Render the benchmark comparison in the walk-forward/CPCV/Monte Carlo tear sheet sections (reusing the existing `"benchmark_total_return"` rendering logic from `reporting.py` if available, or adding a new per-analysis section).

Evidence and constraints for the next agent:
- `calculate_metrics(results)` in `performance.py:58,204-219` already computes `benchmark_total_return`, `benchmark_annualized_return`, `correlation_with_benchmark`, `alpha`, `beta` from `results["benchmark"]` — a Series of returns aligned (via `returns.align(benchmark_returns, join="inner")`) to the strategy returns index. The walk-forward runner does not currently call `calculate_metrics` with a benchmark; it computes OOS returns directly (see `run_walk_forward_analysis` in `walk_forward.py`).
- The benchmark return for period t is `benchmark["close"].pct_change()` (close-to-close from t-1 to t, no `shift(-1)`).
- `run_backtest.py:run_backtest()` already implements the correct benchmark computation pattern (lines 363–372 of the updated file): `benchmark_returns = benchmark["close"].pct_change(); _, aligned_benchmark = strategy_returns.align(benchmark_returns, join="inner")`. Reuse this pattern for the OOS returns alignment.
- `reporting.py` already has a `"Benchmark Comparison"` HTML section (lines 373-385) and `generate_report` already prints `--- Benchmark Comparison ---` (lines 370-379 of `performance.py`); both key off `benchmark_total_return` in the metrics dict. The walk-forward summaries store their own summary dict (not the `calculate_metrics` output), so the per-analysis benchmark metrics must be added as new keys to the walk-forward/CPCV/Monte Carlo summary dicts.

## Test commands

Run each command from the repository root and preserve the actual result:

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest test_strategy_builder test_walk_forward test_cpcv test_monte_carlo test_generate_sample_data; do
  python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses `unittest`; its exit status and `OK` summary are the pass/fail evidence. Other files use a custom runner. Recompute the total from the tests actually executed; do not assume the former total remains valid after the added coverage.

(End of file)
