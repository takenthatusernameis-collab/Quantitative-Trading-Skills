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
from reporting import generate_tear_sheet


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


if __name__ == "__main__":
    unittest.main()
