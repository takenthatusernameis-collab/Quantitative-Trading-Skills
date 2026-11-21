# Handoff — Next Task: Verify Kelly/volatility targeting CPCV partial selection diagnosis

Check test_cpcv_kelly_criterion_real_aapl.py and test_cpcv_volatility_targeting_real_aapl.py (both expect folds_with_position=4, lookback=63). Verify their partial_selection_diagnosis assertions match the completeness of test_cpcv_dual_momentum_real_aapl_googl_structure.py which explicitly asserts:
- partial["cause"] == "no_position_in_validation_window"
- summary["no_selection_diagnosis"] is None