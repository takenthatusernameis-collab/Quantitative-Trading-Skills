# Handoff — CURRENT — see HANDOFF_SESSION_173.md

Latest session (173) fixed a silent methodological no-op: `--max-impact` was
accepted by the `optimize` and `monte-carlo` subcommands but never forwarded into
returns/selection, so a researcher setting it got an uncapped backtest. Fix in
`skills/quantitative-backtesting/scripts/walk_forward.py` (default None
byte-identical) + 2 registered regression tests. Baseline green: test_walk_forward
256/256, genuine-guard revert proof done. Nothing committed.

Read `HANDOFF_SESSION_173.md` for full evidence and the one precise next task
(audit/forward `max_participation_rate` into the monte-carlo `parameter_optimization`
call, which is resolved but not forwarded).