# Next Session Task — Fix out-of-sample CSV capacity bug

## Task
Fix the bug in `run_out_of_sample_validation()` where `--output-format csv` fails because it tries to call `.get()` on a float capacity value instead of a dict. The fix should use `capacity_detail` dict from the summary (like `run_monte_carlo` and `run_parameter_optimization` do).

## Evidence / where to look
- Bug location: `skills/quantitative-backtesting/scripts/walk_forward.py` line 12571-12578
- The `test_performance.capacity` in the JSON is a float (scalar `estimated_capacity`), but the CSV code treats it as a dict with `.get()`
- Correct pattern: Use `summary.get("capacity_detail")` which is a dict with keys: `impact_capacity`, `participation_capacity`, `cost_adjusted_capacity`, `cost_drag`, `holding_period_years`
- Reference implementations:
  - `run_monte_carlo` line 11905-11915: `cap = mc_results["summary"].get("capacity_detail") or {}`
  - `run_parameter_optimization` line 10967-10979: `cap = top_result.get("capacity_detail") or {}`

## Constraints
- Committed fixtures only, no network
- Minimal fix: change the CSV emission block to read from `capacity_detail` dict
- Verify with: `python3 -m pytest skills/quantitative-backtesting/tests/test_walk_forward.py::test_cli_walk_forward_output_format_csv_writes_capacity_rows` (add OOS test if needed)
- Do not modify engine math; keep changes additive and reversible

## Expected fix
```python
# Current (broken):
cap = (summary_data.get("test_performance") or {}).get("capacity") or {}
# Fixed:
cap = summary_data.get("summary", {}).get("capacity_detail") or {}
```