#!/usr/bin/env python3
"""First-principles reproducibility + binding check for the walk-forward
Deflated Sharpe Ratio (DSR) on the committed triple panel (AAPL/MSFT/GOOGL).

The honest verdict in
``test_walk_forward_zscore_triple_real_aapl_msft_googl.py`` hinges entirely on
one number: the Deflated Sharpe p-value (0.9534) being far above the 0.10
falsification threshold, so the strategy is reported NOT SUPPORTED. That test
only asserts the *value* is above threshold; it does not prove the value is
*correctly computed*. This test closes that gap the way
``test_factor_attribution_reproducibility.py`` does for factor attribution:

1. Run the exact same walk-forward configuration on committed fixtures only.
2. Reconstruct the DSR inputs (per-period out-of-sample returns, the grid-search
   trial Sharpes, the trial count) from the returned result object.
3. Recompute the Deflated Sharpe Ratio from the Bailey & Lopez de Prado (2014)
   formula *from first principles*, using ``scipy.stats.norm.cdf`` as an
   independent normal CDF (the engine uses ``math.erf``). No engine DSR
   function is called.
4. Assert the independent recompute reproduces every reported field
   (``z_score``, ``deflated_sharpe_ratio``, ``p_value``,
   ``expected_max_sharpe``) to a tight tolerance.
5. Prove the multiplicity guard *binds* rather than merely passes:
   - the expected maximum Sharpe from luck alone (from the trial dispersion)
     exceeds the observed out-of-sample Sharpe, so the strategy is deflated to
     near-zero confidence;
   - the trial-dispersion estimator of SR* is strictly more conservative
     (larger) than the i.i.d.-normal null, confirming the trial Sharpes are
     genuinely consumed and not silently ignored;
   - the resulting p-value is far above 0.10, so no cell flips to SUPPORTED.

Offline, committed fixtures only; no live network; no engine/fixture/test
mutation. Direct ``python3`` runnable (pytest is not required).
"""

