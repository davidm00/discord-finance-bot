from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

import pytz
import yfinance as yf


ET_TZ = pytz.timezone("America/New_York")


def _safe_float(val: Any) -> float | None:
    try:
        if val is None:
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    try:
        if val is None:
            return None
        return int(val)
    except (TypeError, ValueError):
        return None


def _fetch_daily_series(ticker: str):
    t = yf.Ticker(ticker)
    hist = t.history(period="5d", interval="1d")
    return t, hist


def fetch_market_data() -> dict[str, Any]:
    """Fetch equities + crypto market data from yfinance.

    Returns a dict shaped like:
    {
      "equities": { ... },
      "crypto": { ... },
      "fetched_at_et": "YYYY-MM-DD HH:MM ET"
    }
    """

    now_et = datetime.now(ET_TZ)
    fetched_at_et = now_et.strftime("%Y-%m-%d %H:%M ET")

    equities_tickers = ["SPY", "QQQ", "DIA", "^VIX"]
    crypto_tickers = ["BTC-USD", "ETH-USD", "SOL-USD"]

    equities: dict[str, Any] = {}
    crypto: dict[str, Any] = {}

    print("Fetching market data via yfinance...", file=sys.stdout)

    for tk in equities_tickers:
        try:
            t, hist = _fetch_daily_series(tk)
            if hist is None or len(hist) < 2:
                raise ValueError("Insufficient history")

            prev_close = _safe_float(hist["Close"].iloc[-2])
            last_close = _safe_float(hist["Close"].iloc[-1])
            last_vol = _safe_int(hist["Volume"].iloc[-1])

            price = None
            try:
                fi = getattr(t, "fast_info", None)
                if fi:
                    price = _safe_float(fi.get("last_price"))
                    if last_vol is None:
                        last_vol = _safe_int(fi.get("last_volume"))
            except Exception:
                price = None

            if price is None:
                price = last_close

            if prev_close is None or price is None:
                raise ValueError("Missing price data")

            pct_change = ((price - prev_close) / prev_close) * 100.0

            equities[tk] = {
                "price": float(price),
                "prev_close": float(prev_close),
                "pct_change": float(pct_change),
                "volume": int(last_vol) if last_vol is not None else 0,
            }
        except Exception as exc:
            print(f"WARNING: Failed to fetch {tk}: {exc}", file=sys.stderr)
            equities[tk] = None

    for tk in crypto_tickers:
        try:
            t, hist = _fetch_daily_series(tk)
            if hist is None or len(hist) < 2:
                raise ValueError("Insufficient history")

            prev_close = _safe_float(hist["Close"].iloc[-2])
            last_close = _safe_float(hist["Close"].iloc[-1])
            last_vol = _safe_float(hist["Volume"].iloc[-1])

            price = None
            try:
                fi = getattr(t, "fast_info", None)
                if fi:
                    price = _safe_float(fi.get("last_price"))
                    if last_vol is None:
                        last_vol = _safe_float(fi.get("last_volume"))
            except Exception:
                price = None

            if price is None:
                price = last_close

            if prev_close is None or price is None:
                raise ValueError("Missing price data")

            pct_change = ((price - prev_close) / prev_close) * 100.0

            crypto[tk] = {
                "price": float(price),
                "pct_change": float(pct_change),
                "volume": float(last_vol) if last_vol is not None else 0.0,
            }
        except Exception as exc:
            print(f"WARNING: Failed to fetch {tk}: {exc}", file=sys.stderr)
            crypto[tk] = None

    return {
        "equities": equities,
        "crypto": crypto,
        "fetched_at_et": fetched_at_et,
    }
