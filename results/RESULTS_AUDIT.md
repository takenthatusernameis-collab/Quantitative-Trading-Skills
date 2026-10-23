# Results Artifacts Audit (2026-10-23)

Status legend: REPRODUCIBLE = regenerable from committed script+input; RETIRED = not reproducible, historical only; SYNTHETIC = generated from bundled synthetic data, not market evidence.

## Root `results/`
- `metrics.json`, `tear_sheet_summary.json`, `monte_carlo_results.json`, `report.txt`, `equity_curve.png`, `returns_distribution.png`, `monte_carlo_equity_curve.png`, `tear_sheet.html`: RETIRED. Input `splits_test_data.csv` missing. See `RETIREMENT_NOTICE.md`.
- `data_provenance.json`, `benchmark_provenance.json`: provenance for the retired artifacts above; do not treat as results.
- `results/resolution_floor/*.json`: REPRODUCIBLE from `skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py` etc.; synthetic control fixture, not market evidence.
- `results/README.md`, `results/RETIREMENT_NOTICE.md`: documentation.

## `skills/quantitative-backtesting/results/`
- `resolution_floor/*.json`: REPRODUCIBLE (subset of root resolution_floor); provenance embedded.

## `skills/quantitative-backtesting/examples/example_output/`
- All artifacts: REPRODUCIBLE from `full_pipeline_example.py` / example scripts on bundled synthetic `sample_ohlcv.csv`. SYNTHETIC; not market evidence. Regenerate with the example scripts.

## `test_output/`
- Not committed (gitignored); ephemeral test artifacts only.

## General rule
No committed artifact in this repository is evidence about a real security or market. Resolution-ladder and example outputs are machinery checks on synthetic data.
