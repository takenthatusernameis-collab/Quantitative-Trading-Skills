# Handoff — Session 134 (2026-11-18): Sweep measures criterion 5 instead of faking a failure

## Latest baseline (verified)
- **`tests/test_falsifiable_hypothesis_example.py`: 36 passed** (269.83s).
- Default example CLI: **EXIT 0, 8.48s**, verdict `NOT SUPPORTED`.
- Working tree has 3 modified files (uncommitted):
  `examples/falsifiable_hypothesis_example.py`,
  `tests/test_falsifiable_hypothesis_example.py`, `examples/README.md`.

## What changed
The cost sensitivity sweep hard-coded `sample_benchmark.csv`, so every row
loaded N=1, DAR was `None`, and criterion 5 was reported as **failed without
being measured**. It now resolves the headline `BENCHMARK_FILES` (N=2) by
default and raises if that set is missing. Criteria carry an `evaluable` flag:
a statistic the configuration cannot produce is printed `[N/A]` and listed in
`criteria_unavailable`, still counted as not satisfied (verdict semantics
unchanged, conservative). Sweep rows record `n_benchmarks` /
`deflated_alpha_ratio_evaluable`; `--output-json` now preserves
`criteria_unavailable`.

Measured default sweep: N=2 at every level, DAR 0.332383 → 0.313580 (all
`NOT SUPPORTED`; criterion 5 now fails for a real measured reason). Headline
DARs match the pre-change direct measurements, so no result was retuned.

## Current handoff & precise next task
See `HANDOFF_SESSION_134.md`. One-line: the CLI's JSON artifact still never
contains the sweep — `main()` whitelists a `cost_sweep` key that no result
sets (`examples/falsifiable_hypothesis_example.py:1180,1223`). Capture the
sweep rows into the artifact and add a CLI regression asserting one row per
cost level with `n_benchmarks >= 2` and a finite DAR.

## Constraints
- Do NOT hard-code a single benchmark in the sweep again.
- Do NOT let an unavailable criterion count as a pass.
- The full quant gate was NOT re-run this session (baseline 1505 passed,
  session 133); the affected file plus its direct dependents are green.
- `pytest-xdist` still not pinned in `requirements.txt` (needs user
  confirmation); tests ran under `/tmp/venv`.
- No profitability/capacity claim; committed verdicts remain NOT SUPPORTED.
- Do not commit unless explicitly asked.
