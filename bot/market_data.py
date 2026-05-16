from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

import pytz
import requests
import yfinance as yf

from retry_utils import api_retry


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


def _fetch_yahoo_chart_fallback(symbol: str):
    """Direct Yahoo Finance chart API as fallback when yfinance library fails."""
    # Map internal symbols to Yahoo API symbols
    yahoo_symbol = symbol.replace("^", "%5E")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}"
    params = {"range": "5d", "interval": "1d"}
    headers = {"User-Agent": "Mozilla/5.0"}

    resp = requests.get(url, params=params, headers=headers, timeout=10)
    if resp.status_code != 200:
        return None

    data = resp.json()
    result = data.get("chart", {}).get("result")
    if not result:
        return None

    quotes = result[0].get("indicators", {}).get("quote", [{}])[0]
    closes = quotes.get("close", [])
    volumes = quotes.get("volume", [])

    if not closes or len(closes) < 2:
        return None

    # Filter out None values
    valid_closes = [(i, c) for i, c in enumerate(closes) if c is not None]
    if len(valid_closes) < 2:
        return None

    prev_close = valid_closes[-2][1]
    last_close = valid_closes[-1][1]
    last_idx = valid_closes[-1][0]
    last_vol = volumes[last_idx] if last_idx < len(volumes) and volumes[last_idx] is not None else 0

    return {
        "price": float(last_close),
        "prev_close": float(prev_close),
        "volume": int(last_vol),
    }


def _fetch_finnhub_quote_fallback(symbol: str) -> dict | None:
    """Finnhub quote API as a genuinely different data source fallback."""
    import os
    api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        return None

    # Finnhub uses plain symbols, no ^ prefix
    fh_symbol = symbol.replace("^", "")
    url = "https://finnhub.io/api/v1/quote"
    params = {"symbol": fh_symbol, "token": api_key}

    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        current = data.get("c")
        prev_close = data.get("pc")
        if current and prev_close and current > 0 and prev_close > 0:
            return {
                "price": float(current),
                "prev_close": float(prev_close),
                "volume": 0,  # Finnhub quote doesn't include volume
            }
    except Exception:
        pass
    return None


@api_retry
def fetch_equity_with_fallback(symbol: str) -> dict | None:
    """Fetch equity data: yfinance → Yahoo chart API → Finnhub → None."""
    # Attempt 1: yfinance
    try:
        t, hist = _fetch_daily_series(symbol)
        if hist is not None and not hist.empty and "Close" in hist.columns and len(hist) >= 2:
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

            if prev_close is not None and price is not None:
                pct_change = ((price - prev_close) / prev_close) * 100.0
                print(f"[market] {symbol}: fetched via yfinance")
                return {
                    "price": float(price),
                    "prev_close": float(prev_close),
                    "pct_change": float(pct_change),
                    "volume": int(last_vol) if last_vol is not None else 0,
                }
    except Exception as e:
        print(f"[market] WARNING: yfinance failed for {symbol}: {e}")

    # Attempt 2: Direct Yahoo chart API (different code path, same upstream)
    try:
        result = _fetch_yahoo_chart_fallback(symbol)
        if result:
            pct_change = ((result["price"] - result["prev_close"]) / result["prev_close"]) * 100.0
            print(f"[market] {symbol}: fetched via Yahoo chart API fallback")
            return {
                "price": result["price"],
                "prev_close": result["prev_close"],
                "pct_change": float(pct_change),
                "volume": result["volume"],
            }
    except Exception as e:
        print(f"[market] WARNING: Yahoo chart fallback failed for {symbol}: {e}")

    # Attempt 3: Finnhub (genuinely different data source)
    try:
        result = _fetch_finnhub_quote_fallback(symbol)
        if result:
            pct_change = ((result["price"] - result["prev_close"]) / result["prev_close"]) * 100.0
            print(f"[market] {symbol}: fetched via Finnhub fallback")
            return {
                "price": result["price"],
                "prev_close": result["prev_close"],
                "pct_change": float(pct_change),
                "volume": result["volume"],
            }
    except Exception as e:
        print(f"[market] WARNING: Finnhub fallback failed for {symbol}: {e}")

    print(f"[market] WARNING: {symbol} in degraded mode — no fresh data")
    return None


