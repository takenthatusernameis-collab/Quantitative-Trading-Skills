# Handoff — Session 173 — `--max-impact` was silently ignored by `optimize` and `monte-carlo`

## Prior assignment executed
`HANDOFF_SESSION_172.md` / `HANDOFF_SESSION_CURRENT.md` pointed at wiring the PIT
`lookahead_warning_threshold` band into the walk-forward path. Verified that is
ALREADY DONE in the committed tree: all 8 `validate_point_in_time(...)` call sites in
`skills/quantitative-backtesting/scripts/walk_forward.py` forward
`lookahead_warning_threshold`, the CLI flag exists, and
`tests/test_walk_forward_pit_warning_zone_wiring.py` exists and passes (2/2).
Baseline re-verified green: `test_walk_forward.py` 254/254, `test_run_backtest.py`
132/132, both PIT wiring tests 5/5. So I selected a NEW bounded task from direct
code evidence.

## What changed (this session)
`--max-impact` (capacity-aware per-trade position cap) is declared on the shared
`common_parser`, so ALL five subcommands accept it. But only `out-of-sample`
forwarded it into returns/selection. The `optimize` and `monte-carlo` subcommands
SILENTLY IGNORED it — a researcher setting `--max-impact` got an uncapped backtest
while believing the cap applied (the exact "silent methodological no-op" class the
`--max-*-costs` fail-fast guard was added to prevent).

Fix (production, default `None` => byte-identical; `skills/.../scripts/walk_forward.py`):
1. `run_parameter_optimization` `parameter_optimization(...)` call (~10933): added
   `max_impact=getattr(args, "max_impact", None)`.
2. `_monte_carlo_sweep_coefficient(...)`: new `max_impact: Optional[float] = None`
   param, resolved from `args` when None; forwarded into BOTH its
   `parameter_optimization(...)` (selection) and `_calculate_strategy_returns(...)`
   (final returns) calls.
3. `run_monte_carlo` single-run: forwarded `max_impact=getattr(args, "max_impact",
   None)` into its `parameter_optimization(...)` and `_calculate_strategy_returns(...)`
   calls.
Net diff: 12 insertions / 4 deletions in walk_forward.py (5 forwarding sites +
signature + resolution). No other production file touched.

Tests (`skills/.../tests/test_walk_forward.py`, +2 tests, both registered in
`TEST_REGISTRY`):
- `test_cli_monte_carlo_max_impact_binds_returns`: binding `--max-impact 0.00001`
  changes the monte-carlo return distribution; non-binding `--max-impact 1000000`
  leaves it byte-identical to no-cap (default-path invariance).
- `test_cli_optimize_max_impact_affects_selection`: binding cap changes the
  optimize top-ranked parameter set vs uncapped.

## What was actually verified (evidence)
- Reproduction BEFORE fix: `monte-carlo` with/without `--max-impact 0.00001`
  produced byte-identical `total_return`/`sharpe` (blind spot confirmed).
- AFTER fix: capped run differs (total_return mean -0.0376 -> -0.0040).
- Genuine-guard proof: `git checkout -- scripts/walk_forward.py` (revert fix) ->
  BOTH new tests FAIL ("cap was silently ignored"; "both runs selected
  (('fast_period', 8), ('slow_period', 20))"); restored fix byte-for-byte
  (`git diff --stat` = 12/-4).
- Full `python3 tests/test_walk_forward.py` -> 256 passed (was 254; +2 new).
- New tests + registry guard (`test_main_registers_every_module_level_test`) -> 3/3.
- `git status`: only `scripts/walk_forward.py` (M) + `tests/test_walk_forward.py`
  (M). Nothing committed (not asked). No data/fixtures/hashes/catalog touched.

## Unresolved (pre-existing, unchanged)
- DATA PROVENANCE (blocked offline): committed `real_market_data` CSVs are
  synthetic/placeholder; `_real_*` tests only check the committed manifest. Do NOT
  fabricate/edit pinned hashes.
- The `--max-impact` cap is a soft position scaler; sub-threshold impact still
  applies (documented). Monte-carlo per-run `summary` does not echo the selected
  params under a `selected_params` key (selection is internal) — the new test
  discriminates on the return distribution / top-ranked params instead.
- `_monte_carlo_sweep_coefficient` still does not forward `max_participation_rate`
  into its internal `parameter_optimization` call (pre-existing, out of scope).

## Approaches that already failed (do not repeat)
- `background_process` runs in a separate FS namespace where the repo is NOT
  visible — run tests foreground with the bash tool `timeout` raised (the tool's
  own 120s default cut off `test_walk_forward.py`; set timeout >= 900000 ms).
- Running all ~330 test files in one pytest call (>50 min, killed) — chunk per file.
- Asserting capped-vs-uncapped `test_total_return` does NOT guard the cpcv
  `max_impact` forward (val/test calls forward it independently) — see
  HANDOFF_SESSION_NEXT.md; use `selected_params`/return-distribution instead.
- Do NOT re-attempt offline data-provenance restoration (blocked; do not fabricate).

## One precise next task (bounded, evidence-based)
The `optimize`/`monte-carlo` `max_impact` blind spot is fixed. The SAME class of
gap may exist for `max_participation_rate`: `_monte_carlo_sweep_coefficient`
resolves `max_participation_rate` from args but does NOT forward it into its
internal `parameter_optimization(...)` call (only into `estimate_capacity`). Verify
and, if confirmed, fix + pin:
1. Test FIRST: run `walk_forward monte-carlo` (or `optimize`) on a synthetic frame
   with/without a binding `--max-participation-rate` and assert reported
   capacity/returns are currently IDENTICAL (proves the blind spot). Register it.
2. Forward `max_participation_rate=max_participation_rate` into the
   `parameter_optimization(...)` call in `_monte_carlo_sweep_coefficient`
   (~line 11243) and, if missing, `run_monte_carlo` (~11732). Default None must
   leave every published number byte-identical.
3. Flip the test to assert the cap changes the result; keep default-path invariance.
4. Verify: new test + `python3 tests/test_walk_forward.py` (expect 257/257) +
   genuine-guard revert proof. Scope to `walk_forward.py` + `test_walk_forward.py`;
   do NOT touch data/fixtures/hashes/catalog. Do NOT commit unless asked.