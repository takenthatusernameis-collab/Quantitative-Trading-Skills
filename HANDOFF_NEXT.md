# HANDOFF_NEXT

## Next task: give the `run_backtest.py` path its test resolution too (and
## print the aggregate Deflated Alpha the resolution belongs to)

### Why

The previous session's commit `ed044d4` (HEAD) changed the import in
`skills/quantitative-backtesting/scripts/run_backtest.py` to

```python
from walk_forward import estimate_capacity, deflated_sharpe_ratio, minimum_detectable_sharpe
```

and **never used either new name**. `run_backtest.py:1279` reads the
statistic out of the metrics dict instead:

```python
    dsr = metrics.get("deflated_sharpe")
    if dsr is not None:
        print(
            f"Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )
```

So the framework's **primary backtest entry point** prints a Deflated Sharpe
Ratio with a p-value and no statement of what that test could have detected at
all -- the exact defect that was just fixed in the walk-forward, CPCV and
out-of-sample paths. The dangling import is the evidence that the wiring was
intended and never finished.

The same gap exists for the Deflated Alpha Ratio in all three analysis CLIs:
they now print the alpha **resolution** ("smallest confirmable annualized
alpha 35.68%") but never the statistic the resolution belongs to (the
aggregate DAR and its p-value), even though `summary["deflated_alpha"]`
carries it. The per-benchmark corrected alpha p-value that *is* printed is a
different statistic from the canonical aggregate DAR.

### Scope

1. **`run_backtest.py`**: when `metrics["deflated_sharpe"]` is present (the
   `--n-trials` path), compute the resolution with
   `walk_forward.minimum_detectable_sharpe(dsr, returns)` and print it with
   the same wording the three analysis paths use. The return series is the
   strategy's own return series over the whole run -- find where the metrics
   and the returns are computed (`_calculate_strategy_returns` /
   `performance.calculate_metrics` and the `results` dict the CLI holds) and
   make sure the series passed to the helper has the **same length** as
   `dsr["n_observations"]`, otherwise the helper returns
   `returns_do_not_match_statistic` and the block reports "not resolvable".
   That check is the whole difficulty of this task: the resolution must be the
   resolution of *that* statistic, not of some other series.
   - Report it in the artifact too (`metrics.json` / the metrics dict), under
     a key of the same name the analysis paths use (`test_resolution`), so a
     reader of `metrics.json` sees it.
   - The DSR that `calculate_metrics` builds is computed on the `returns`
     argument it receives (`performance.py:645`, with
     `n_observations = len(returns.dropna())`); reuse *that* series, not a
     re-derived one.
2. **The three analysis CLIs**: print the aggregate Deflated Alpha Ratio
   (`summary["deflated_alpha"]`: `deflated_alpha_ratio`, `p_value`,
   `expected_max_alpha`, `n_benchmarks`) next to the alpha resolution, in
   `run_walk_forward`, `run_cpcv` and `run_out_of_sample_validation`.
3. Remove the unused import (or use it). After the change,
   `deflated_sharpe_ratio` and `minimum_detectable_sharpe` must both be used
   or both be gone -- an unused import is a lint failure in most projects and
   is exactly what made this gap invisible.

### Constraints

- **No reported number may move.** The resolution is reporting-only, exactly
  as in the three paths fixed this session: no p-value, no verdict, no
  Sharpe / alpha / return changes. The Deflated Alpha line you add to the
  CLIs must print numbers that are already in `summary["deflated_alpha"]`.
- The artifact shape changes (a new key in the `run_backtest` metrics and
  new console lines). The parity harness from the last session lived in a
  temporary directory and is gone -- rebuild it before claiming parity, or
  state explicitly that the shape change is intentional and list every key
  added. The harness recipe is in `HANDOFF.md` ("What was verified").
- Reuse `walk_forward._build_test_resolution` and
  `walk_forward._print_test_resolution` rather than re-implementing them.
  `_build_test_resolution` takes `(summary, returns)` and reads
  `summary["deflated_sharpe"]` / `summary["deflated_alpha"]`, so the
  `run_backtest` path can use it directly if it puts the statistic under one
  of those keys in a summary-shaped dict.
- Do not re-threshold anything and do not change a verdict.

### Evidence to inspect first

- `skills/quantitative-backtesting/scripts/run_backtest.py:50` (the dangling
  import) and `:1279-1285` (the Deflated Sharpe print with no resolution).
- `skills/quantitative-backtesting/scripts/walk_forward.py` --
  `_build_test_resolution`, `_print_test_resolution`,
  `PLAUSIBLE_MAX_ANNUALIZED_SHARPE` / `PLAUSIBLE_MAX_ANNUALIZED_ALPHA`,
  and the three wiring points (`walk_forward_analysis`, `cpcv_analysis`,
  `out_of_sample_validation`) as the reference implementation.
- `skills/quantitative-backtesting/scripts/performance.py` --
  `calculate_metrics`, where `metrics["deflated_sharpe"]` is built and from
  which return series.
- `skills/quantitative-backtesting/tests/test_test_resolution.py` -- the
  test file written for the three paths; extend it rather than starting
  again.
- `skills/quantitative-backtesting/references/validation_methods.md`,
  "The framework's own verdicts report their resolution".

### Definition of done

- The `run_backtest.py` CLI prints the resolution next to its Deflated Sharpe
  Ratio, and the artifact carries the same numbers.
- The three analysis CLIs print the aggregate Deflated Alpha Ratio next to
  the alpha resolution.
- Tests added and passing; the full `skills/quantitative-backtesting` suite
  green (except the pre-existing `test_reporting.py` failures, which are
  caused by `matplotlib` missing in this container -- 9 failures at HEAD,
  identical with and without changes).
- Evidence documented (what changed, verified, unresolved).
- No change to any reported number outside the new reporting-only keys.

### The task after this one

Two candidates, in order of value:

1. **A positive control for the falsifiable-hypothesis machinery.** The
   resolution analysis shows analytically that the criteria need an annualized
   Sharpe of ~4.2 at T=100, but nothing has yet *executed* the same machinery
   against a series with a known effect to show the criteria can be met. Build
   one: a synthetic series with a deliberately injected regime structure (so
   an SMA crossover can beat buy-and-hold net of costs), long enough that T
   is large enough for the deflated thresholds to be reachable, and assert that
   the example's criteria evaluation returns SUPPORTED. Label it unmistakably
   as a test-machinery check on synthetic data, never as evidence about a
   market.
2. **The `test_n_periods` naming defect.** The framework's key counts test
   *observations* while claiming to count *periods*. Renaming it (or adding an
   alias) changes the artifact shape, so it needs a session that can also
   rebuild the parity harnesses.
