from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

import pytz
import requests
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
    """Fetch equities market data from yfinance.

    Returns a dict shaped like:
    {
      "equities": {
        "SPY": {"price": float, "prev_close": float, "pct_change": float, "volume": int},
        ...
      },
      "fetched_at_et": "YYYY-MM-DD HH:MM ET"
    }

    (Crypto is handled separately via CoinGecko in bot/crypto_data.py.)
    """

    now_et = datetime.now(ET_TZ)
    fetched_at_et = now_et.strftime("%Y-%m-%d %H:%M ET")

    equities_tickers = ["SPY", "QQQ", "DIA", "^VIX"]

    equities: dict[str, Any] = {}

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

    return {
        "equities": equities,
        "fetched_at_et": fetched_at_et,
    }


def fetch_macro_context() -> dict[str, Any]:
    """Fetch macro context: 10Y Treasury yield, DXY, Fear & Greed Index.

    Each field is fetched independently — if one fails, the others still return.
    """
    print("[market] Fetching macro context (TNX, DXY, Fear & Greed)...")

    result: dict[str, Any] = {
        "treasury_10y": None,
        "dollar_index": None,
        "fear_greed_score": None,
        "fear_greed_rating": None,
    }

    # 10-Year Treasury Yield (^TNX)
    try:
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period="2d")
        if hist is not None and not hist.empty:
            result["treasury_10y"] = round(float(hist["Close"].iloc[-1]), 2)
    except Exception as exc:
        print(f"[market] WARNING: TNX fetch failed — {exc}")

    # US Dollar Index (DX-Y.NYB)
    try:
        dxy = yf.Ticker("DX-Y.NYB")
        hist = dxy.history(period="2d")
        if hist is not None and not hist.empty:
            result["dollar_index"] = round(float(hist["Close"].iloc[-1]), 2)
    except Exception as exc:
        print(f"[market] WARNING: DXY fetch failed — {exc}")

    # CNN Fear & Greed Index
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        resp = requests.get(
            url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if 200 <= resp.status_code < 300:
            data = resp.json()
            fg = data.get("fear_and_greed") or {}
            score = fg.get("score")
            rating = fg.get("rating")
            if score is not None:
                result["fear_greed_score"] = int(round(float(score)))
            if rating:
                result["fear_greed_rating"] = str(rating)
    except Exception as exc:
        print(f"[market] WARNING: Fear & Greed fetch failed — {exc}")

    # Log results
    tnx_str = f"{result['treasury_10y']}%" if result["treasury_10y"] is not None else "N/A"
    dxy_str = str(result["dollar_index"]) if result["dollar_index"] is not None else "N/A"
    fg_str = f"{result['fear_greed_score']} ({result['fear_greed_rating']})" if result["fear_greed_score"] is not None else "N/A"
    print(f"[market] TNX: {tnx_str} | DXY: {dxy_str} | Fear & Greed: {fg_str}")

    return result
