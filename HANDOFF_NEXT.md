# Handoff — machinery separation audit verified on longer windows

## What changed
- No code changes needed; verified `test_real_market_machinery_separation_audit_longer_windows` passes (84s) using committed real-market fixtures with offline guards.

## What was actually verified
- Separation invariants (disjoint, chronological, zero overlaps) hold for GOOGL, MSFT, AAPL pairs plus single-asset AAPL.
- pit_passed and bias_controls_engaged true for all.

## What remains unresolved
- Live Yahoo fetch remains rate-limited; offline mock guards cover contract.

## One precise next task
- Add a concrete falsifiable hypothesis test on a longer real-data window (e.g., MSFT vs GOOGL over full committed series) verifying verdict stability under cost sensitivity.