def fetch_market_data() -> dict[str, Any]:
    """Fetch equities market data with multi-source fallback.

    Returns a dict shaped like:
    {
      "equities": {
        "SPY": {"price": float, "prev_close": float, "pct_change": float, "volume": int},
        ...
      },
      "fetched_at_et": "YYYY-MM-DD HH:MM ET"
    }
    """

    now_et = datetime.now(ET_TZ)
    fetched_at_et = now_et.strftime("%Y-%m-%d %H:%M ET")

    equities_tickers = ["SPY", "QQQ", "DIA", "^VIX"]

    equities: dict[str, Any] = {}

    print("Fetching market data via yfinance (with fallbacks)...", file=sys.stdout)

    for tk in equities_tickers:
        result = fetch_equity_with_fallback(tk)
        if result is not None:
            equities[tk] = result
        else:
            equities[tk] = None

    return {
        "equities": equities,
        "fetched_at_et": fetched_at_et,
    }


def fetch_macro_context() -> dict[str, Any]:
    """Fetch macro context: 10Y Treasury yield, DXY, Fear & Greed Index.

    Each field is fetched independently — if one fails, the others still return.
    Uses the same multi-source fallback pattern as equity fetches.
    """
    print("[market] Fetching macro context (TNX, DXY, Fear & Greed)...")

    result: dict[str, Any] = {
        "treasury_10y": None,
        "dollar_index": None,
        "fear_greed_score": None,
        "fear_greed_rating": None,
    }

    # 10-Year Treasury Yield (^TNX) — with fallback
    try:
        tnx_data = fetch_equity_with_fallback("^TNX")
        if tnx_data and tnx_data.get("price") is not None:
            result["treasury_10y"] = round(float(tnx_data["price"]), 2)
    except Exception as exc:
        print(f"[market] WARNING: TNX fetch failed — {exc}")

    # US Dollar Index (DX-Y.NYB) — with fallback
    try:
        dxy_data = fetch_equity_with_fallback("DX-Y.NYB")
        if dxy_data and dxy_data.get("price") is not None:
            result["dollar_index"] = round(float(dxy_data["price"]), 2)
    except Exception as exc:
        print(f"[market] WARNING: DXY fetch failed — {exc}")

    # Fear & Greed Index — try multiple endpoints
    fg_found = False

    # Endpoint 1: CNN
    if not fg_found:
        try:
            url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
            resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if 200 <= resp.status_code < 300:
                data = resp.json()
                fg = data.get("fear_and_greed") or {}
                score = fg.get("score")
                rating = fg.get("rating")
                if score is not None:
                    result["fear_greed_score"] = int(round(float(score)))
                    result["fear_greed_rating"] = str(rating) if rating else "Unknown"
                    fg_found = True
                    print(f"[market] Fear & Greed source: CNN — score {result['fear_greed_score']} ({result['fear_greed_rating']})")
        except Exception as exc:
            print(f"[market] WARNING: Fear & Greed CNN failed — {exc}, trying next...")

    # Endpoint 2: Alternative.me (crypto fear & greed)
    if not fg_found:
        try:
            url = "https://api.alternative.me/fng/?limit=1"
            resp = requests.get(url, timeout=10)
            if 200 <= resp.status_code < 300:
                data = resp.json()
                items = data.get("data") or []
                if items:
                    score = int(items[0].get("value", 0))
                    rating = items[0].get("value_classification", "Unknown")
                    result["fear_greed_score"] = score
                    result["fear_greed_rating"] = str(rating)
                    fg_found = True
                    print(f"[market] Fear & Greed source: Alternative.me — score {score} ({rating})")
        except Exception as exc:
            print(f"[market] WARNING: Fear & Greed Alternative.me failed — {exc}, trying next...")

    # Endpoint 3: Fallback neutral
    if not fg_found:
        result["fear_greed_score"] = 50
        result["fear_greed_rating"] = "Neutral (unavailable)"
        print("[market] Fear & Greed source: fallback — score 50 (Neutral (unavailable))")

    # Log results
    tnx_str = f"{result['treasury_10y']}%" if result["treasury_10y"] is not None else "N/A"
    dxy_str = str(result["dollar_index"]) if result["dollar_index"] is not None else "N/A"
    fg_str = f"{result['fear_greed_score']} ({result['fear_greed_rating']})" if result["fear_greed_score"] is not None else "N/A"
    print(f"[market] TNX: {tnx_str} | DXY: {dxy_str} | Fear & Greed: {fg_str}")

    return result
