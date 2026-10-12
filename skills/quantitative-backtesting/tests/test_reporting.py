#!/usr/bin/env python3
"""
Tests for report generation functionality in performance module.
"""

import os
import sys
import tempfile
import unittest

# Add scripts directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from performance import generate_report


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


if __name__ == "__main__":
    unittest.main()
