# Handoff — Session 134 (2026-11-18): Cost sweep now evaluates criterion 5 honestly

## Latest baseline (verified this session)
- **`tests/test_falsifiable_hypothesis_example.py`: 36 passed** in 269.83s
  (33 before + 3 new regressions).
- Default example CLI: **EXIT 0, 8.48s**, 124 lines, verdict `NOT SUPPORTED`.
- Working tree (uncommitted): `examples/falsifiable_hypothesis_example.py`,
  `tests/test_falsifiable_hypothesis_example.py`, `examples/README.md`. No
  generated artifacts dirtied.

## What changed
The cost sensitivity sweep used to hard-code `sample_benchmark.csv` as its
benchmark, so every row loaded **one** benchmark, `deflated_alpha_ratio` was
`None` (`n_benchmarks = 1`) and criterion 5 was printed as **failed** in all
five rows without ever being measured.

1. `run_cost_sensitivity_sweep` now defers benchmark resolution to
   `run_hypothesis_test` (`benchmark_path=None` → `BENCHMARK_FILES`, N=2), and
   raises a clear `FileNotFoundError` if that set is absent instead of
   silently degrading to one benchmark.
2. Rows carry `n_benchmarks` and `deflated_alpha_ratio_evaluable`; the default
   sweep asserts N ≥ 2 and a finite DAR at every level.
3. `run_hypothesis_test` criterion results carry `evaluable`. A criterion
   whose statistic this configuration cannot produce is printed `[N/A]` with
   an explanation and listed under `criteria_unavailable`, not `[FAIL]`.
   It is still counted as not satisfied (`passed=False`), so an uncorrected
   single-benchmark alpha can never be called SUPPORTED — verdict semantics
   are unchanged, only the reporting is honest.
4. Sweep output prints `unavailable=<criterion>` separately from
   `failing=<criterion>` and adds a NOTE for single-benchmark overrides.
5. `criteria_unavailable` is now included in `--output-json` artifacts
   (verified: sample JSON contains `criteria_unavailable: []`).
6. `examples/README.md` documents the sweep's benchmark set.

## Measured effect (default sweep on `sample_ohlcv.csv`)
| level (comm+slip) | n_benchmarks | DAR | verdict |
|---|---|---|---|
| 0bp+0bp | 2 | 0.332383 | NOT SUPPORTED |
| 1bp+0bp | 2 | 0.331122 | NOT SUPPORTED |
| 2bp+1bp | 2 | 0.328603 | NOT SUPPORTED |
| 5bp+2.5bp | 2 | 0.322950 | NOT SUPPORTED |
| 10bp+5bp | 2 | 0.313580 | NOT SUPPORTED |

Criterion 5 now fails **for a measured reason** (DAR ≈ 0.31–0.33 < 0.90), and
the directional claim (Sharpe −0.8914 → −0.9716, return −4.98% → −5.40%,
DAR 0.3324 → 0.3136) holds. Headline DARs match the pre-change direct
measurements (0.33238333 / 0.32860291). No verdict changed; still
`NOT SUPPORTED` and no profitability claim.

Single-benchmark override (`benchmark_path=<one csv>`): `n_benchmarks == 1`,
DAR `None`, `criteria_unavailable == ["deflated_alpha_ratio_gt_0.90"]`,
console prints `[N/A] deflated_alpha_ratio_gt_0.90`, an `UNAVAILABLE CRITERIA`
block and a sweep NOTE; verdict stays `NOT SUPPORTED`.

## Verification evidence
| Check | Result |
|---|---|
| `pytest tests/test_falsifiable_hypothesis_example.py` | 36 passed, 269.83s |
| `-k "cost_sensitivity_sweep or cost_sweep or criterion_5"` | 9 passed, 134.87s |
| `test_walk_forward.py` + `test_examples_coverage.py` `-k falsifiable` | 2 passed, 9.28s |
| `test_test_window_observations.py -k example_reports_the_same_number` | 1 passed, 2.50s |
| sample sweep direct measurement | DARs and N above |
| single-benchmark direct measurement | N=1, DAR None, `[N/A]` + unavailable block |
| CLI `--output-json /tmp/fx.json --no-cost-sweep` | EXIT 0; `criteria_unavailable: []` in JSON |

## What remains unresolved
- Changes are **uncommitted** (do not commit unless the user asks).
- The **full quant gate was not re-run this session**; baseline from session
  133 is 1505 passed. Only the affected file and its direct dependents were
  re-run (all green). If a full gate is desired, expect ≈44 min with `-n 4`
  and revert only `examples/example_reproducible_output/` if dirtied.
- `pytest-xdist` is still not pinned in `requirements.txt` (needs explicit
  user confirmation); the test env used this session was `/tmp/venv`.
- Real-market sweep tests that pass an explicit `--benchmark` now exercise the
  unavailable-criterion path but do not assert it.

## Do not repeat
- Do NOT re-run the full gate *hoping* the example runtime changes; the
  deterministic runtime cause was fixed in session 133 (8.25s).
- Do NOT hard-code a single benchmark in the sweep again.
- Do NOT let an unavailable criterion count as a pass to "simplify" reporting.
- Do NOT tune parameters/costs/verdicts to force SUPPORT.

## One precise next task (evidence-based)
The CLI's JSON artifact never contains the cost sweep: `main()` whitelists a
`cost_sweep` key (`examples/falsifiable_hypothesis_example.py:1180,1223`) but
no result ever sets it (`grep -n cost_sweep` shows only the whitelist and the
`--no-cost-sweep` flag). So the durable artifact omits the sensitivity
analysis entirely.
1. Capture the rows returned by `run_cost_sensitivity_sweep(...)` in both CLI
   branches (`--fetch-real` and the sample branch) and write them under
   `cost_sweep` in the JSON (rows already carry `n_benchmarks` and
   `deflated_alpha_ratio_evaluable`).
2. Add a regression in `tests/test_falsifiable_hypothesis_example.py` that
   runs the CLI with `--output-json` into a tmp dir and asserts
   `cost_sweep` has one entry per `COST_SWEEP_LEVELS` with
   `n_benchmarks >= 2` and finite `deflated_alpha_ratio` (and that the
   single-benchmark override writes `evaluable: false` rows).
3. Re-run `tests/test_falsifiable_hypothesis_example.py` (36 → 37 tests) and
   revert only `examples/example_reproducible_output/` if a broader run
   dirties it.
