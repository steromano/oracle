"""Shared pytest fixtures for the Oracle test suite.

Task 0 owns this file; later tasks may add fixtures here as needed. It provides
an isolated on-disk state root so ledger/benchmark tests never touch the real
`data/` tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def state_root(tmp_path: Path) -> Path:
    """A temporary Oracle state root with the standard subdirectories."""
    for sub in (
        "data/ledger",
        "data/ledger/backtest",
        "data/questions",
        "data/sealed",
        "data/evidence",
        "data/benchmarks",
        "data/benchmarks/calibration",
        "knowledge/priors",
        "knowledge/audits",
        "reports",
        "notebooks",
    ):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path
