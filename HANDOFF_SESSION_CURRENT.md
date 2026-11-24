# Handoff — Session (current): holm_stepdown wired into time-series momentum protocol-sensitivity test

## Status entering this session
- HEAD `f6046c0` (main); working tree clean at start.
- Prior session (committed in `5bb8a7f`) wired `holm_stepdown` into the
  cross-sectional momentum protocol-sensitivity test; `utils.holm_stepdown`
  (`scripts/utils.py:2345`) and `tests/test_holm_stepdown.py` (12 tests) are committed.
- Environment: system `python3` 3.14.4 with pinned requirements; no venv needed.
- Full regression gate baseline: **1759 passed, 0 failed** (Session CURRENT).

## Assigned task (from prior handoff)
"Wire `holm_stepdown` into the time-series momentum protocol-sensitivity test
(`test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py`)
for consistency" — i.e. give `holm_stepdown` a second production consumer without
disturbing pinned matrices.

## What changed this session
- **One additive source change** (no engine/fixture/pinned-matrix/default-JSON change):
  - `skills/quantitative-backtesting/tests/test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py`
    - Import: `from utils import bonferroni_correction, holm_stepdown`.
    - In `test_sole_pass_does_not_survive_protocol_multiplicity`, after the existing
      Bonferroni `n_rejected == 0` block, added a companion Holm block: the
      Holm-adjusted p-value for the sole-pass (30,12,12) MSFT cell must exceed
      `DSR_PVALUE_THRESHOLD` (0.10) and Holm `n_rejected` must be 0.
  - Existing Bonferroni assertions and the pinned `EXPECTED` matrix left byte-identical.
    No new test function registered (TEST_REGISTRY unchanged). Diff: +15/-1, one file.

## What was actually verified (evidence)
- `python3 -m py_compile` on the edited file → `COMPILE_OK`.
- `pytest tests/test_holm_stepdown.py tests/test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py -p no:cacheprovider -q`
  → **17 passed** (12 Holm unit + 5 time-series protocol-sensitivity), 17.60s, exit 0.
- `git status --short`: only the one intended file modified; `git diff --stat` = 1 file, +15/-1.
- `git diff` confirms no `EXPECTED`/matrix line changed.
- Rationale the assertion holds: Holm dominates Bonferroni under arbitrary dependence,
  so if the Bonferroni-adjusted sole-pass p already exceeds 0.10 (existing assertion),
  the Holm-adjusted value must too; and Holm rejection set ⊆ Bonferroni rejection set,
  so `n_rejected == 0` is preserved.

## What remains unresolved
- `holm_stepdown` now has two consumers (cross-sectional + time-series triple tests) but
  is still not applied uniformly across all protocol-sensitivity families.
- Nothing committed (standing rule: no commit unless explicitly asked).

## Approaches already tried / failed
- None failed. Green first try.

## One precise next task (bounded, evidence-based)
Extend the same non-breaking Holm companion assertion to the remaining **triple**
protocol-sensitivity tests that currently use only `bonferroni_correction`
(verified via grep, 0 `holm_stepdown` occurrences):
- `tests/test_walk_forward_dual_momentum_protocol_sensitivity_real_triple_aapl_msft_googl.py`
- `tests/test_walk_forward_sma_crossover_protocol_sensitivity_real_triple_aapl_msft_googl.py`
- `tests/test_walk_forward_rsi_mean_reversion_protocol_sensitivity_real_triple_aapl_msft_googl.py`
For each: add `holm_stepdown` to the `from utils import ...` line and, immediately
after the existing Bonferroni multiplicity assertion, add a companion Holm assertion
(best/sole-pass adjusted p > threshold and `n_rejected == 0`). Keep every existing
assertion and pinned `EXPECTED`/summary matrix byte-identical; only ADD assertions.
- **Constraints**: offline/committed fixtures only; do not renumber metrics, change
  default JSON, or modify the engine; do not commit unless explicitly asked.
- **Verify**: run the three edited files plus `tests/test_holm_stepdown.py` focused
  (~a few minutes) and report exact pass/fail counts. A full 1759-gate rerun is the
  correct final check before any commit, not required for the additive change itself.
- Alternative higher-value task if consistency wiring is deprioritized: build a shared
  aggregate-reporting layer that applies FWER/FDR once across a protocol family
  (currently each test file corrects ad hoc) — larger scope, needs its own design.