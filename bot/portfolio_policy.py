"""Versioned policy for the simulated paper portfolio."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioPolicy:
    version: str = "v1"
    initial_capital: float = 10_000.0
    position_allocation_pct: float = 0.10
    max_gross_exposure_pct: float = 0.60
    max_open_gap_pct: float = 0.02
    stop_loss_pct: float = 0.04
    max_holding_sessions: int = 10
    repeat_window_days: int = 5
    slippage_bps: float = 5.0
    eligible_confidence: tuple[str, ...] = ("MEDIUM", "HIGH")
    excluded_tickers: tuple[str, ...] = ("BTC", "ETH", "SOL")


DEFAULT_POLICY = PortfolioPolicy()
