#!/usr/bin/env python3
"""
Tests for report generation functionality in performance module.
"""

import json
import os
import sys
import tempfile
import unittest

import numpy as np
import pandas as pd

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from performance import generate_report
from reporting import generate_tear_sheet, generate_parameter_heatmap


class TestReporting(unittest.TestCase):
    def test_generate_report_creates_files_with_metrics(self):
        """Test that generate_report creates output directory and writes both files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = {
                "total_return": 0.1,
                "annualized_return": 0.15,
                "sharpe_ratio": 1.2,
                "total_trades": 2,
                "winning_trades": 1,
                "losing_trades": 1,
                "win_rate": 0.5,
            }
            generate_report(metrics, tmpdir, symbol="SPY", strategy_name="SMA")

            # Check files were created
            metrics_path = os.path.join(tmpdir, "metrics.json")
            report_path = os.path.join(tmpdir, "report.txt")
            self.assertTrue(os.path.exists(metrics_path))
            self.assertTrue(os.path.exists(report_path))

            # Check metrics.json contains the passed metrics
            import json
            with open(metrics_path, "r") as f:
                loaded_metrics = json.load(f)
            self.assertEqual(loaded_metrics["total_return"], 0.1)
            self.assertEqual(loaded_metrics["sharpe_ratio"], 1.2)
            self.assertEqual(loaded_metrics["total_trades"], 2)

    def test_generate_report_contains_expected_headers(self):
        """Test that report.txt contains expected section headers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = {"total_return": 0.05, "sharpe_ratio": 0.8}
            generate_report(metrics, tmpdir, symbol="AAPL", strategy_name="MACD")

            report_path = os.path.join(tmpdir, "report.txt")
            with open(report_path, "r") as f:
                content = f.read()

            self.assertIn("BACKTEST PERFORMANCE REPORT", content)
            self.assertIn("Return Metrics", content)

    def test_generate_report_includes_trade_analytics_when_trades_present(self):
        """Test that report includes Trade-Level Analytics when total_trades present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = {
                "total_return": 0.2,
                "total_trades": 10,
                "winning_trades": 6,
                "losing_trades": 4,
                "win_rate": 0.6,
            }
            generate_report(metrics, tmpdir, symbol="TSLA", strategy_name="RSI")

            report_path = os.path.join(tmpdir, "report.txt")
            with open(report_path, "r") as f:
                content = f.read()

            self.assertIn("BACKTEST PERFORMANCE REPORT", content)
            self.assertIn("Return Metrics", content)
            self.assertIn("Trade-Level Analytics", content)

    def test_generate_report_surfaces_end_of_sample_closes(self):
        """When `trades_closed_at_end` is present, the report surfaces it.

        Regression: the extractor flags a trade `closed_at_end` when its
        exit was forced by the end of the sample rather than by a signal,
        but no consumer previously exposed the flag, so a backtest whose
        ledger is end-of-sample artifact reported nothing about it.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = {
                "total_return": 0.1,
                "total_trades": 4,
                "trades_closed_at_end": 1,
                "pct_trades_closed_at_end": 0.25,
            }
            generate_report(metrics, tmpdir, symbol="SPY", strategy_name="Mom")

            report_path = os.path.join(tmpdir, "report.txt")
            with open(report_path, "r") as f:
                content = f.read()

            self.assertIn("End-of-Sample Closes", content)
            self.assertIn("Trades Closed at End", content)
            self.assertIn("% of Trades Closed at End", content)

    def test_generate_report_omits_end_of_sample_section_when_absent(self):
        """Without `trades_closed_at_end`, the section is omitted entirely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = {
                "total_return": 0.1,
                "total_trades": 4,
            }
            generate_report(metrics, tmpdir, symbol="SPY", strategy_name="Mom")

            report_path = os.path.join(tmpdir, "report.txt")
            with open(report_path, "r") as f:
                content = f.read()

            self.assertNotIn("End-of-Sample Closes", content)

    def test_generate_report_surfaces_deflated_sharpe(self):
        """When `deflated_sharpe` is present, the report surfaces it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = {
                "total_return": 0.1,
                "sharpe_ratio": 0.8,
                "deflated_sharpe": {
                    "deflated_sharpe_ratio": 0.42,
                    "p_value": 0.58,
                    "expected_max_sharpe": 1.5,
                    "z_score": -0.3,
                    "n_trials": 50,
                    "n_observations": 252,
                    "skewness": 0.1,
                    "kurtosis": 3.0,
                },
            }
            generate_report(metrics, tmpdir, symbol="SPY", strategy_name="SMA")

            report_path = os.path.join(tmpdir, "report.txt")
            with open(report_path, "r") as f:
                content = f.read()

            self.assertIn("Multiple-Testing Correction", content)
            self.assertIn("Deflated Sharpe Ratio", content)
            self.assertIn("P-Value", content)
            self.assertIn("Expected Max Sharpe", content)
            self.assertIn("Z-Score", content)
            self.assertIn("Number of Trials", content)
            self.assertIn("Observations", content)
            self.assertIn("50", content)
            self.assertIn("252", content)

    def test_generate_report_omits_deflated_sharpe_section_when_absent(self):
        """Without `deflated_sharpe`, the section is omitted entirely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = {"total_return": 0.1, "sharpe_ratio": 0.8}
            generate_report(metrics, tmpdir, symbol="SPY", strategy_name="SMA")

            report_path = os.path.join(tmpdir, "report.txt")
            with open(report_path, "r") as f:
                content = f.read()

            self.assertNotIn("Multiple-Testing Correction", content)

    def test_generate_report_handles_empty_metrics_dict(self):
        """Test that passing an empty metrics dict does not crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics = {}
            # Should not raise exception
            generate_report(metrics, tmpdir, symbol="ES", strategy_name="Breakout")

            metrics_path = os.path.join(tmpdir, "metrics.json")
            report_path = os.path.join(tmpdir, "report.txt")
            self.assertTrue(os.path.exists(metrics_path))
            self.assertTrue(os.path.exists(report_path))

    def test_generate_report_creates_directory_if_not_exists(self):
        """Test that generate_report creates output directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested_dir = os.path.join(tmpdir, "subdir", "nested")
            metrics = {"total_return": 0.1}
            generate_report(metrics, nested_dir, symbol="QQQ", strategy_name="Momentum")

            self.assertTrue(os.path.exists(nested_dir))
            self.assertTrue(os.path.exists(os.path.join(nested_dir, "metrics.json")))
            self.assertTrue(os.path.exists(os.path.join(nested_dir, "report.txt")))


class TestTearSheet(unittest.TestCase):
    """Smoke tests for generate_tear_sheet (matplotlib optional)."""

    def _make_results(self, periods: int = 60, seed: int = 7) -> dict:
        rng = np.random.default_rng(seed)
        dates = pd.date_range("2020-01-01", periods=periods, freq="B")
        returns = pd.Series(rng.normal(0.0005, 0.015, periods), index=dates)
        equity = (1 + returns).cumprod() * 100000
        return {
            "equity_curve": equity,
            "returns": returns,
            "config": {"initial_capital": 100000},
        }

    def _make_walk_forward_results(self, include_dsr: bool = False) -> dict:
        summary = {
            "n_periods": 2,
            "total_oos_return": 0.10,
            "oos_sharpe": 0.85,
            "oos_volatility": 0.15,
            "win_rate_periods": 0.60,
            "avg_period_return": 0.02,
        }
        if include_dsr:
            summary["deflated_sharpe"] = {
                "deflated_sharpe_ratio": 0.42,
                "p_value": 0.58,
                "expected_max_sharpe": 1.5,
                "z_score": -0.3,
                "n_trials": 20,
                "n_observations": 50,
                "skewness": 0.1,
                "kurtosis": 3.0,
            }
        return {
            "periods": [
                {"best_params": {"period": 10, "exit_period": 5}, "best_sharpe": 1.2},
                {"best_params": {"period": 20, "exit_period": 10}, "best_sharpe": 0.85},
            ],
            "best_params_per_period": [
                {"period": 10, "exit_period": 5},
                {"period": 20, "exit_period": 10},
            ],
            "oos_returns": pd.Series(
                [0.01, 0.02, -0.01, 0.03, -0.005],
                index=pd.date_range("2020-01-01", periods=5, freq="B"),
            ),
            "summary": summary,
        }

    def _make_cpcv_results(self, include_dsr: bool = False) -> dict:
        summary = {
            "n_folds": 3,
            "total_oos_return": 0.08,
            "oos_sharpe": 0.72,
            "overfitting_risk": "low",
            "avg_param_stability": 0.67,
        }
        if include_dsr:
            summary["deflated_sharpe"] = {
                "deflated_sharpe_ratio": 0.38,
                "p_value": 0.62,
                "expected_max_sharpe": 1.4,
                "n_trials": 15,
                "n_observations": 45,
                "skewness": 0.05,
                "kurtosis": 3.1,
                "z_score": -0.5,
            }
        return {
            "folds": [
                {"fold": 0, "best_params": {"period": 10}, "best_sharpe": 1.1},
                {"fold": 1, "best_params": {"period": 10}, "best_sharpe": 0.95},
                {"fold": 2, "best_params": {"period": 20}, "best_sharpe": 0.88},
            ],
            "best_params_per_fold": [
                {"period": 10}, {"period": 10}, {"period": 20}
            ],
            "oos_returns": pd.Series(
                [0.01, 0.02, -0.01, 0.03, -0.005],
                index=pd.date_range("2020-01-01", periods=5, freq="B"),
            ),
            "summary": summary,
            "param_stability": {
                "period": {
                    "unique_values": 2,
                    "most_common": 10,
                    "stability_ratio": 0.67,
                },
            },
        }

    def _make_monte_carlo_results(self) -> dict:
        dates = pd.date_range("2020-01-01", periods=5, freq="B")
        return {
            "simulated_equity_curves": [
                pd.Series([1.0, 1.02, 0.99, 1.05, 1.03], index=dates),
                pd.Series([1.0, 0.98, 1.01, 1.02, 0.99], index=dates),
                pd.Series([1.0, 1.05, 1.03, 1.07, 1.06], index=dates),
            ],
            "metric_distributions": {"sharpe_ratio": np.array([0.8, 0.9, 1.0])},
            "confidence_intervals": {
                "sharpe_ratio": {
                    0.90: (0.5, 1.2),
                    0.95: (0.3, 1.5),
                    0.99: (0.1, 2.0),
                },
                "total_return": {
                    0.90: (0.05, 0.15),
                    0.95: (0.02, 0.20),
                    0.99: (0.01, 0.30),
                },
            },
            "probability_of_ruin": 0.03,
            "ruin_threshold": 0.5,
            "summary": {
                "sharpe_ratio": {
                    "mean": 0.85, "std": 0.1, "median": 0.84, "min": 0.5, "max": 1.2,
                },
                "total_return": {
                    "mean": 0.10, "std": 0.03, "median": 0.09, "min": 0.02, "max": 0.18,
                },
            },
            "n_simulations": 3,
            "base_observations": 5,
        }

    def test_generate_tear_sheet_creates_html_and_summary(self):
        """Tear sheet writes HTML and JSON summary files even without matplotlib."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            metrics = {"total_return": 0.1, "total_trades": 5, "win_rate": 0.6}
            html_path = generate_tear_sheet(
                results, metrics, tmpdir, symbol="SPY", strategy_name="SMA"
            )
            self.assertTrue(os.path.exists(html_path))
            self.assertTrue(html_path.endswith("tear_sheet.html"))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "tear_sheet_summary.json")))
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertEqual(summary["symbol"], "SPY")
            self.assertEqual(summary["strategy"], "SMA")

    def test_generate_tear_sheet_surfaces_deflated_sharpe(self):
        """The tear sheet renders the DSR and surfaces it in the JSON summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            metrics = {
                "total_return": 0.1,
                "deflated_sharpe": {
                    "deflated_sharpe_ratio": 0.42,
                    "p_value": 0.58,
                    "expected_max_sharpe": 1.5,
                    "z_score": -0.3,
                    "n_trials": 50,
                    "n_observations": 252,
                    "skewness": 0.1,
                    "kurtosis": 3.0,
                },
            }
            html_path = generate_tear_sheet(
                results, metrics, tmpdir, symbol="SPY", strategy_name="SMA"
            )
            with open(html_path, "r") as f:
                html = f.read()

            self.assertIn("Multiple-Testing Correction", html)
            self.assertIn("Deflated Sharpe Ratio", html)
            self.assertIn("Number of Trials", html)
            self.assertIn("Observations", html)

            # The DSR is a dict, so it is filtered out of the scalar-only
            # `metrics` field and surfaced as a top-level summary key.
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertIn("deflated_sharpe", summary)
            self.assertEqual(summary["deflated_sharpe"]["n_trials"], 50)
            self.assertAlmostEqual(
                summary["deflated_sharpe"]["deflated_sharpe_ratio"], 0.42
            )

    def test_generate_tear_sheet_omits_deflated_sharpe_when_absent(self):
        """Without `deflated_sharpe`, the section and summary key are absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            metrics = {"total_return": 0.1}
            html_path = generate_tear_sheet(
                results, metrics, tmpdir, symbol="SPY", strategy_name="SMA"
            )
            with open(html_path, "r") as f:
                html = f.read()

            self.assertNotIn("Multiple-Testing Correction", html)

            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertNotIn("deflated_sharpe", summary)

    def test_generate_tear_sheet_includes_benchmark_section(self):
        """The tear sheet renders the Benchmark Comparison section (including
        annualized return) and surfaces benchmark metrics in the JSON summary
        when benchmark_total_return is present in metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            metrics = {
                "total_return": 0.10,
                "benchmark_total_return": 0.12,
                "benchmark_annualized_return": 0.18,
                "correlation_with_benchmark": 0.85,
                "alpha": 0.02,
                "beta": 1.1,
                "alpha_tstat": 1.9,
                "alpha_pvalue": 0.06,
                "r_squared": 0.72,
            }
            html_path = generate_tear_sheet(
                results, metrics, tmpdir,
                symbol="SPY", strategy_name="SMA", save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertIn("Benchmark Comparison", html)
            self.assertIn("Benchmark Total Return", html)
            self.assertIn("Benchmark Annualized Return", html)
            self.assertIn("Correlation", html)
            self.assertIn("Alpha", html)
            self.assertIn("Beta", html)
            self.assertIn("Alpha t-statistic", html)
            self.assertIn("Alpha p-value", html)
            self.assertIn("R-squared", html)

            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            for key in ("benchmark_total_return", "benchmark_annualized_return",
                        "correlation_with_benchmark", "alpha", "beta"):
                self.assertIn(key, summary["metrics"])
            for key in ("alpha_tstat", "alpha_pvalue", "r_squared"):
                self.assertIn(key, summary["metrics"])

    def test_generate_tear_sheet_omits_benchmark_when_absent(self):
        """Without benchmark metrics, the Benchmark Comparison section is omitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            metrics = {"total_return": 0.10}
            html_path = generate_tear_sheet(
                results, metrics, tmpdir,
                symbol="SPY", strategy_name="SMA", save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertNotIn("Benchmark Comparison", html)

    def _make_provenance(self, symbol="SPY", checksum="abc123def456"):
        """Build a DataProvenance-style dict matching DataProvenance.to_dict()."""
        return {
            "source_path": "data.csv",
            "load_timestamp": "2026-01-01T00:00:00Z",
            "file_format": ".csv",
            "file_size_bytes": 1234,
            "symbol_filter": symbol,
            "start_date_filter": None,
            "end_date_filter": None,
            "original_shape": [500, 6],
            "final_shape": [500, 6],
            "columns_original": ["date", "open", "high", "low", "close", "volume"],
            "columns_final": ["date", "open", "high", "low", "close", "volume"],
            "date_range_original": ["2020-01-01", "2022-01-01"],
            "date_range_final": ["2020-01-01", "2022-01-01"],
            "validation_passed": True,
            "validation_messages": [],
            "transformations_applied": ["sorted_by_date"],
            "checksum": checksum,
        }

    def test_generate_tear_sheet_includes_data_provenance_section(self):
        """Data Provenance section renders source path, checksum, date range,
        filters, and validation outcome when results['data_provenance'] is present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            prov = self._make_provenance(symbol="SPY", checksum="deadbeef")
            results["data_provenance"] = prov
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir,
                symbol="SPY", strategy_name="SMA", save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertIn("Data Provenance", html)
            self.assertIn("source_path", html)
            self.assertIn("data.csv", html)
            self.assertIn("checksum", html)
            self.assertIn("deadbeef", html)
            self.assertIn("date_range_final", html)
            self.assertIn("symbol_filter", html)
            self.assertIn("validation_passed", html)
            self.assertIn("validation_messages", html)
            self.assertIn("transformations_applied", html)

            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertIn("data_provenance", summary)
            self.assertEqual(summary["data_provenance"]["source_path"], "data.csv")
            self.assertEqual(summary["data_provenance"]["checksum"], "deadbeef")

    def test_generate_tear_sheet_omits_data_provenance_when_absent(self):
        """Without results['data_provenance'], the section and summary key are omitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir,
                symbol="SPY", strategy_name="SMA", save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertNotIn("Data Provenance", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertNotIn("data_provenance", summary)
            self.assertNotIn("point_in_time_validation", summary)

    def test_generate_tear_sheet_data_provenance_per_symbol_panel(self):
        """Per-symbol panel provenance renders each symbol's fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            provs = {
                "SPY": self._make_provenance(symbol="SPY", checksum="ck1"),
                "TLT": self._make_provenance(symbol="TLT", checksum="ck2"),
            }
            results["data_provenance"] = provs
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir,
                symbol="SPY", strategy_name="SMA", save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertIn("Data Provenance", html)
            self.assertIn("SPY / source_path", html)
            self.assertIn("TLT / source_path", html)
            self.assertIn("ck1", html)
            self.assertIn("ck2", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertIn("data_provenance", summary)
            self.assertIn("SPY", summary["data_provenance"])
            self.assertIn("TLT", summary["data_provenance"])

    def test_generate_tear_sheet_surfaces_point_in_time_validation(self):
        """Point-in-time validation outcome at results level is surfaced
        in both HTML and JSON summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            results["data_provenance"] = self._make_provenance(checksum="deadbeef")
            results["point_in_time_validation"] = {
                "passed": True, "violations": [], "warnings": [],
            }
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir,
                symbol="SPY", strategy_name="SMA", save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertIn("point_in_time", html)
            self.assertIn("passed", html)
            self.assertIn("violations", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertIn("point_in_time_validation", summary)
            self.assertTrue(summary["point_in_time_validation"]["passed"])

    def test_generate_tear_sheet_handles_missing_equity(self):
        """Tear sheet does not crash when results lack equity_curve."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = {"returns": pd.Series([0.01, -0.02, 0.005])}
            html_path = generate_tear_sheet(
                results, {}, tmpdir, symbol="ES", strategy_name="Breakout"
            )
            self.assertTrue(os.path.exists(html_path))

    def test_generate_tear_sheet_creates_output_dir(self):
        """Tear sheet creates nested output directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "a", "b", "c")
            results = self._make_results()
            html_path = generate_tear_sheet(
                results, {"total_return": 0.05}, nested, symbol="QQQ"
            )
            self.assertTrue(os.path.exists(nested))
            self.assertTrue(os.path.exists(html_path))

    def test_generate_tear_sheet_includes_parameter_heatmap_when_two_varying_params(self):
        """Integration test: tear sheet generates and embeds parameter_heatmap.png
        when results['parameter_optimization'] has exactly two varying parameters
        and save_plots=True.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create synthetic parameter optimization results with 2 varying params (period, exit_period)
            param_opt_results = [
                {
                    "params": {"period": 10, "exit_period": 5},
                    "sharpe_ratio": 1.2,
                    "total_return": 0.15,
                    "n_periods": 100,
                },
                {
                    "params": {"period": 10, "exit_period": 10},
                    "sharpe_ratio": 0.8,
                    "total_return": 0.10,
                    "n_periods": 100,
                },
                {
                    "params": {"period": 20, "exit_period": 5},
                    "sharpe_ratio": 1.5,
                    "total_return": 0.20,
                    "n_periods": 100,
                },
                {
                    "params": {"period": 20, "exit_period": 10},
                    "sharpe_ratio": 0.5,
                    "total_return": 0.05,
                    "n_periods": 100,
                },
            ]

            results = self._make_results()
            results["parameter_optimization"] = param_opt_results
            metrics = {"total_return": 0.1, "total_trades": 5, "win_rate": 0.6}

            html_path = generate_tear_sheet(
                results, metrics, tmpdir, symbol="SPY", strategy_name="Donchian", save_plots=True
            )

            # Verify heatmap file was created
            heatmap_path = os.path.join(tmpdir, "parameter_heatmap.png")
            self.assertTrue(os.path.exists(heatmap_path), "parameter_heatmap.png should be created")

            # Verify heatmap is referenced in the HTML
            with open(html_path, "r") as f:
                html = f.read()
            self.assertIn("parameter_heatmap.png", html, "HTML should reference the heatmap image")

            # Verify plot_files in JSON summary includes the heatmap
            summary_path = os.path.join(tmpdir, "tear_sheet_summary.json")
            with open(summary_path, "r") as f:
                summary = json.load(f)
            self.assertIn("plot_files", summary)
            plot_files = summary["plot_files"]
            self.assertTrue(any("parameter_heatmap.png" in p for p in plot_files),
                           "JSON summary should list parameter_heatmap.png")

    def test_generate_tear_sheet_omits_heatmap_when_not_two_varying_params(self):
        """Tear sheet should not create heatmap when parameter_optimization
        has fewer or more than two varying parameters.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # Only one varying parameter
            param_opt_results = [
                {"params": {"period": 10}, "sharpe_ratio": 1.0},
                {"params": {"period": 20}, "sharpe_ratio": 1.2},
            ]

            results = self._make_results()
            results["parameter_optimization"] = param_opt_results
            metrics = {"total_return": 0.1}

            html_path = generate_tear_sheet(
                results, metrics, tmpdir, symbol="SPY", strategy_name="SMA", save_plots=True
            )

            heatmap_path = os.path.join(tmpdir, "parameter_heatmap.png")
            self.assertFalse(os.path.exists(heatmap_path),
                           "parameter_heatmap.png should NOT be created for non-2D grid")

            with open(html_path, "r") as f:
                html = f.read()
            self.assertNotIn("parameter_heatmap.png", html,
                           "HTML should not reference heatmap when grid is invalid")

    def test_tear_sheet_includes_walk_forward_section(self):
        """Walk-forward analysis results are rendered as an HTML section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            metrics = {"total_return": 0.1, "total_trades": 5}
            wf = self._make_walk_forward_results(include_dsr=True)
            html_path = generate_tear_sheet(
                results, metrics, tmpdir, symbol="SPY", strategy_name="SMA",
                analysis_results={"walk_forward": wf}, save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertIn("Walk-Forward Analysis", html)
            self.assertIn("Number of Periods", html)
            self.assertIn("Total OOS Return", html)
            self.assertIn("OOS Sharpe Ratio", html)
            self.assertIn("Best Parameters Per Period", html)
            self.assertIn("Walk-Forward Multiple-Testing Correction", html)
            self.assertIn("Deflated Sharpe Ratio", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertIn("walk_forward", summary)
            self.assertEqual(summary["walk_forward"]["summary"]["n_periods"], 2)
            self.assertIn("best_params_per_period", summary["walk_forward"])

    def test_tear_sheet_omits_walk_forward_when_absent(self):
        """Without walk_forward analysis, the section is omitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir, symbol="SPY",
                save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertNotIn("Walk-Forward Analysis", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertNotIn("walk_forward", summary)

    def test_tear_sheet_includes_cpcv_section(self):
        """CPCV analysis results are rendered as an HTML section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            cpcv = self._make_cpcv_results(include_dsr=True)
            html_path = generate_tear_sheet(
                results, {"total_return": 0.08}, tmpdir,
                symbol="SPY", strategy_name="SMA",
                analysis_results={"cpcv": cpcv}, save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertIn("CPCV Analysis", html)
            self.assertIn("Number of Folds", html)
            self.assertIn("Overfitting Risk", html)
            self.assertIn("low", html)
            self.assertIn("Parameter Stability", html)
            self.assertIn("Best Parameters Per Fold", html)
            self.assertIn("CPCV Multiple-Testing Correction", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertIn("cpcv", summary)
            self.assertEqual(summary["cpcv"]["summary"]["n_folds"], 3)
            self.assertIn("param_stability", summary["cpcv"])

    def test_tear_sheet_omits_cpcv_when_absent(self):
        """Without CPCV analysis, the section is omitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir, symbol="SPY",
                save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertNotIn("CPCV Analysis", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertNotIn("cpcv", summary)

    def test_tear_sheet_includes_monte_carlo_section(self):
        """Monte Carlo results are rendered as an HTML section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            mc = self._make_monte_carlo_results()
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir,
                symbol="SPY", strategy_name="SMA",
                analysis_results={"monte_carlo": mc}, save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertIn("Monte Carlo Simulation", html)
            self.assertIn("Number of Simulations", html)
            self.assertIn("Probability of Ruin", html)
            self.assertIn("Confidence Intervals", html)
            self.assertIn("Metric Distributions", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertIn("monte_carlo", summary)
            self.assertEqual(summary["monte_carlo"]["n_simulations"], 3)
            self.assertAlmostEqual(summary["monte_carlo"]["probability_of_ruin"], 0.03)

    def test_tear_sheet_omits_monte_carlo_when_absent(self):
        """Without Monte Carlo analysis, the section is omitted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir, symbol="SPY",
                save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertNotIn("Monte Carlo Simulation", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertNotIn("monte_carlo", summary)

    def test_tear_sheet_mc_fan_chart_generated(self):
        """Monte Carlo equity fan chart is generated and embedded when save_plots=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            mc = self._make_monte_carlo_results()
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir,
                symbol="SPY", strategy_name="SMA",
                analysis_results={"monte_carlo": mc}, save_plots=True,
            )
            fan_path = os.path.join(tmpdir, "monte_carlo_equity_curve.png")
            self.assertTrue(
                os.path.exists(fan_path),
                "monte_carlo_equity_curve.png should be created",
            )
            with open(html_path) as f:
                html = f.read()
            self.assertIn("monte_carlo_equity_curve.png", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertTrue(
                any("monte_carlo_equity_curve.png" in p for p in summary["plot_files"]),
                "JSON summary should list monte_carlo_equity_curve.png",
            )

    def test_tear_sheet_backward_compatible_without_analysis_results(self):
        """generate_tear_sheet works identically when analysis_results is not passed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            metrics = {"total_return": 0.1, "sharpe_ratio": 1.2, "total_trades": 5}
            html_path = generate_tear_sheet(
                results, metrics, tmpdir, symbol="SPY", strategy_name="SMA",
                save_plots=False,
            )
            self.assertTrue(os.path.exists(html_path))
            self.assertTrue(os.path.exists(os.path.join(tmpdir, "tear_sheet_summary.json")))
            with open(html_path) as f:
                html = f.read()
            self.assertNotIn("Walk-Forward Analysis", html)
            self.assertNotIn("CPCV Analysis", html)
            self.assertNotIn("Monte Carlo Simulation", html)

    def test_tear_sheet_mc_section_without_equity_curves(self):
        """Monte Carlo HTML section renders even when simulated_equity_curves is absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            mc = self._make_monte_carlo_results()
            del mc["simulated_equity_curves"]
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir,
                symbol="SPY", strategy_name="SMA",
                analysis_results={"monte_carlo": mc}, save_plots=False,
            )
            with open(html_path) as f:
                html = f.read()
            self.assertIn("Monte Carlo Simulation", html)
            self.assertIn("Probability of Ruin", html)

    def test_tear_sheet_wf_equity_curve_generated(self):
        """Walk-forward equity curve is generated and embedded when save_plots=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            wf = self._make_walk_forward_results()
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir,
                symbol="SPY", strategy_name="SMA",
                analysis_results={"walk_forward": wf}, save_plots=True,
            )
            wf_path = os.path.join(tmpdir, "walk_forward_equity_curve.png")
            self.assertTrue(
                os.path.exists(wf_path),
                "walk_forward_equity_curve.png should be created",
            )
            with open(html_path) as f:
                html = f.read()
            self.assertIn("walk_forward_equity_curve.png", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertTrue(
                any("walk_forward_equity_curve.png" in p for p in summary["plot_files"]),
                "JSON summary should list walk_forward_equity_curve.png",
            )

    def test_tear_sheet_cpcv_equity_curve_generated(self):
        """CPCV equity curve is generated and embedded when save_plots=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            cpcv = self._make_cpcv_results()
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir,
                symbol="SPY", strategy_name="SMA",
                analysis_results={"cpcv": cpcv}, save_plots=True,
            )
            cpcv_path = os.path.join(tmpdir, "cpcv_equity_curve.png")
            self.assertTrue(
                os.path.exists(cpcv_path),
                "cpcv_equity_curve.png should be created",
            )
            with open(html_path) as f:
                html = f.read()
            self.assertIn("cpcv_equity_curve.png", html)
            with open(os.path.join(tmpdir, "tear_sheet_summary.json")) as f:
                summary = json.load(f)
            self.assertTrue(
                any("cpcv_equity_curve.png" in p for p in summary["plot_files"]),
                "JSON summary should list cpcv_equity_curve.png",
            )

    def test_tear_sheet_omits_wf_equity_curve_when_no_oos_returns(self):
        """Walk-forward equity curve is not created when oos_returns is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            wf = self._make_walk_forward_results()
            wf["oos_returns"] = pd.Series(dtype=float)  # Empty returns
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir,
                symbol="SPY", strategy_name="SMA",
                analysis_results={"walk_forward": wf}, save_plots=True,
            )
            wf_path = os.path.join(tmpdir, "walk_forward_equity_curve.png")
            self.assertFalse(
                os.path.exists(wf_path),
                "walk_forward_equity_curve.png should NOT be created for empty oos_returns",
            )

    def test_tear_sheet_omits_cpcv_equity_curve_when_no_oos_returns(self):
        """CPCV equity curve is not created when oos_returns is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            results = self._make_results()
            cpcv = self._make_cpcv_results()
            cpcv["oos_returns"] = pd.Series(dtype=float)  # Empty returns
            html_path = generate_tear_sheet(
                results, {"total_return": 0.1}, tmpdir,
                symbol="SPY", strategy_name="SMA",
                analysis_results={"cpcv": cpcv}, save_plots=True,
            )
            cpcv_path = os.path.join(tmpdir, "cpcv_equity_curve.png")
            self.assertFalse(
                os.path.exists(cpcv_path),
                "cpcv_equity_curve.png should NOT be created for empty oos_returns",
            )


class TestParameterHeatmap(unittest.TestCase):
    """Tests for generate_parameter_heatmap function."""

    def _make_optimization_results(self) -> list:
        """Create synthetic parameter optimization results for a 2x2 grid."""
        return [
            {
                "params": {"period": 10, "exit_period": 5},
                "sharpe_ratio": 1.2,
                "total_return": 0.15,
                "n_periods": 100,
                "deflated_sharpe": {
                    "deflated_sharpe_ratio": 0.8,
                    "p_value": 0.2,
                    "expected_max_sharpe": 1.5,
                    "z_score": 0.5,
                    "n_trials": 4,
                    "n_observations": 100,
                    "skewness": 0.1,
                    "kurtosis": 3.0,
                },
            },
            {
                "params": {"period": 10, "exit_period": 10},
                "sharpe_ratio": 0.8,
                "total_return": 0.10,
                "n_periods": 100,
                "deflated_sharpe": {
                    "deflated_sharpe_ratio": 0.4,
                    "p_value": 0.6,
                    "expected_max_sharpe": 1.5,
                    "z_score": -0.2,
                    "n_trials": 4,
                    "n_observations": 100,
                    "skewness": 0.1,
                    "kurtosis": 3.0,
                },
            },
            {
                "params": {"period": 20, "exit_period": 5},
                "sharpe_ratio": 1.5,
                "total_return": 0.20,
                "n_periods": 100,
                "deflated_sharpe": {
                    "deflated_sharpe_ratio": 1.0,
                    "p_value": 0.1,
                    "expected_max_sharpe": 1.5,
                    "z_score": 1.0,
                    "n_trials": 4,
                    "n_observations": 100,
                    "skewness": 0.1,
                    "kurtosis": 3.0,
                },
            },
            {
                "params": {"period": 20, "exit_period": 10},
                "sharpe_ratio": 0.5,
                "total_return": 0.05,
                "n_periods": 100,
                "deflated_sharpe": {
                    "deflated_sharpe_ratio": 0.2,
                    "p_value": 0.8,
                    "expected_max_sharpe": 1.5,
                    "z_score": -0.8,
                    "n_trials": 4,
                    "n_observations": 100,
                    "skewness": 0.1,
                    "kurtosis": 3.0,
                },
            },
        ]

    def _make_degenerate_optimization_results(self) -> list:
        """Create synthetic results with constant returns (degenerate DSR)."""
        return [
            {
                "params": {"period": 10, "exit_period": 5},
                "sharpe_ratio": 0.0,
                "total_return": 0.0,
                "n_periods": 100,
                "deflated_sharpe": {
                    "deflated_sharpe_ratio": 0.0,
                    "p_value": 1.0,
                    "expected_max_sharpe": 1.5,
                    "z_score": None,
                    "n_trials": 4,
                    "n_observations": 100,
                    "skewness": 0.0,
                    "kurtosis": 3.0,
                },
            },
            {
                "params": {"period": 10, "exit_period": 10},
                "sharpe_ratio": 0.0,
                "total_return": 0.0,
                "n_periods": 100,
                "deflated_sharpe": {
                    "deflated_sharpe_ratio": 0.0,
                    "p_value": 1.0,
                    "expected_max_sharpe": 1.5,
                    "z_score": None,
                    "n_trials": 4,
                    "n_observations": 100,
                    "skewness": 0.0,
                    "kurtosis": 3.0,
                },
            },
            {
                "params": {"period": 20, "exit_period": 5},
                "sharpe_ratio": 0.0,
                "total_return": 0.0,
                "n_periods": 100,
                "deflated_sharpe": {
                    "deflated_sharpe_ratio": 0.0,
                    "p_value": 1.0,
                    "expected_max_sharpe": 1.5,
                    "z_score": None,
                    "n_trials": 4,
                    "n_observations": 100,
                    "skewness": 0.0,
                    "kurtosis": 3.0,
                },
            },
            {
                "params": {"period": 20, "exit_period": 10},
                "sharpe_ratio": 0.0,
                "total_return": 0.0,
                "n_periods": 100,
                "deflated_sharpe": {
                    "deflated_sharpe_ratio": 0.0,
                    "p_value": 1.0,
                    "expected_max_sharpe": 1.5,
                    "z_score": None,
                    "n_trials": 4,
                    "n_observations": 100,
                    "skewness": 0.0,
                    "kurtosis": 3.0,
                },
            },
        ]

    def test_generate_parameter_heatmap_creates_figure(self):
        """Test that heatmap figure is created for valid 2D grid."""
        results = self._make_optimization_results()
        fig = generate_parameter_heatmap(
            results, param_x="period", param_y="exit_period", metric="sharpe_ratio"
        )
        self.assertIsNotNone(fig)
        # Clean up
        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_generate_parameter_heatmap_saves_to_file(self):
        """Test that heatmap saves to file when save_path provided."""
        import tempfile
        results = self._make_optimization_results()
        with tempfile.TemporaryDirectory() as tmpdir:
            save_path = os.path.join(tmpdir, "heatmap.png")
            fig = generate_parameter_heatmap(
                results,
                param_x="period",
                param_y="exit_period",
                metric="sharpe_ratio",
                save_path=save_path,
            )
            self.assertIsNotNone(fig)
            self.assertTrue(os.path.exists(save_path))
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_generate_parameter_heatmap_handles_degenerate_dsr(self):
        """Test heatmap handles degenerate DSR dict (z_score=None) without crash."""
        results = self._make_degenerate_optimization_results()
        fig = generate_parameter_heatmap(
            results,
            param_x="period",
            param_y="exit_period",
            metric="deflated_sharpe_ratio",
        )
        # Should not crash; figure created but all values NaN so masked
        self.assertIsNotNone(fig)
        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_generate_parameter_heatmap_returns_none_for_non_rectangular_grid(self):
        """Test returns None when grid doesn't have exactly two varying params."""
        # Only one varying parameter
        results = [
            {"params": {"period": 10}, "sharpe_ratio": 1.0},
            {"params": {"period": 20}, "sharpe_ratio": 1.2},
        ]
        fig = generate_parameter_heatmap(results, param_x="period", param_y="exit_period")
        self.assertIsNone(fig)

        # Three varying parameters
        results = [
            {"params": {"a": 1, "b": 2, "c": 3}, "sharpe_ratio": 1.0},
            {"params": {"a": 2, "b": 2, "c": 3}, "sharpe_ratio": 1.2},
        ]
        fig = generate_parameter_heatmap(results, param_x="a", param_y="b")
        self.assertIsNone(fig)

    def test_generate_parameter_heatmap_returns_none_for_empty_results(self):
        """Test returns None for empty results list."""
        fig = generate_parameter_heatmap([], param_x="a", param_y="b")
        self.assertIsNone(fig)

    def test_generate_parameter_heatmap_supports_total_return_metric(self):
        """Test heatmap works with total_return metric."""
        results = self._make_optimization_results()
        fig = generate_parameter_heatmap(
            results, param_x="period", param_y="exit_period", metric="total_return"
        )
        self.assertIsNotNone(fig)
        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_generate_parameter_heatmap_custom_cmap_and_title(self):
        """Test heatmap accepts custom cmap and title."""
        results = self._make_optimization_results()
        fig = generate_parameter_heatmap(
            results,
            param_x="period",
            param_y="exit_period",
            metric="sharpe_ratio",
            cmap="viridis",
            title="Custom Title",
        )
        self.assertIsNotNone(fig)
        self.assertEqual(fig.axes[0].get_title(), "Custom Title")
        import matplotlib.pyplot as plt
        plt.close(fig)


if __name__ == "__main__":
    unittest.main()
