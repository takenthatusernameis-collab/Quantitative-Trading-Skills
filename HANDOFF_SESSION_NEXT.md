# Handoff — OOS regime-impact wiring + guard done; next: --max-impact on OOS

## Prior session (complete, uncommitted)
Out-of-sample CLI path dropped `--regime-impact-coefficients` /
`--regime-cost-multipliers`. Fixed `run_out_of_sample_validation` (parse +
forward both into the single-run call) and `_oos_sweep_coefficient` (new
`regime_impact_coefficients` param + forward). Added genuine regression guard
`test_cli_oos_summary_regime_impact_coefficients_reflected_in_capacity`
(fails without the fix: flat==regime 581632.45; passes with it: flat 581632.45
> regime 370715.67). Full suite **251/251 passed**. Default path byte-identical.
Only `scripts/walk_forward.py` + `tests/test_walk_forward.py` modified; NOT
committed. See HANDOFF_SESSION_CURRENT.md for full evidence.

## One precise next task (bounded, evidence-based)
Make `--max-impact` real (or loudly rejected) on the out-of-sample path.
`out_of_sample_validation` accepts `max_impact` (walk_forward.py:7007) but never
uses it in its body (6967–8018), and `run_out_of_sample_validation` doesn't
forward it — so `--max-impact` is a silent no-op for OOS (it IS implemented in
run_backtest / walk_forward_analysis / cpcv_analysis).

1. Test FIRST: run `walk_forward out-of-sample` twice at `--impact-coefficient
   0.5`, once with `--max-impact 0.0005` and once without; assert
   `out_of_sample_summary.json` `summary.capacity` is currently IDENTICAL
   (proves the blind spot). Register it.
2. Fix: thread `max_impact` from the handler (~:12375) into
   `out_of_sample_validation`, then into its internal `walk_forward_analysis` /
   `cpcv_analysis` validation sub-calls (~:7262, :7296) and val/test
   `run_backtest` calls (~:7416, :7530). Default `None` → byte-identical.
   If threading is non-trivial, minimal safe alternative: reject `--max-impact`
   on the `out-of-sample` subcommand loudly (mirror the cap-sweep rejection at
   ~:12990) and pin that.
3. Flip test to assert a difference when `--max-impact` binds; keep default-path
   invariance. Verify full `test_walk_forward.py` (expect 252/252).

Constraints: scope to `walk_forward.py` + `test_walk_forward.py`; do NOT touch
the inherited marketplace catalog or pinned data hashes; `pytest` absent (run
`python3 <file>`); do NOT commit unless explicitly asked. Do NOT re-attempt the
offline data-provenance restoration (blocked; do not fabricate).