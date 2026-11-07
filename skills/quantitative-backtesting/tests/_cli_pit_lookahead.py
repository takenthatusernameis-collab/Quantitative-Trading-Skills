#!/usr/bin/env python3
"""Test-only wrapper: registers a look-ahead strategy into STRATEGY_REGISTRY,
then invokes ``walk_forward.main()`` with the remaining argv.

The production ``STRATEGY_REGISTRY`` has no hook for a look-ahead signal, so
CLI-level injection of one is otherwise impossible. This module registers the
strategy *only inside the test harness process*; it is not added to the
shipped registry and is imported only by ``test_point_in_time_strict_cli_walk_forward.py``.

The strategy emits ``signal[t] = sign(close[t+1] - close[t])`` (next-period
return sign), a deterministic look-ahead positive control.

Usage:
    python _cli_pit_lookahead.py <walk_forward subcommand> <walk_forward args...>

Offline, committed fixtures only; no live network.
"""
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pandas as pd  # noqa: E402

import walk_forward  # noqa: E402
from strategy_builder import STRATEGY_REGISTRY, StrategyConfig  # noqa: E402


class _PitLookaheadStrategy:
    def __init__(self, config):
        self.config = config
        self.name = config.name
        self.parameters = config.parameters or {}

    def generate_signals(self, data):
        close = data["close"] if isinstance(data, pd.DataFrame) else data["close"]
        nxt = close.pct_change().shift(-1)
        return (nxt > 0).astype(float).reindex(data.index).fillna(0.0)


STRATEGY_REGISTRY["pit_lookahead"] = _PitLookaheadStrategy


def main():
    # argv[0] is this wrapper; the rest are the walk_forward CLI args.
    sys.argv = [str(SCRIPTS_DIR / "walk_forward.py")] + sys.argv[1:]
    try:
        code = walk_forward.main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    except ValueError as exc:
        # Strict PIT abort raises ValueError from walk_forward_analysis /
        # out_of_sample_validation; surface the violation message on stderr
        # so the CLI exit is machine-auditable.
        print(str(exc), file=sys.stderr)
        code = 1
    sys.exit(code)


if __name__ == "__main__":
    main()