import contextlib
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from utils import _annualization_factor  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Same pre-registered grid as the guarded test (period=20, entry_z=2.0,
# exit_z=0.5), fixed before any result is inspected.
PARAM_GRID = {
    "period": [20],
    "entry_z": [2.0],
    "exit_z": [0.5],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12

DSR_PVALUE_THRESHOLD = 0.10

# Relative tolerance for the independent recompute vs. the engine's reported
# values. The two use different normal-CDF implementations (scipy vs. math.erf)
# and different summation orders, so exact bit equality is not expected; 1e-9
# is far tighter than any decision threshold while comfortably above float noise.
REL_TOL = 1e-9


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        panel[Path(name).stem] = df
    return panel


def _factory(params):
    return build_strategy("multi_pair_zscore_mean_reversion", json.dumps(params))


def _run_walk_forward():
    return walk_forward_analysis(
        data=_build_panel(),
        strategy_factory=_factory,
        param_grid=PARAM_GRID,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        panel_pricing="book",
        apply_deflation=True,
        validate_pit=True,
    )


def _reconstruct_dsr_inputs(result):
    """Pull the exact inputs the engine feeds into ``deflated_sharpe_ratio``
    out of the returned result object, without recomputing them.

    The engine (walk_forward.py) builds ``all_trial_sharpes`` by extending each
    period's ``trial_sharpes`` (the in-sample training Sharpes of every grid
    combination that took a position), and sets ``n_trials =
    max(total_evaluated_trials, 1)`` where ``total_evaluated_trials`` is the
    count of those trial Sharpes. ``oos_returns`` is the concatenation of each
    period's selected out-of-sample test returns.
    """
    oos_returns = result["oos_returns"]
    periods = result["periods"]
    trial_sharpes = []
    for p in periods:
        # walk_forward stores the per-period grid-search Sharpes under
        # "trial_sharpes"; tolerate the singular alias defensively.
        ts = p.get("trial_sharpes")
        if ts is None:
            ts = p.get("trial_sharpe", [])
        trial_sharpes.extend(float(s) for s in ts)
    n_trials = max(len(trial_sharpes), 1)
    return oos_returns, trial_sharpes, n_trials


def _independent_dsr(sharpe_ratio_ann, returns, trial_sharpes, n_trials):
    """Recompute the Deflated Sharpe Ratio from first principles.

    Mirrors Bailey & Lopez de Prado (2014). All internal Sharpe quantities are
    in per-period units; ``sharpe_ratio_ann`` is the annualized Sharpe the
    engine reports.

        DSR = Phi( (SR_hat - SR*) * sqrt(T - 1)
                    / sqrt(1 - gamma3 * SR_hat + ((gamma4 - 1) / 4) * SR_hat^2) )

    where SR* (per-period) is estimated from the cross-sectional dispersion of
    the trial Sharpes when at least two are available
    (SR* = std(SR_trials) * sqrt(2 * ln(N))), otherwise from the i.i.d.-normal
    null (SR* = sqrt(2 * ln(N) / T)). gamma3 is skewness and gamma4 is
    (non-excess) kurtosis. Phi is the standard normal CDF, computed here with
    ``scipy.stats.norm.cdf`` (the engine uses ``math.erf``).
    """
    ann_factor = _annualization_factor(returns.index)
    t_obs = len(returns)
    sr = float(sharpe_ratio_ann) / math.sqrt(ann_factor)
    ln_trials = math.log(max(int(n_trials), 1))

    # Expected maximum Sharpe under the null (per-period units).
    sr_star = None
    sr_star_iid = math.sqrt(2.0 * ln_trials / t_obs)
    if trial_sharpes is not None and len(trial_sharpes) >= 2:
        trial_sr = np.asarray(trial_sharpes, dtype=float) / math.sqrt(ann_factor)
        trial_std = float(np.std(trial_sr, ddof=1))
        if trial_std > 0 and np.isfinite(trial_std):
            sr_star = trial_std * math.sqrt(2.0 * ln_trials)
    used_trial_dispersion = sr_star is not None
    if sr_star is None:
        sr_star = sr_star_iid

    skew = float(returns.skew())
    kurt = float(returns.kurtosis()) + 3.0  # pandas reports excess kurtosis
    if not np.isfinite(skew):
        skew = 0.0
    if not np.isfinite(kurt):
        kurt = 3.0

    variance_term = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if not np.isfinite(variance_term) or variance_term <= 0.0:
        variance_term = np.finfo(float).tiny
    denom = math.sqrt(variance_term)

    vol = float(returns.std())
    if returns.nunique(dropna=False) == 1 or vol <= 0:
        z = -math.inf
    else:
        z = (sr - sr_star) * math.sqrt(t_obs - 1) / denom

    dsr = float(norm.cdf(z))
    dsr = min(max(dsr, 0.0), 1.0)
    return {
        "z_score": z,
        "deflated_sharpe_ratio": dsr,
        "p_value": 1.0 - dsr,
        "expected_max_sharpe_ann": sr_star * math.sqrt(ann_factor),
        "sr_star_per_period": sr_star,
        "sr_star_iid_per_period": sr_star_iid,
        "used_trial_dispersion": used_trial_dispersion,
        "sharpe_per_period": sr,
        "ann_factor": ann_factor,
        "skewness": skew,
        "kurtosis": kurt,
        "n_trials": int(n_trials),
        "n_observations": int(t_obs),
    }


def test_dsr_recompute_matches_engine():
    """The independent first-principles recompute must reproduce the engine's
    reported DSR fields to a tight tolerance. This proves the value the honest
    verdict hinges on is computed correctly, not merely above threshold.
    """
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    summary = result["summary"]
    reported = summary["deflated_sharpe"]
    assert reported is not None, "walk-forward summary carries no deflated_sharpe"

    oos_returns, trial_sharpes, n_trials = _reconstruct_dsr_inputs(result)
    assert n_trials >= 1
    assert len(oos_returns) > 1

    indep = _independent_dsr(summary["oos_sharpe"], oos_returns, trial_sharpes, n_trials)

    # z_score, DSR, p_value, expected_max_sharpe must all reproduce.
    def _close(a, b):
        return abs(a - b) <= REL_TOL * max(abs(b), 1e-9)

    assert _close(indep["z_score"], reported["z_score"]), (
        indep["z_score"], reported["z_score"]
    )
    assert _close(
        indep["deflated_sharpe_ratio"], reported["deflated_sharpe_ratio"]
    ), (indep["deflated_sharpe_ratio"], reported["deflated_sharpe_ratio"])
    assert _close(indep["p_value"], reported["p_value"]), (
        indep["p_value"], reported["p_value"]
    )
    assert _close(
        indep["expected_max_sharpe_ann"], reported["expected_max_sharpe"]
    ), (indep["expected_max_sharpe_ann"], reported["expected_max_sharpe"])
    # The trial count and observation count must also agree.
    assert indep["n_trials"] == reported["n_trials"]
    assert indep["n_observations"] == reported["n_observations"]
    # Skew/kurtosis are reported by the engine too; confirm they agree.
    assert _close(indep["skewness"], reported["skewness"])
    assert _close(indep["kurtosis"], reported["kurtosis"])


def test_dsr_guard_binds_not_merely_passes():
    """The multiplicity control must *bind*: the expected maximum Sharpe from
    luck must exceed the observed Sharpe, the trial-dispersion estimator must
    be the one actually used and must be more conservative than the i.i.d.
    null, and the resulting p-value must sit far above the 0.10 threshold so
    the verdict stays NOT SUPPORTED.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    summary = result["summary"]
    oos_returns, trial_sharpes, n_trials = _reconstruct_dsr_inputs(result)
    indep = _independent_dsr(summary["oos_sharpe"], oos_returns, trial_sharpes, n_trials)

    # 1) The engine used the trial-dispersion estimator (more than one trial
    #    Sharpe was available), so the grid search genuinely drives SR*.
    assert len(trial_sharpes) >= 2
    assert indep["used_trial_dispersion"] is True

    # 2) The trial-dispersion SR* is strictly more conservative (larger) than
    #    the i.i.d.-normal null -- confirming the trial Sharpes are consumed,
    #    not ignored. (More conservative SR* -> harder to clear the bar.)
    assert indep["sr_star_per_period"] > indep["sr_star_iid_per_period"], (
        indep["sr_star_per_period"], indep["sr_star_iid_per_period"]
    )

    # 3) The observed Sharpe is far below the expected maximum from luck, so
    #    the z-score is strongly negative and the DSR is near zero. This is
    #    the substantive sense in which the guard "binds": the null of no skill
    #    predicts a Sharpe the strategy does not come close to matching.
    assert indep["sharpe_per_period"] < indep["sr_star_per_period"]
    assert indep["z_score"] < 0
    assert indep["deflated_sharpe_ratio"] < 0.10

    # 4) The falsification threshold is not crossed: p-value far above 0.10.
    reported_p = summary["deflated_sharpe"]["p_value"]
    assert reported_p > DSR_PVALUE_THRESHOLD, reported_p
    assert indep["p_value"] > DSR_PVALUE_THRESHOLD
    # The honest verdict stays NOT SUPPORTED on the DSR criterion.
    assert bool(reported_p < DSR_PVALUE_THRESHOLD) is False


if __name__ == "__main__":
    test_dsr_recompute_matches_engine()
    print("test_dsr_recompute_matches_engine OK")
    test_dsr_guard_binds_not_merely_passes()
    print("test_dsr_guard_binds_not_merely_passes OK")
    print("OK")