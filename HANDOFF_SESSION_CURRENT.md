# Handoff — CURRENT — see HANDOFF_SESSION_171.md

Latest session (171) wired the PIT `lookahead_warning_threshold` warning band into
`run_backtest.py` (CLI flag + `_validate_point_in_time` forwarding + narrowed
warning filter) and added `tests/test_run_backtest_pit_warning_zone_wiring.py`.
Baseline green (run_backtest 132/132, data_loader 56/56, PIT strict OK). Nothing
committed.

Read `HANDOFF_SESSION_171.md` for full evidence, the genuine-guard proof, and the
one precise next task (wire the same band into the walk-forward path's 8
`validate_point_in_time` call sites; default None byte-identical).