#!/usr/bin/env python3
"""
Market Regime Detection Module.

Provides methods to identify market regimes (bull/bear/sideways, high/low volatility)
and compute regime-dependent performance metrics for strategy evaluation.

Includes:
- Moving average crossover trend detection (causal)
- Expanding quantile volatility detection (causal)
- Hidden Markov Model (HMM) regime detection with point-in-time guarantees
"""

from typing import Dict, List, Optional, Tuple, Literal
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd
import numpy as np
from scipy.special import logsumexp
from scipy.stats import norm


class TrendRegime(Enum):
    """Market trend regime classification."""
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    UNKNOWN = "unknown"


class VolatilityRegime(Enum):
    """Market volatility regime classification."""
    HIGH = "high"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass
class RegimeConfig:
    """Configuration for regime detection."""
    # Trend regime parameters
    trend_ma_short: int = 50
    trend_ma_long: int = 200
    trend_threshold: float = 0.02  # 2% threshold for trend classification

    # Volatility regime parameters
    vol_window: int = 63  # ~3 months
    vol_quantile_high: float = 0.75
    vol_quantile_low: float = 0.25

    # Combined regime parameters
    min_regime_length: int = 21  # Minimum bars for a regime to be valid


@dataclass
class HMMConfig:
    """Configuration for HMM-based regime detection."""
    n_states: int = 3  # Number of hidden states (regimes)
    n_iter: int = 100  # Maximum EM iterations
    tol: float = 1e-4  # Convergence tolerance
    covariance_type: str = "diag"  # "diag" or "full" - diagonal is more stable
    min_covar: float = 1e-6  # Minimum covariance for numerical stability
    random_state: Optional[int] = 42  # Seed for reproducibility
    # Point-in-time / walk-forward parameters
    refit_window: Optional[int] = None  # If set, refit every N bars (None = single fit on all training data)
    train_frac: float = 0.7  # Fraction of data used for initial training (rest for walk-forward)
    min_regime_length: int = 21  # Minimum observations for a regime to be reported
    # Feature construction
    use_returns: bool = True  # Use returns as primary feature
    use_volatility: bool = True  # Add rolling volatility as feature
    vol_window: int = 21  # Window for rolling volatility feature
    use_trend: bool = False  # Add trend feature (MA diff)
    trend_window: int = 50  # Window for trend feature


@dataclass
class HMMResult:
    """Result of HMM regime detection."""
    regimes: pd.Series  # Regime labels for each time point
    state_probs: pd.DataFrame  # Posterior state probabilities (filtered, point-in-time)
    model_params: Dict  # Fitted model parameters
    log_likelihood: float  # Final log-likelihood
    n_iter: int  # Number of EM iterations
    converged: bool  # Whether EM converged
    feature_names: List[str]  # Names of features used


@dataclass
class RegimePeriod:
    """A contiguous period of a specific regime."""
    regime: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    length: int
    metrics: Dict[str, float]


def detect_trend_regime(
    close: pd.Series,
    ma_short: int = 50,
    ma_long: int = 200,
    threshold: float = 0.02,
) -> pd.Series:
    """
    Detect trend regime (bull/bear/sideways) using moving average crossover.

    Args:
        close: Close price series
        ma_short: Short moving average window
        ma_long: Long moving average window
        threshold: Minimum separation between MAs to classify as bull/bear

    Returns:
        Series with regime labels: 'bull', 'bear', 'sideways', 'unknown'
    """
    if len(close) < ma_long:
        return pd.Series(TrendRegime.UNKNOWN.value, index=close.index)

    sma_short = close.rolling(ma_short).mean()
    sma_long = close.rolling(ma_long).mean()

    # Relative difference between MAs
    ma_diff = (sma_short - sma_long) / sma_long

    regimes = pd.Series(TrendRegime.UNKNOWN.value, index=close.index)
    regimes[ma_diff > threshold] = TrendRegime.BULL.value
    regimes[ma_diff < -threshold] = TrendRegime.BEAR.value
    regimes[(ma_diff >= -threshold) & (ma_diff <= threshold)] = TrendRegime.SIDEWAYS.value

    # Forward fill to handle initial NaN period
    regimes = regimes.replace(TrendRegime.UNKNOWN.value, np.nan).ffill().fillna(TrendRegime.UNKNOWN.value)

    return regimes


def detect_volatility_regime(
    close: pd.Series,
    window: int = 63,
    quantile_high: float = 0.75,
    quantile_low: float = 0.25,
) -> pd.Series:
    """
    Detect volatility regime (high/low) using rolling realized volatility.

    Args:
        close: Close price series
        window: Rolling window for volatility calculation
        quantile_high: Upper quantile threshold for high volatility
        quantile_low: Lower quantile threshold for low volatility

    Returns:
        Series with regime labels: 'high', 'low', 'unknown'
    """
    if len(close) < window + 1:
        return pd.Series(VolatilityRegime.UNKNOWN.value, index=close.index)

    returns = close.pct_change()
    # Annualize realized volatility with the return frequency inferred from
    # the close index (252 business-daily, 365 calendar-daily, 52 weekly,
    # 12 monthly, ...) via the framework convention ``utils._annualization_factor``,
    # falling back to 252 for a non-DatetimeIndex or an un-inferable frequency.
    # Hardcoding sqrt(252) overstated annualized volatility on non-daily data
    # (e.g. ~2.2x too high for weekly bars), which mis-scaled the reported
    # volatility regime and any downstream comparison against a per-regime
    # annualized target. The expanding-quantile *classification* is invariant
    # to this constant scale (both series and thresholds scale together), but
    # the reported magnitude is not, so the level is corrected here.
    try:
        from utils import _annualization_factor
        periods_per_year = float(_annualization_factor(close.index))
    except Exception:
        periods_per_year = 252.0
    if not np.isfinite(periods_per_year) or periods_per_year <= 0:
        periods_per_year = 252.0
    rolling_vol = returns.rolling(window).std() * np.sqrt(periods_per_year)  # Annualized

    # Compute thresholds from the full series (expanding)
    vol_high_threshold = rolling_vol.expanding().quantile(quantile_high)
    vol_low_threshold = rolling_vol.expanding().quantile(quantile_low)

    regimes = pd.Series(VolatilityRegime.UNKNOWN.value, index=close.index)
    regimes[rolling_vol > vol_high_threshold] = VolatilityRegime.HIGH.value
    regimes[rolling_vol < vol_low_threshold] = VolatilityRegime.LOW.value
    regimes[
        (rolling_vol >= vol_low_threshold) & (rolling_vol <= vol_high_threshold)
    ] = VolatilityRegime.UNKNOWN.value  # Medium vol = unknown for binary classification

    # Forward fill to handle initial NaN period
    regimes = regimes.replace(VolatilityRegime.UNKNOWN.value, np.nan).ffill().fillna(VolatilityRegime.UNKNOWN.value)

    return regimes


