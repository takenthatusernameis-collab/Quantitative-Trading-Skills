#!/usr/bin/env python3
"""
Simple test to check if we can import strategy_builder
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'skills', 'quantitative-backtesting', 'scripts'))

try:
    import strategy_builder
    print("Successfully imported strategy_builder")
    print(f"Strategy builder location: {strategy_builder.__file__}")
except Exception as e:
    print(f"Failed to import strategy_builder: {e}")
    import traceback
    traceback.print_exc()

try:
    from strategy_builder import build_strategy
    print("Successfully imported build_strategy from strategy_builder")
except Exception as e:
    print(f"Failed to import build_strategy: {e}")
    import traceback
    traceback.print_exc()