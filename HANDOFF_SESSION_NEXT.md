# Handoff — session (2026-11-17): extended PIT/survivorship controls to out-of-sample validation

## Baseline (committed, green)
- HEAD `f417a91` (session 131): full quant gate green `1491 passed, 0 failed, EXIT 0` (1973 s at `-n 4`). Working tree clean at session start.
- TSMOM walk-forward subset confirmed green: `23 passed in 4.11s` (session 132).

## What changed (bounded, verifiable)
- **Modified** `skills/quantitative-backtesting/scripts/walk_forward.py`:
  - Added `survivorship: Optional[Dict[str, Any]] = None` parameter to `out_of_sample_validation()` function signature.
  - Added automatic survivorship bias detection for multi-asset panels (MultiIndex columns) when `survivorship=None`. Mirrors the walk-forward / CPCV paths: converts panel to dict and runs `detect_survivorship_bias()`.
  - Updated docstring to document the new parameter.
  - Updated early-return path (no parameters selected) to include `point_in_time_validation`, `survivorship_bias`, and `bias_controls_engaged` in results and summary.
  - Updated `bias_controls_engaged` in summary to `bool(pit_results is not None or survivorship is not None)` (was `bool(pit_results is not None)`).
  - Added `survivorship_bias` to the returned results dictionary.
  - Updated `_oos_sweep_coefficient()` helper to pass `survivorship` through to `out_of_sample_validation()`.
  - Updated CLI `run_out_of_sample_validation()` to pass `survivorship` (loaded from `_load_and_validate_data`) to `out_of_sample_validation()`.
  - Updated CLI summary artifact to include `survivorship_bias` in config, set `bias_controls_engaged` correctly, and persist `survivorship_bias.json` artifact for multi-symbol panels (mirrors `run_walk_forward` / `run_backtest`).

## What was actually verified (evidence)
| Check | Result |
|-------|--------|
| Out-of-sample TSMOM test (triple panel) | `pytest test_out_of_sample_time_series_momentum_real_triple_aapl_msft_googl.py -q` -> **1 passed (0.68s)** |
| Multi-symbol PIT/survivorship test | `pytest test_multi_symbol_pit_survivorship_real_panel.py -q` -> **3 passed (4.61s)** |
| Survivorship bias positive control | `pytest test_survivorship_bias_insufficient_and_gaps_real_panel.py -q` -> **1 passed (1.51s)** |
| PIT strict tests | `pytest test_point_in_time_strict_abort_on_violation.py test_point_in_time_strict_cli_walk_forward.py -q` -> **10 passed (5.39s)** |
| TSMOM walk-forward subset | `pytest -k "time_series_momentum" -n 4 -q` -> **23 passed (4.11s)** |
| All out-of-sample tests | `pytest test_out_of_sample*.py -q` -> **16 passed (6.38s)** |
| All walk_forward CLI tests | `pytest test_walk_forward.py -q` -> **207 passed (289s)** |
| All CPCV tests | `pytest test_cpcv.py -q` -> **30 passed (56s)** |
| Manual verification: survivorship_bias in result | `survivorship_bias` key present with full detection report, `bias_controls_engaged: True` |
| Manual verification: corrupted panel detection | `insufficient_data` correctly flagged, `bias_score: 1.0`, early-return path includes survivorship |

## What remains unresolved
- Full quant gate NOT re-run after this additive change (session 131's 1491-passed gate predates it). Recommended: run the full gate `python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4` (~33 min at `-n 4`; do not run as a blocking in-session command — use background/poll or defer to CI per session 131).
- `pytest-xdist` still not pinned in `skills/quantitative-backtesting/requirements.txt` (session 131 note); `-n 4` not reproducible from a clean env. Dependency edit requires explicit user confirmation.
- No profitability/capacity claim made or supported; this is methodological control extension only.

## Approaches already tried / failed (do not repeat unchanged)
- None new this session. The survivorship detection machinery already existed in `detect_survivorship_bias()` and was wired in walk-forward / CPCV / run_backtest CLI paths; the gap was the out-of-sample validation framework, now filled.

## One precise next task
Run the full quant gate to confirm green after this change:
`python3 -m pytest skills/quantitative-backtesting/tests/ -p no:cacheprovider -q -n 4`
Then pick the next bounded methodological gap per the AGENTS.md quant mission (e.g. genuinely out-of-sample falsification net of plausible costs, or extend PIT/survivorship controls further). Do NOT add another strategy falsification test, do NOT claim profitability/capacity, do NOT tune parameters/costs/verdicts to force SUPPORT. Offline committed fixtures only; preserve marketplace compatibility; do not commit unless explicitly asked.

(End of file - total 44 lines)