def detect_combined_regime(
    close: pd.Series,
    config: Optional[RegimeConfig] = None,
) -> pd.Series:
    """
    Detect combined trend + volatility regime.

    Returns labels like: 'bull_high_vol', 'bull_low_vol', 'bear_high_vol',
    'bear_low_vol', 'sideways_high_vol', 'sideways_low_vol', 'unknown'
    """
    if config is None:
        config = RegimeConfig()

    trend = detect_trend_regime(
        close, config.trend_ma_short, config.trend_ma_long, config.trend_threshold
    )
    vol = detect_volatility_regime(
        close, config.vol_window, config.vol_quantile_high, config.vol_quantile_low
    )

    combined = pd.Series("unknown", index=close.index)

    # Only assign combined regime when both trend and vol are known
    mask_known = (trend != TrendRegime.UNKNOWN.value) & (vol != VolatilityRegime.UNKNOWN.value)
    combined[mask_known] = trend[mask_known] + "_" + vol[mask_known]

    # Forward fill unknown periods
    combined = combined.replace("unknown", np.nan).ffill().fillna("unknown")

    return combined


# =============================================================================
# HMM-based Regime Detection (with point-in-time guarantees)
# =============================================================================

class GaussianHMM:
    """
    Gaussian Hidden Markov Model with Baum-Welch EM algorithm.

    Implements a standard HMM with Gaussian emissions. The model is fitted
    using the EM algorithm (Baum-Welch) and supports forward filtering
    for point-in-time regime inference (no look-ahead bias).

    Point-in-time guarantee: The forward algorithm computes P(state_t | obs_1...obs_t)
    using only historical observations up to time t. No future data is used.
    """

    def __init__(self, config: HMMConfig):
        self.config = config
        self.n_states = config.n_states
        self.n_iter = config.n_iter
        self.tol = config.tol
        self.covariance_type = config.covariance_type
        self.min_covar = config.min_covar
        self.random_state = config.random_state

        # Fitted parameters
        self.startprob_ = None  # Initial state distribution (n_states,)
        self.transmat_ = None   # Transition matrix (n_states, n_states)
        self.means_ = None      # Emission means (n_states, n_features)
        self.covars_ = None     # Emission covariances (n_states, n_features) or (n_states, n_features, n_features)

        # Training history
        self.log_likelihood_ = -np.inf
        self.n_iter_ = 0
        self.converged_ = False

    def _initialize_parameters(self, X: np.ndarray) -> None:
        """Initialize HMM parameters using k-means-like initialization."""
        n_samples, n_features = X.shape
        rng = np.random.RandomState(self.random_state)

        # Initialize startprob uniformly
        self.startprob_ = np.ones(self.n_states) / self.n_states

        # Initialize transition matrix with slight diagonal preference (state persistence)
        self.transmat_ = np.ones((self.n_states, self.n_states)) * 0.1
        np.fill_diagonal(self.transmat_, 0.9)
        self.transmat_ = self.transmat_ / self.transmat_.sum(axis=1, keepdims=True)

        # Initialize means using quantiles of the data
        if self.n_states == 2:
            quantiles = [0.25, 0.75]
        elif self.n_states == 3:
            quantiles = [0.167, 0.5, 0.833]
        else:
            quantiles = np.linspace(0.1, 0.9, self.n_states)

        self.means_ = np.percentile(X, [q * 100 for q in quantiles], axis=0)
        if self.means_.ndim == 1:
            self.means_ = self.means_.reshape(-1, 1)

        # Initialize covariances
        global_cov = np.cov(X.T)
        # Ensure global_cov is 2D even for single feature
        if global_cov.ndim == 0:
            global_cov = np.array([[global_cov]])
        n_features = X.shape[1]
        if self.covariance_type == "diag":
            self.covars_ = np.tile(np.diag(global_cov) + self.min_covar, (self.n_states, 1))
        else:
            self.covars_ = np.tile(global_cov + self.min_covar * np.eye(n_features), (self.n_states, 1, 1))

    def _compute_log_emission_probs(self, X: np.ndarray) -> np.ndarray:
        """Compute log emission probabilities log P(X_t | state)."""
        n_samples, n_features = X.shape
        log_probs = np.zeros((n_samples, self.n_states))

        for k in range(self.n_states):
            if self.covariance_type == "diag":
                # Diagonal covariance: independent features
                var = self.covars_[k] + self.min_covar
                log_det = np.sum(np.log(var))
                diff = X - self.means_[k]
                log_probs[:, k] = -0.5 * (n_features * np.log(2 * np.pi) + log_det + np.sum(diff ** 2 / var, axis=1))
            else:
                # Full covariance
                cov = self.covars_[k] + self.min_covar * np.eye(n_features)
                try:
                    log_det = np.linalg.slogdet(cov)[1]
                    diff = X - self.means_[k]
                    precision = np.linalg.inv(cov)
                    log_probs[:, k] = -0.5 * (n_features * np.log(2 * np.pi) + log_det + np.sum(diff @ precision * diff, axis=1))
                except np.linalg.LinAlgError:
                    # Fallback to diagonal if singular
                    var = np.diag(cov) + self.min_covar
                    log_det = np.sum(np.log(var))
                    diff = X - self.means_[k]
                    log_probs[:, k] = -0.5 * (n_features * np.log(2 * np.pi) + log_det + np.sum(diff ** 2 / var, axis=1))

        return log_probs

    def _forward(self, log_emission: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Forward algorithm (filtering).

        Computes alpha_t(i) = P(obs_1...obs_t, state_t=i) in log space.
        Returns log_alpha and log_likelihood.

        This is the point-in-time inference: alpha_t only depends on obs_1...obs_t.
        """
        n_samples = log_emission.shape[0]
        log_alpha = np.zeros((n_samples, self.n_states))

        # Initial step
        log_alpha[0] = np.log(self.startprob_ + 1e-300) + log_emission[0]

        # Recursion
        for t in range(1, n_samples):
            # log_alpha[t-1] + log(transmat_.T)  -> (n_states,) + (n_states, n_states) -> (n_states, n_states)
            # logsumexp over previous states
            log_alpha[t] = logsumexp(log_alpha[t-1, :, np.newaxis] + np.log(self.transmat_.T + 1e-300), axis=0)
            log_alpha[t] += log_emission[t]

        log_likelihood = logsumexp(log_alpha[-1])
        return log_alpha, log_likelihood

    def _backward(self, log_emission: np.ndarray) -> np.ndarray:
        """Backward algorithm for smoothing (used in Baum-Welch E-step)."""
        n_samples = log_emission.shape[0]
        log_beta = np.zeros((n_samples, self.n_states))

        # Final step: beta_T = 0 (log(1))
        log_beta[-1] = 0.0

        # Recursion (backward)
        for t in range(n_samples - 2, -1, -1):
            # log_beta[t] = logsumexp( log(transmat_) + log_emission[t+1] + log_beta[t+1] )
            log_beta[t] = logsumexp(
                np.log(self.transmat_ + 1e-300) + log_emission[t+1] + log_beta[t+1],
                axis=1
            )

        return log_beta

    def _compute_posteriors(self, log_alpha: np.ndarray, log_beta: np.ndarray, log_likelihood: float) -> np.ndarray:
        """Compute posterior state probabilities gamma_t(i) = P(state_t=i | all obs)."""
        log_gamma = log_alpha + log_beta - log_likelihood
        return np.exp(log_gamma)

    def _compute_xi(self, log_emission: np.ndarray, log_alpha: np.ndarray,
                    log_beta: np.ndarray, log_likelihood: float) -> np.ndarray:
        """Compute transition posteriors xi_t(i,j) = P(state_t=i, state_{t+1}=j | all obs)."""
        n_samples = log_emission.shape[0]
        log_xi = np.zeros((n_samples - 1, self.n_states, self.n_states))

        for t in range(n_samples - 1):
            # log_xi[t, i, j] = log_alpha[t, i] + log(transmat_[i, j]) + log_emission[t+1, j] + log_beta[t+1, j] - log_likelihood
            log_xi[t] = (
                log_alpha[t, :, np.newaxis]
                + np.log(self.transmat_ + 1e-300)
                + log_emission[t+1, np.newaxis, :]
                + log_beta[t+1, np.newaxis, :]
                - log_likelihood
            )

        return np.exp(log_xi)

    def fit(self, X: np.ndarray) -> "GaussianHMM":
        """
        Fit HMM using Baum-Welch EM algorithm.

        Args:
            X: Observations (n_samples, n_features)

        Returns:
            self
        """
        n_samples, n_features = X.shape

        # Initialize parameters
        self._initialize_parameters(X)

        prev_log_likelihood = -np.inf

        for iteration in range(self.n_iter):
            # E-step: Forward-backward
            log_emission = self._compute_log_emission_probs(X)
            log_alpha, log_likelihood = self._forward(log_emission)
            log_beta = self._backward(log_emission)

            # Compute posteriors
            gamma = self._compute_posteriors(log_alpha, log_beta, log_likelihood)
            xi = self._compute_xi(log_emission, log_alpha, log_beta, log_likelihood)

            # M-step: Update parameters
            # Start probabilities
            self.startprob_ = gamma[0]

            # Transition matrix
            self.transmat_ = xi.sum(axis=0) / gamma[:-1].sum(axis=0)[:, np.newaxis]
            # Handle zero rows
            zero_rows = self.transmat_.sum(axis=1) == 0
            if zero_rows.any():
                self.transmat_[zero_rows] = 1.0 / self.n_states

            # Emission means
            self.means_ = (gamma.T @ X) / gamma.sum(axis=0)[:, np.newaxis]

            # Emission covariances
            if self.covariance_type == "diag":
                for k in range(self.n_states):
                    diff = X - self.means_[k]
                    weighted_diff = gamma[:, k, np.newaxis] * diff
                    self.covars_[k] = np.sum(weighted_diff * diff, axis=0) / gamma[:, k].sum()
                    self.covars_[k] = np.maximum(self.covars_[k], self.min_covar)
            else:
                for k in range(self.n_states):
                    diff = X - self.means_[k]
                    weighted_diff = gamma[:, k, np.newaxis, np.newaxis] * diff[:, :, np.newaxis] * diff[:, np.newaxis, :]
                    self.covars_[k] = np.sum(weighted_diff, axis=0) / gamma[:, k].sum()
                    self.covars_[k] += self.min_covar * np.eye(n_features)

            # Check convergence
            if abs(log_likelihood - prev_log_likelihood) < self.tol:
                self.converged_ = True
                break

            prev_log_likelihood = log_likelihood

        self.log_likelihood_ = log_likelihood
        self.n_iter_ = iteration + 1

        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """
        Predict most likely state sequence using Viterbi algorithm.

        Note: Viterbi uses the full sequence, so this is NOT point-in-time.
        For point-in-time inference, use `filter()` instead.
        """
        log_emission = self._compute_log_emission_probs(X)
        n_samples = X.shape[0]

        # Viterbi
        log_delta = np.zeros((n_samples, self.n_states))
        psi = np.zeros((n_samples, self.n_states), dtype=int)

        log_delta[0] = np.log(self.startprob_ + 1e-300) + log_emission[0]

        for t in range(1, n_samples):
            for j in range(self.n_states):
                trans_scores = log_delta[t-1] + np.log(self.transmat_[:, j] + 1e-300)
                psi[t, j] = np.argmax(trans_scores)
                log_delta[t, j] = trans_scores[psi[t, j]] + log_emission[t, j]

        # Backtrack
        states = np.zeros(n_samples, dtype=int)
        states[-1] = np.argmax(log_delta[-1])
        for t in range(n_samples - 2, -1, -1):
            states[t] = psi[t+1, states[t+1]]

        return states

    def filter(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Forward filtering for point-in-time regime inference.

        Computes P(state_t | obs_1...obs_t) for each t using only historical data.
        This is the point-in-time inference - no future observations are used.

        Args:
            X: Observations (n_samples, n_features)

        Returns:
            filtered_probs: (n_samples, n_states) - P(state_t | obs_1...obs_t)
            log_likelihood: Log-likelihood of the sequence
        """
        log_emission = self._compute_log_emission_probs(X)
        log_alpha, log_likelihood = self._forward(log_emission)

        # Normalize alpha to get filtered probabilities
        # log_alpha[t] = log P(obs_1...obs_t, state_t)
        # P(state_t | obs_1...obs_t) = exp(log_alpha[t]) / sum(exp(log_alpha[t]))
        filtered_probs = np.exp(log_alpha - logsumexp(log_alpha, axis=1, keepdims=True))

        return filtered_probs, log_likelihood

    def score(self, X: np.ndarray) -> float:
        """Compute log-likelihood of observations under the model."""
        log_emission = self._compute_log_emission_probs(X)
        _, log_likelihood = self._forward(log_emission)
        return log_likelihood


def build_hmm_features(
    close: pd.Series,
    config: HMMConfig,
) -> Tuple[np.ndarray, List[str]]:
    """
    Build feature matrix for HMM from price series.

    Features are constructed causally (no look-ahead):
    - Returns: pct_change (uses current and previous close)
    - Rolling volatility: rolling std of returns (uses window of past returns)
    - Trend: MA diff (uses rolling MAs of past closes)

    All features are computed using only historical data up to each point.

    Args:
        close: Close price series
        config: HMM configuration

    Returns:
        Feature matrix (n_samples, n_features) and feature names
    """
    features = []
    feature_names = []

    # Returns feature (most informative for regime detection)
    if config.use_returns:
        returns = close.pct_change()
        features.append(returns.values.reshape(-1, 1))
        feature_names.append("returns")

    # Rolling volatility feature
    if config.use_volatility:
        returns = close.pct_change()
        # Annualize with the return frequency inferred from the index (see
        # detect_volatility_regime); the hardcoded sqrt(252) overstated the
        # feature scale on non-daily data. Regime *labels* are invariant to a
        # constant per-feature scale (Gaussian-emission EM is location/scale
        # invariant), but the reported ``means``/``covars`` model params are
        # not, so the level is corrected here for interpretability.
        try:
            from utils import _annualization_factor
            periods_per_year = float(_annualization_factor(close.index))
        except Exception:
            periods_per_year = 252.0
        if not np.isfinite(periods_per_year) or periods_per_year <= 0:
            periods_per_year = 252.0
        rolling_vol = returns.rolling(config.vol_window).std() * np.sqrt(periods_per_year)
        features.append(rolling_vol.values.reshape(-1, 1))
        feature_names.append("volatility")

    # Trend feature (MA diff)
    if config.use_trend:
        sma_short = close.rolling(config.trend_window).mean()
        sma_long = close.rolling(config.trend_window * 4).mean()
        ma_diff = (sma_short - sma_long) / sma_long
        features.append(ma_diff.values.reshape(-1, 1))
        feature_names.append("trend")

    # Combine features
    if len(features) == 0:
        raise ValueError("At least one feature must be enabled in HMMConfig")

    X = np.hstack(features)

    # Handle NaN values (from rolling windows) - forward fill then backward fill
    # This is done per feature, causally
    X_filled = np.zeros_like(X)
    for i in range(X.shape[1]):
        col = X[:, i]
        # Forward fill
        mask = np.isnan(col)
        if mask.all():
            X_filled[:, i] = 0.0
        else:
            idx = np.where(~mask)[0]
            first_valid = idx[0]
            col_filled = col.copy()
            col_filled[:first_valid] = col[first_valid]  # Backfill initial NaNs
            # Forward fill remaining
            for j in range(first_valid + 1, len(col_filled)):
                if np.isnan(col_filled[j]):
                    col_filled[j] = col_filled[j-1]
            X_filled[:, i] = col_filled

    return X_filled, feature_names


def fit_hmm_walkforward(
    close: pd.Series,
    config: HMMConfig,
) -> HMMResult:
    """
    Fit HMM with walk-forward refitting for point-in-time guarantees.

    If config.refit_window is set, the model is refit periodically using only
    data available up to that point. This simulates real-time deployment where
    the model is updated as new data arrives.

    If config.refit_window is None, the model is fit once on the training portion
    (config.train_frac) and then used to filter the entire series.

    Args:
        close: Close price series
        config: HMM configuration

    Returns:
        HMMResult with regimes, state probabilities, and model info
    """
    X, feature_names = build_hmm_features(close, config)
    n_samples = X.shape[0]

    if config.refit_window is None:
        # Single fit on training data, then filter full series
        train_size = int(n_samples * config.train_frac)
        if train_size < config.n_states * 10:
            train_size = min(n_samples, config.n_states * 10)

        X_train = X[:train_size]

        # Fit model
        hmm = GaussianHMM(config)
        hmm.fit(X_train)

        # Filter full series (point-in-time inference)
        filtered_probs, log_likelihood = hmm.filter(X)

        # Most likely state at each point
        regimes = np.argmax(filtered_probs, axis=1)

        # Map to labels
        regime_labels = _map_hmm_states_to_labels(filtered_probs, X, feature_names)
        regimes_series = pd.Series(regime_labels, index=close.index)

        # State probabilities DataFrame
        state_probs = pd.DataFrame(
            filtered_probs,
            index=close.index,
            columns=[f"state_{i}" for i in range(config.n_states)]
        )

        return HMMResult(
            regimes=regimes_series,
            state_probs=state_probs,
            model_params={
                "startprob": hmm.startprob_.tolist(),
                "transmat": hmm.transmat_.tolist(),
                "means": hmm.means_.tolist(),
                "covars": hmm.covars_.tolist() if config.covariance_type == "diag" else [c.tolist() for c in hmm.covars_],
            },
            log_likelihood=hmm.log_likelihood_,
            n_iter=hmm.n_iter_,
            converged=hmm.converged_,
            feature_names=feature_names,
        )
    else:
        # Walk-forward refitting
        refit_window = config.refit_window
        regimes = np.full(n_samples, -1, dtype=int)
        all_filtered_probs = np.zeros((n_samples, config.n_states))

        # Initial training window
        train_size = int(n_samples * config.train_frac)
        if train_size < config.n_states * 10:
            train_size = min(n_samples, config.n_states * 10)

        current_train_end = train_size

        while current_train_end < n_samples:
            # Fit on data up to current_train_end
            X_train = X[:current_train_end]
            hmm = GaussianHMM(config)
            hmm.fit(X_train)

            # Determine prediction window
            pred_end = min(current_train_end + refit_window, n_samples)
            X_pred = X[current_train_end:pred_end]

            if len(X_pred) > 0:
                # Filter prediction window
                filtered_probs, _ = hmm.filter(X_pred)
                pred_regimes = np.argmax(filtered_probs, axis=1)

                regimes[current_train_end:pred_end] = pred_regimes
                all_filtered_probs[current_train_end:pred_end] = filtered_probs

            current_train_end = pred_end

        # Handle initial training period (use the first fitted model to filter it)
        hmm_initial = GaussianHMM(config)
        hmm_initial.fit(X[:train_size])
        init_filtered, _ = hmm_initial.filter(X[:train_size])
        regimes[:train_size] = np.argmax(init_filtered, axis=1)
        all_filtered_probs[:train_size] = init_filtered

        # Map to labels
        regime_labels = _map_hmm_states_to_labels(all_filtered_probs, X, feature_names)
        regimes_series = pd.Series(regime_labels, index=close.index)

        state_probs = pd.DataFrame(
            all_filtered_probs,
            index=close.index,
            columns=[f"state_{i}" for i in range(config.n_states)]
        )

        return HMMResult(
            regimes=regimes_series,
            state_probs=state_probs,
            model_params={
                "startprob": hmm.startprob_.tolist(),
                "transmat": hmm.transmat_.tolist(),
                "means": hmm.means_.tolist(),
                "covars": hmm.covars_.tolist() if config.covariance_type == "diag" else [c.tolist() for c in hmm.covars_],
            },
            log_likelihood=hmm.log_likelihood_,
            n_iter=hmm.n_iter_,
            converged=hmm.converged_,
            feature_names=feature_names,
        )


def _map_hmm_states_to_labels(
    state_probs: np.ndarray,
    X: np.ndarray,
    feature_names: List[str],
) -> List[str]:
    """
    Map HMM states to interpretable regime labels based on emission parameters.

    This is a post-hoc interpretation and does not affect the model fitting.
    The mapping is based on the mean returns and volatility of each state.
    """
    n_states = state_probs.shape[1]
    regime_returns = []

    # Find returns feature index
    returns_idx = feature_names.index("returns") if "returns" in feature_names else 0

    for k in range(n_states):
        # Weighted average return for this state
        weights = state_probs[:, k]
        weighted_return = np.sum(weights * X[:, returns_idx]) / np.sum(weights)
        regime_returns.append(weighted_return)

    # Sort states by mean return
    sorted_states = np.argsort(regime_returns)

    # Assign labels based on sorted order
    labels = {}
    if n_states == 2:
        labels[sorted_states[0]] = "bear"
        labels[sorted_states[1]] = "bull"
    elif n_states == 3:
        labels[sorted_states[0]] = "bear"
        labels[sorted_states[1]] = "sideways"
        labels[sorted_states[2]] = "bull"
    else:
        # Generic labels for more states
        for i, state_idx in enumerate(sorted_states):
            if i == 0:
                labels[state_idx] = "bear"
            elif i == n_states - 1:
                labels[state_idx] = "bull"
            else:
                labels[state_idx] = f"regime_{i}"

    # Convert state sequence to labels
    state_sequence = np.argmax(state_probs, axis=1)
    return [labels.get(s, f"state_{s}") for s in state_sequence]


def detect_hmm_regime(
    close: pd.Series,
    config: Optional[HMMConfig] = None,
) -> pd.Series:
    """
    Detect market regimes using Hidden Markov Model with point-in-time guarantees.

    This function uses the walk-forward HMM approach where:
    1. Model is fit on historical data only (no future data)
    2. Forward filtering computes P(state_t | obs_1...obs_t) - point-in-time
    3. Optional periodic refitting simulates real-time model updates

    Args:
        close: Close price series
        config: HMM configuration (uses defaults if None)

    Returns:
        Series with regime labels (e.g., 'bull', 'bear', 'sideways')
    """
    if config is None:
        config = HMMConfig()

    result = fit_hmm_walkforward(close, config)
    return result.regimes


def detect_hmm_regime_with_probs(
    close: pd.Series,
    config: Optional[HMMConfig] = None,
) -> Tuple[pd.Series, pd.DataFrame]:
    """
    Detect market regimes using HMM and return both labels and state probabilities.

    Args:
        close: Close price series
        config: HMM configuration

    Returns:
        Tuple of (regime_labels_series, state_probabilities_dataframe)
    """
    if config is None:
        config = HMMConfig()

    result = fit_hmm_walkforward(close, config)
    return result.regimes, result.state_probs


def add_hmm_regime_analysis_to_results(
    results: Dict,
    data: pd.DataFrame | Dict[str, pd.DataFrame],
    returns_key: str = "returns",
    close_key: str = "close",
    config: Optional[HMMConfig] = None,
) -> Dict:
    """
    Add HMM-based regime analysis to backtest results.

    Args:
        results: Backtest results dictionary
        data: Market data (DataFrame or dict of DataFrames for panels)
        returns_key: Key in results for strategy returns
        close_key: Column name for close prices in data
        config: HMM configuration

    Returns:
        Updated results dict with hmm_regime_analysis key
    """
    # Extract returns
    if returns_key not in results:
        return results

    returns = results[returns_key]
    if not isinstance(returns, pd.Series):
        try:
            returns = pd.Series(returns)
        except Exception:
            return results

    # Extract close prices
    if isinstance(data, dict):
        first_asset = next(iter(data.values()))
        if isinstance(first_asset, pd.DataFrame) and close_key in first_asset.columns:
            close = first_asset[close_key]
        else:
            return results
    elif isinstance(data, pd.DataFrame):
        if close_key in data.columns:
            close = data[close_key]
        else:
            return results
    else:
        return results

    # Align returns and close
    common_index = returns.index.intersection(close.index)
    if len(common_index) == 0:
        return results

    returns_aligned = returns.loc[common_index]
    close_aligned = close.loc[common_index]

    # Compute HMM regime analysis
    config = config or HMMConfig()
    hmm_result = fit_hmm_walkforward(close_aligned, config)

    # Compute performance per HMM regime
    regime_perf = compute_regime_performance(
        returns_aligned, hmm_result.regimes, config.min_regime_length
    )

    results["hmm_regime_analysis"] = {
        "config": {
            "n_states": config.n_states,
            "n_iter": config.n_iter,
            "tol": config.tol,
            "covariance_type": config.covariance_type,
            "refit_window": config.refit_window,
            "train_frac": config.train_frac,
            "feature_names": hmm_result.feature_names,
        },
        "model_params": hmm_result.model_params,
        "log_likelihood": hmm_result.log_likelihood,
        "n_iter": hmm_result.n_iter,
        "converged": hmm_result.converged,
        "regime_performance": regime_perf,
        "regime_distribution": hmm_result.regimes.value_counts().to_dict(),
    }

    return results


def identify_regime_periods(regimes: pd.Series) -> List[RegimePeriod]:
    """
    Identify contiguous regime periods from a regime series.

    Args:
        regimes: Series with regime labels

    Returns:
        List of RegimePeriod objects
    """
    periods = []
    current_regime = None
    start_idx = None

    for i, (date, regime) in enumerate(regimes.items()):
        if regime != current_regime:
            if current_regime is not None and start_idx is not None:
                end_date = regimes.index[i - 1]
                periods.append(RegimePeriod(
                    regime=current_regime,
                    start_date=regimes.index[start_idx],
                    end_date=end_date,
                    length=i - start_idx,
                    metrics={}
                ))
            current_regime = regime
            start_idx = i

    # Handle last period
    if current_regime is not None and start_idx is not None:
        periods.append(RegimePeriod(
            regime=current_regime,
            start_date=regimes.index[start_idx],
            end_date=regimes.index[-1],
            length=len(regimes) - start_idx,
            metrics={}
        ))

    return periods


def compute_regime_performance(
    returns: pd.Series,
    regimes: pd.Series,
    min_period_length: int = 21,
    periods_per_year: Optional[float] = None,
) -> Dict[str, Dict[str, float]]:
    """
    Compute performance metrics per regime.

    Args:
        returns: Strategy returns series
        regimes: Regime labels series (aligned with returns)
        min_period_length: Minimum observations for a regime to be reported
        periods_per_year: Annualization factor for the regime's return
            frequency. ``None`` infers it from the returns index via
            :func:`utils._annualization_factor` (252 business-daily,
            365 calendar-daily, 52 weekly, 12 monthly, ...), falling back
            to 252 when the index is not a DatetimeIndex or the frequency
            cannot be inferred. Passing an explicit value overrides it.

    Returns:
        Dict mapping regime -> metrics dict
    """
    # Align series
    aligned = pd.DataFrame({"returns": returns, "regime": regimes}).dropna()

    if len(aligned) == 0:
        return {}

    if periods_per_year is None:
        try:
            from utils import _annualization_factor
            periods_per_year = float(_annualization_factor(aligned["returns"].index))
        except Exception:
            periods_per_year = 252.0
    periods_per_year = float(periods_per_year)
    if not np.isfinite(periods_per_year) or periods_per_year <= 0:
        periods_per_year = 252.0

    results = {}

    for regime in aligned["regime"].unique():
        if regime == "unknown":
            continue

        regime_returns = aligned.loc[aligned["regime"] == regime, "returns"]

        if len(regime_returns) < min_period_length:
            continue

        # Basic metrics. The annualization factor is inferred from the
        # returns' own frequency (see _annualization_factor), so the same
        # return process reported at daily, weekly or monthly frequency
        # yields the same annualized regime metrics. Hardcoding 252 made
        # weekly/monthly regime Sharpe numbers inconsistent with the daily
        # ones computed elsewhere in the framework for the same process.
        total_return = (1 + regime_returns).prod() - 1
        ann_return = (1 + total_return) ** (periods_per_year / len(regime_returns)) - 1
        ann_vol = regime_returns.std() * np.sqrt(periods_per_year)
        sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0

        # Drawdown
        equity = (1 + regime_returns).cumprod()
        running_max = equity.expanding().max()
        drawdown = (equity - running_max) / running_max
        max_drawdown = drawdown.min()

        # Win rate
        win_rate = (regime_returns > 0).mean()

        # Skewness / Kurtosis
        skew = regime_returns.skew()
        kurt = regime_returns.kurtosis()

        results[regime] = {
            "n_observations": len(regime_returns),
            "total_return": float(total_return),
            "annualized_return": float(ann_return),
            "annualized_volatility": float(ann_vol),
            "sharpe_ratio": float(sharpe),
            "max_drawdown": float(max_drawdown),
            "win_rate": float(win_rate),
            "skewness": float(skew),
            "kurtosis": float(kurt),
        }

    return results


def regime_performance_summary(
    returns: pd.Series,
    close: pd.Series,
    config: Optional[RegimeConfig] = None,
    periods_per_year: Optional[float] = None,
) -> Dict:
    """
    Generate a complete regime-dependent performance summary.

    Args:
        returns: Strategy returns series
        close: Market close price series (for regime detection)
        config: Regime detection configuration
        periods_per_year: Annualization factor for the regime metrics.
            ``None`` infers it from the returns index via
            :func:`utils._annualization_factor` (252 business-daily,
            365 calendar-daily, 52 weekly, 12 monthly, ...), falling back
            to 252 when the index is not a DatetimeIndex or the frequency
            cannot be inferred. Passing an explicit value overrides it.

    Returns:
        Dict with regime detection results and per-regime performance
    """
    if config is None:
        config = RegimeConfig()

    # Detect regimes on market data
    trend_regimes = detect_trend_regime(
        close, config.trend_ma_short, config.trend_ma_long, config.trend_threshold
    )
    vol_regimes = detect_volatility_regime(
        close, config.vol_window, config.vol_quantile_high, config.vol_quantile_low
    )
    combined_regimes = detect_combined_regime(close, config)

    # Align all series
    df = pd.DataFrame({
        "returns": returns,
        "trend_regime": trend_regimes,
        "vol_regime": vol_regimes,
        "combined_regime": combined_regimes,
    }).dropna()

    if len(df) == 0:
        return {
            "trend_regime_performance": {},
            "volatility_regime_performance": {},
            "combined_regime_performance": {},
            "regime_periods": [],
        }

    trend_perf = compute_regime_performance(
        df["returns"], df["trend_regime"], config.min_regime_length,
        periods_per_year=periods_per_year,
    )
    vol_perf = compute_regime_performance(
        df["returns"], df["vol_regime"], config.min_regime_length,
        periods_per_year=periods_per_year,
    )
    combined_perf = compute_regime_performance(
        df["returns"], df["combined_regime"], config.min_regime_length,
        periods_per_year=periods_per_year,
    )

    # Identify regime periods for combined regime
    regime_periods = identify_regime_periods(df["combined_regime"])

    # Add performance metrics to periods
    for period in regime_periods:
        if period.regime in combined_perf:
            period.metrics = combined_perf[period.regime]

    return {
        "config": {
            "trend_ma_short": config.trend_ma_short,
            "trend_ma_long": config.trend_ma_long,
            "trend_threshold": config.trend_threshold,
            "vol_window": config.vol_window,
            "vol_quantile_high": config.vol_quantile_high,
            "vol_quantile_low": config.vol_quantile_low,
            "min_regime_length": config.min_regime_length,
        },
        "trend_regime_performance": trend_perf,
        "volatility_regime_performance": vol_perf,
        "combined_regime_performance": combined_perf,
        "regime_periods": [
            {
                "regime": p.regime,
                "start_date": p.start_date.isoformat() if isinstance(p.start_date, pd.Timestamp) else str(p.start_date),
                "end_date": p.end_date.isoformat() if isinstance(p.end_date, pd.Timestamp) else str(p.end_date),
                "length": p.length,
                "metrics": p.metrics,
            }
            for p in regime_periods
        ],
        "regime_distribution": df["combined_regime"].value_counts().to_dict(),
    }


def regime_aware_position_size(
    base_signals: pd.Series,
    close: pd.Series,
    regimes: pd.Series,
    target_vol_by_regime: Dict[str, float],
    lookback: int = 63,
    min_leverage: float = 0.0,
    max_leverage: float = 2.0,
    default_target_vol: Optional[float] = None,
    periods_per_year: Optional[float] = None,
) -> pd.Series:
    """Scale ``base_signals`` to a per-regime volatility target.

    This is a position-sizing overlay, not a signal generator. For every bar
    ``t`` it computes::

        realized_vol_t = std(returns[t-lookback+1 .. t]) * sqrt(periods_per_year)
        target_t       = target_vol_by_regime[regime_t]
        multiplier_t   = clip(target_t / realized_vol_t,
                              min_leverage, max_leverage)
        sized_t        = base_signals_t * multiplier_t

    Point-in-time guarantee: ``realized_vol_t`` uses only returns up to and
    including ``t`` (a trailing rolling window), and ``regime_t`` is taken as
    supplied. The caller is responsible for passing point-in-time regime
    labels (for example from ``detect_hmm_regime``'s forward filter or a causal
    detector); this function does not infer regimes itself. Mutating future
    prices therefore leaves every already-computed position size unchanged.

    Args:
        base_signals: Target direction/position from the underlying strategy.
            Only its sign and scale are preserved; the overlay rescales it.
        close: Close prices used to estimate realized volatility.
        regimes: Regime label per bar, aligned with ``close``.
        target_vol_by_regime: Mapping from regime label to annualized target
            volatility (as a decimal, e.g. ``{"bull": 0.10, "bear": 0.20}``).
            Values must be finite and non-negative.
        lookback: Rolling window (in bars) for realized volatility. The first
            ``lookback - 1`` bars have no estimate and are returned as NaN.
        min_leverage: Lower clip bound for the position multiplier.
        max_leverage: Upper clip bound for the position multiplier. Used as the
            multiplier when realized volatility is exactly zero (the
            target-vol convention of maximum permitted leverage).
        default_target_vol: Target volatility for regime labels absent from
            ``target_vol_by_regime`` (and for missing labels). If ``None``, an
            unmapped regime raises ``ValueError`` instead of silently going
            flat.
        periods_per_year: Annualization factor for realized volatility.
            ``None`` infers it from the ``close`` index via
            :func:`utils._annualization_factor` (252 business-daily,
            365 calendar-daily, 52 weekly, 12 monthly, ...), falling back
            to 252 when the index is not a DatetimeIndex or the frequency
            cannot be inferred. Passing an explicit value overrides it.
            Defaults to ``None`` rather than a hardcoded 252: a caller
            passing weekly ``close`` with the old default got a ~2.2x
            under-sized position (multiplier 0.45x of correct), because the
            realized vol was under-annualized.

    Returns:
        A float ``pd.Series`` of position sizes on the common index of
        ``base_signals``, ``close`` and ``regimes``.

    Raises:
        ValueError: On invalid arguments, empty index overlap, or an unmapped
            regime label when ``default_target_vol`` is not provided.
    """
    if lookback < 1:
        raise ValueError(f"lookback must be >= 1, got {lookback}")
    if min_leverage > max_leverage:
        raise ValueError(
            f"min_leverage ({min_leverage}) must be <= max_leverage ({max_leverage})"
        )
    if not target_vol_by_regime:
        raise ValueError("target_vol_by_regime must not be empty")
    for label, vol in target_vol_by_regime.items():
        if not np.isfinite(vol) or vol < 0:
            raise ValueError(
                f"target volatility for regime {label!r} must be finite and "
                f"non-negative, got {vol}"
            )
    if default_target_vol is not None and (
        not np.isfinite(default_target_vol) or default_target_vol < 0
    ):
        raise ValueError(
            f"default_target_vol must be finite and non-negative, got {default_target_vol}"
        )

    base = pd.Series(base_signals, dtype=float)
    close_s = pd.Series(close, dtype=float)
    reg = pd.Series(regimes)

    common = base.index.intersection(close_s.index).intersection(reg.index)
    if len(common) == 0:
        raise ValueError(
            "base_signals, close and regimes share no common index; cannot size positions"
        )
    base = base.loc[common]
    close_s = close_s.loc[common]
    reg = reg.loc[common]

    if periods_per_year is None:
        # Infer the annualization factor from the close index so a weekly or
        # monthly series sizes positions against a weekly/monthly realized vol,
        # not a daily-annualized one. Mirrors compute_regime_performance's
        # ``Optional[float] = None`` pattern; falls back to 252 when the
        # frequency cannot be inferred.
        try:
            from utils import _annualization_factor
            periods_per_year = float(_annualization_factor(close_s.index))
        except Exception:
            periods_per_year = 252.0
    periods_per_year = float(periods_per_year)
    if not np.isfinite(periods_per_year) or periods_per_year <= 0:
        periods_per_year = 252.0

    returns = close_s.pct_change()
    realized_vol = returns.rolling(window=lookback, min_periods=lookback).std() * np.sqrt(
        periods_per_year
    )

    target = reg.map(target_vol_by_regime)
    if target.isna().any():
        if default_target_vol is None:
            missing = sorted(reg[target.isna()].dropna().astype(str).unique().tolist())
            detail = f" {missing}" if missing else ""
            raise ValueError(
                "no volatility target for regime label(s)"
                f"{detail}; add them to target_vol_by_regime or pass "
                "default_target_vol"
            )
        target = target.fillna(default_target_vol)
    target = target.astype(float)

    with np.errstate(divide="ignore", invalid="ignore"):
        multiplier = (target / realized_vol).clip(lower=min_leverage, upper=max_leverage)
    # A zero target with zero realized volatility is 0/0 -> NaN; the intended
    # multiplier is 0 (no position), not "not enough data".
    multiplier = multiplier.mask((realized_vol == 0) & (target == 0), 0.0)

    sized = base * multiplier
    sized.name = base.name
    return sized


def add_regime_analysis_to_results(
    results: Dict,
    data: pd.DataFrame | Dict[str, pd.DataFrame],
    returns_key: str = "returns",
    close_key: str = "close",
    config: Optional[RegimeConfig] = None,
) -> Dict:
    """
    Add regime-dependent performance analysis to backtest results.

    Args:
        results: Backtest results dictionary
        data: Market data (DataFrame or dict of DataFrames for panels)
        returns_key: Key in results for strategy returns
        close_key: Column name for close prices in data
        config: Regime detection configuration

    Returns:
        Updated results dict with regime_analysis key
    """
    # Extract returns
    if returns_key not in results:
        return results

    returns = results[returns_key]
    if not isinstance(returns, pd.Series):
        try:
            returns = pd.Series(returns)
        except Exception:
            return results

    # Extract close prices
    if isinstance(data, dict):
        # Panel data - use first asset's close
        first_asset = next(iter(data.values()))
        if isinstance(first_asset, pd.DataFrame) and close_key in first_asset.columns:
            close = first_asset[close_key]
        else:
            return results
    elif isinstance(data, pd.DataFrame):
        if close_key in data.columns:
            close = data[close_key]
        else:
            return results
    else:
        return results

    # Align returns and close
    common_index = returns.index.intersection(close.index)
    if len(common_index) == 0:
        return results

    returns_aligned = returns.loc[common_index]
    close_aligned = close.loc[common_index]

    # Compute regime analysis
    regime_analysis = regime_performance_summary(returns_aligned, close_aligned, config)

    results["regime_analysis"] = regime_analysis
    return results


def regime_concentration_diagnostic(
    regime_analysis: Dict,
    min_regime_length: int = 21,
    min_sharpe: float = 0.0,
    sharpe_spread_threshold: float = 1.0,
) -> Dict:
    """
    Assess whether a strategy's edge is concentrated in a single market regime.

    A strategy whose Sharpe is positive in only one regime (and flat or
    negative in the others) is regime-dependent: its apparent edge may not
    survive a regime change. This is a measurement only -- it changes no
    return, cost, impact or capacity number.

    Args:
        regime_analysis: Output of ``regime_performance_summary``.
        min_regime_length: Minimum observations for a regime to count as traded.
        min_sharpe: Sharpe threshold above which a regime counts as positive.
        sharpe_spread_threshold: Sharpe spread beyond which multi-regime
            performance is treated as inconsistent ("moderate").

    Returns:
        Dict with the robustness classification, per-regime Sharpe ratios,
        and a human-readable message. ``regime_robustness`` is one of
        ``robust``, ``moderate``, ``fragile``, ``insufficient_data``.
    """
    combined = (regime_analysis or {}).get("combined_regime_performance") or {}

    per_regime = {}
    for regime, metrics in combined.items():
        if not isinstance(metrics, dict):
            continue
        if regime == "unknown":
            continue
        n_observations = int(metrics.get("n_observations", 0) or 0)
        sharpe_ratio = float(metrics.get("sharpe_ratio", 0.0) or 0.0)
        per_regime[regime] = {
            "sharpe_ratio": sharpe_ratio,
            "n_observations": n_observations,
        }

    traded = {
        regime: values
        for regime, values in per_regime.items()
        if values["n_observations"] >= min_regime_length
    }

    n_traded = len(traded)
    result = {
        "regime_robustness": "insufficient_data",
        "is_regime_concentrated": False,
        "n_regimes_traded": n_traded,
        "n_regimes_positive": 0,
        "n_regimes_negative": 0,
        "best_regime": None,
        "best_sharpe": None,
        "worst_regime": None,
        "worst_sharpe": None,
        "sharpe_spread": 0.0,
        "regime_sharpes": {},
        "regime_observations": {},
        "dominant_regime": None,
        "message": "Fewer than two regimes have enough observations to classify regime dependence.",
    }

    if n_traded < 2:
        return result

    sharpes = {regime: values["sharpe_ratio"] for regime, values in traded.items()}
    observations = {regime: values["n_observations"] for regime, values in traded.items()}

    positive = [regime for regime, sharpe in sharpes.items() if sharpe > min_sharpe]
    negative = [regime for regime, sharpe in sharpes.items() if sharpe < -min_sharpe]

    best_regime = max(sharpes, key=sharpes.get)
    worst_regime = min(sharpes, key=sharpes.get)
    best_sharpe = sharpes[best_regime]
    worst_sharpe = sharpes[worst_regime]
    sharpe_spread = best_sharpe - worst_sharpe
    dominant_regime = max(observations, key=observations.get)

    result.update({
        "regime_sharpes": sharpes,
        "regime_observations": observations,
        "best_regime": best_regime,
        "best_sharpe": best_sharpe,
        "worst_regime": worst_regime,
        "worst_sharpe": worst_sharpe,
        "sharpe_spread": sharpe_spread,
        "dominant_regime": dominant_regime,
        "n_regimes_positive": len(positive),
        "n_regimes_negative": len(negative),
    })

    if len(positive) == 0:
        result["regime_robustness"] = "fragile"
        result["is_regime_concentrated"] = True
        result["message"] = (
            "No regime produces a positive Sharpe; the strategy has no "
            "regime-diversified edge."
        )
    elif len(positive) == 1:
        result["regime_robustness"] = "fragile"
        result["is_regime_concentrated"] = True
        result["message"] = (
            "The edge is concentrated in a single regime "
            f"({best_regime}); performance is regime-dependent and may not "
            "survive a regime change."
        )
    elif sharpe_spread >= sharpe_spread_threshold:
        result["regime_robustness"] = "moderate"
        result["is_regime_concentrated"] = False
        result["message"] = (
            "Multiple regimes produce a positive Sharpe, but the spread "
            "between the best and worst regime is wide; performance is "
            "inconsistent across regimes."
        )
    else:
        result["regime_robustness"] = "robust"
        result["is_regime_concentrated"] = False
        result["message"] = (
            "Multiple regimes produce a positive Sharpe with a narrow "
            "spread; the edge is diversified across regimes."
        )

    return result


if __name__ == "__main__":
    # Demo
    import tempfile

    dates = pd.date_range("2020-01-01", periods=500, freq="B")
    np.random.seed(42)

    # Generate synthetic market with regime changes
    # Bull market: higher drift, lower vol
    # Bear market: negative drift, higher vol
    # Sideways: near-zero drift, medium vol
    regime_lengths = [100, 150, 100, 150]
    returns_list = []
    for i, length in enumerate(regime_lengths):
        if i % 3 == 0:  # Bull
            mu, sigma = 0.001, 0.01
        elif i % 3 == 1:  # Bear
            mu, sigma = -0.0005, 0.02
        else:  # Sideways
            mu, sigma = 0.0001, 0.015
        returns_list.append(np.random.normal(mu, sigma, length))

    market_returns = np.concatenate(returns_list)
    market_prices = 100 * np.exp(np.cumsum(market_returns))

    market_data = pd.DataFrame({
        "close": market_prices,
    }, index=dates[:len(market_prices)])

    # Strategy returns (some alpha in bull, negative in bear)
    strategy_returns = market_returns * 0.5 + np.random.normal(0.0002, 0.005, len(market_returns))
    strategy_returns = pd.Series(strategy_returns, index=market_data.index)

    print("Testing regime detection...")
    config = RegimeConfig(trend_ma_short=20, trend_ma_long=60, trend_threshold=0.01)

    summary = regime_performance_summary(strategy_returns, market_data["close"], config)

    print("\nTrend Regime Performance:")
    for regime, metrics in summary["trend_regime_performance"].items():
        print(f"  {regime}: Sharpe={metrics['sharpe_ratio']:.3f}, Return={metrics['annualized_return']:.2%}, n={metrics['n_observations']}")

    print("\nVolatility Regime Performance:")
    for regime, metrics in summary["volatility_regime_performance"].items():
        print(f"  {regime}: Sharpe={metrics['sharpe_ratio']:.3f}, Return={metrics['annualized_return']:.2%}, n={metrics['n_observations']}")

    print("\nCombined Regime Performance:")
    for regime, metrics in summary["combined_regime_performance"].items():
        print(f"  {regime}: Sharpe={metrics['sharpe_ratio']:.3f}, Return={metrics['annualized_return']:.2%}, n={metrics['n_observations']}")

    print("\nRegime Periods:")
    for period in summary["regime_periods"]:
        print(f"  {period['regime']}: {period['start_date']} to {period['end_date']} ({period['length']} bars)")

    print("\nRegime Distribution:")
    for regime, count in summary["regime_distribution"].items():
        print(f"  {regime}: {count} bars")

    print("\nTest passed!")