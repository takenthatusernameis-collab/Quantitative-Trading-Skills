# Handoff — Quantitative Trading Skills Repository

**Last updated:** 2026-10-13, after adding regression tests for the provenance / point-in-time / survivorship CLI integration and fixing two multi-symbol provenance defects.

## Current repository state

- Default branch: `main`.
- Main package: `skills/quantitative-backtesting/` (strategies, scripts, tests, and validation references).
- Dependencies used by the test suite include `pandas` and `numpy`; plotting tests require Matplotlib to be available. (Environment note: a fresh session must `pip3 install numpy pandas matplotlib` before the suite runs — the baseline failures on 2026-10-13 were only `ModuleNotFoundError`, not code defects.)

## Recent durable work

1. **Provenance / point-in-time / survivorship integration (prior sessions, code at HEAD):** `run_backtest.py` captures `DataProvenance` at load time (`return_provenance=True`), serializes it into `results["data_provenance"]` and a `data_provenance.json` artifact, runs `validate_point_in_time` on data + strategy signals when `--validate-point-in-time` is passed (recording the outcome in `results["point_in_time_validation"]`, aborting in strict mode via `--point-in-time-strict`), and supports `--multi-symbol` which loads the full symbol universe via `load_multi_symbol`, runs `detect_survivorship_bias`, prints the report, and persists `survivorship_bias.json`. The walk-forward CLI (`walk_forward.py`) shares `--validate-point-in-time` / `--point-in-time-strict` across all four subcommands via `_load_and_validate_data`.
2. **Integration regression tests (this session):** the integration code existed but had no CLI-level coverage. Added 10 tests to `test_run_backtest.py` and 1 to `test_data_loader.py` covering: provenance serialization into results (single-asset and per-symbol panel forms), backward-compatible omission when no provenance is captured, PIT outcome recording (clean pass, duplicate-timestamp violation, per-symbol panel validation, non-strict completion), the strict-abort semantics of `_handle_point_in_time_results` (aborts only on violations, never warnings), `parse_args` wiring of the three new flags, and two end-to-end `main()` tests verifying the `data_provenance.json` and `survivorship_bias.json` artifacts are written with checksums, source paths, entered/exited symbols, and a non-empty panel backtest on the overlapping window.
3. **Multi-symbol provenance defects fixed (this session, `scripts/data_loader.py` `load_multi_symbol`):** (a) per-symbol `DataProvenance` now carries a checksum (`_compute_checksum`) and `date_range_final` — previously both were `None`, so the multi-symbol provenance artifact could not support integrity verification or reproducibility; (b) the aggregate stacked frame no longer emits a spurious "Data validation failed: Duplicate dates in index" warning — cross-symbol duplicate timestamps are expected in panel files and per-symbol validation (which drops failing symbols) is the authoritative check.
4. **Test-suite count correction:** the previous handoff's stated total (183) did not match the sum of its per-file counts (196). The authoritative totals are recomputed below from the tests actually executed.

## Verification status — measured this session

- **Full test suite:** 207 tests passing across all 9 test entry points.
  - `test_data_loader.py`: 16/16 (was 15; +1 `load_multi_symbol` provenance test)
  - `test_performance.py`: 13/13
  - `test_reporting.py`: 36/36 (`unittest`, `OK`)
  - `test_run_backtest.py`: 35/35 (was 25; +10 integration tests)
  - `test_strategy_builder.py`: 27/27
  - `test_walk_forward.py`: 56/56
  - `test_cpcv.py`: 16/16
  - `test_monte_carlo.py`: 7/7
  - `test_generate_sample_data.py`: 1/1
- **End-to-end CLI verification (manual):**
  - Single-asset run with `--validate-point-in-time` exits 0, prints "Point-in-time validation passed", and writes `data_provenance.json` with source path, checksum, transformations, and validation outcome.
  - `--multi-symbol` run on a crafted 3-symbol panel (one survivor, one late entry, one early exit) with `cross_sectional_momentum` exits 0, reports bias_score 1.0 with the correct entered/exited symbols, and writes `survivorship_bias.json` plus per-symbol `data_provenance.json` with checksums.
- **Pinned snapshot stability:** regenerating `test_output/` via the canonical command in SKILL.md reproduces byte-identical `report.txt`, identical `metrics.json`, and a `tear_sheet_summary.json` that differs only in `plot_files` (absolute output-directory paths — environment-dependent by design, not a regression).
- **Research limitation:** this package's strategy tests and examples are largely synthetic. No out-of-sample evidence of live-trading profitability is established by these tests.
- **Modeling limitations:** market impact is a linear participation model; borrow and funding rates are constant annualized with data-frequency-aware per-period conversion; market impact, borrow rates, and funding rates are not time-varying. The PIT signal/next-return correlation check (threshold 0.3) cannot distinguish genuine alpha from look-ahead — it is a screening heuristic, not proof.

## Next agent task

The reproducibility chain is complete at the results/artifact level. The most impactful next step is to make provenance first-class in the primary reporting artifact and in the walk-forward workflows:

1. **Surface provenance in the tear sheet:** extend `generate_tear_sheet` in `scripts/reporting.py` to render a "Data Provenance" section (source path, checksum, date range, filters, validation outcome) in the HTML and a `data_provenance` key in the JSON summary when `results["data_provenance"]` is present, omitting it otherwise (backward compatible). Add tests in `test_reporting.py` for presence, content, and omission.
2. **Persist PIT validation results in walk-forward outputs:** `_load_and_validate_data` in `scripts/walk_forward.py` currently only prints PIT results; attach them to the analysis dicts so they flow into the walk-forward JSON artifacts and tear-sheet rendering (the reporting layer already renders arbitrary analysis sections).
3. Optional follow-up: refine the PIT correlation check to compare signal changes against *contemporaneous* returns (true same-bar look-ahead) in addition to next-period returns, since a signal that genuinely predicts next-period returns is alpha, not necessarily look-ahead.

These are bounded, evidence-based extensions of the provenance/validation work. Preserve existing schemas and avoid breaking tests; include lightweight tests for new integration points.

## Test commands

Run each command from the repository root and preserve the actual result:

```bash
for t in test_data_loader test_performance test_reporting test_run_backtest          test_strategy_builder test_walk_forward test_cpcv test_monte_carlo          test_generate_sample_data; do
  python3 skills/quantitative-backtesting/tests/$t.py || exit 1
done
```

`test_reporting.py` uses `unittest`; its exit status and `OK` summary are the pass/fail evidence. Other files use a custom runner. Recompute the total from the tests actually executed; do not assume the former total remains valid after the added coverage.

(End of file)
