"""Signal logger — logs every BUY/SELL/HOLD/WATCH recommendation to CSV."""

from __future__ import annotations

import csv
import math
import os
import sys
from datetime import datetime

import pytz
import yfinance as yf

ET = pytz.timezone("America/New_York")

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "signals.csv")

HEADERS = [
    "date_et",
    "time_et",
    "ticker",
    "action",
    "confidence",
    "price_at_signal",
    "report_type",
    "reasoning_summary",
]

VALID_ACTIONS = {"BUY", "SELL", "HOLD", "WATCH"}
VALID_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}
CRYPTO_YFINANCE_SYMBOLS = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
}


def fetch_price_for_ticker(ticker: str) -> float | None:
    """Fetch current/last close price for a ticker via yfinance. Returns float or None."""
    ticker = str(ticker or "").strip().upper()
    yf_symbol = CRYPTO_YFINANCE_SYMBOLS.get(ticker, ticker)
    try:
        t = yf.Ticker(yf_symbol)
        hist = t.history(period="2d")
        if hist is not None and not hist.empty:
            price = float(hist["Close"].iloc[-1])
            if math.isfinite(price):
                return round(price, 2)
    except Exception as exc:
        print(f"[signal_logger] WARNING: price fetch failed for {ticker}: {exc}")
    return None


def _normalize_action(action: str) -> str:
    return str(action or "").strip().upper()


def _normalize_confidence(confidence: str) -> str:
    raw = str(confidence or "").strip().upper()
    if "HIGH" in raw:
        return "HIGH"
    if "MEDIUM" in raw:
        return "MEDIUM"
    if "LOW" in raw:
        return "LOW"
    return raw


def log_signal(
    ticker: str,
    action: str,
    confidence: str,
    price: float | None,
    report_type: str,
    reasoning: str,
) -> None:
    """Append one signal row to the CSV file."""
    action = _normalize_action(action)
    confidence = _normalize_confidence(confidence)
    ticker = str(ticker or "").strip().upper()

    if not ticker:
        print("[signal_logger] WARNING: skipped signal with empty ticker", file=sys.stderr)
        return
    if action not in VALID_ACTIONS:
        print(f"[signal_logger] WARNING: skipped {ticker}; invalid action: {action!r}", file=sys.stderr)
        return
    if confidence not in VALID_CONFIDENCE:
        print(f"[signal_logger] WARNING: skipped {ticker}; invalid confidence: {confidence!r}", file=sys.stderr)
        return
    if price is not None:
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = None
        if price is not None and not math.isfinite(price):
            print(f"[signal_logger] WARNING: {ticker} price was non-finite; logging N/A", file=sys.stderr)
            price = None

    data_dir = os.path.dirname(CSV_PATH)
    os.makedirs(data_dir, exist_ok=True)

    file_exists = os.path.isfile(CSV_PATH)
    if not file_exists:
        print(f"[signal_logger] Initializing signals.csv at {CSV_PATH}")

    now_et = datetime.now(ET)
    date_et = now_et.strftime("%Y-%m-%d")
    time_et = now_et.strftime("%H:%M")

    price_str = f"{price:.2f}" if price is not None else "N/A"
    reason_clean = (reasoning or "").replace("\n", " ").replace("\r", " ").strip()[:100]

    row = [
        date_et,
        time_et,
        ticker,
        action,
        confidence,
        price_str,
        report_type,
        reason_clean,
    ]

    try:
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(HEADERS)
            writer.writerow(row)
        print(f"[signal_logger] Logged: {ticker} {action} ({confidence}) @ {price_str}")
    except Exception as exc:
        print(f"[signal_logger] WARNING: failed to write signal: {exc}", file=sys.stderr)


def log_recommendations(recs: list[dict], report_type: str) -> int:
    """Log a list of parsed recommendations. Returns count logged."""
    count = 0
    price_cache: dict[str, float | None] = {}
    for r in recs:
        ticker = r.get("ticker", "").strip().upper()
        action = _normalize_action(r.get("rating", ""))
        confidence = _normalize_confidence(r.get("confidence", ""))
        reasoning = r.get("reason", "").strip()

        if not ticker:
            print("[signal_logger] WARNING: skipped recommendation with empty ticker", file=sys.stderr)
            continue
        if action not in VALID_ACTIONS:
            print(f"[signal_logger] WARNING: skipped {ticker}; invalid action: {action!r}", file=sys.stderr)
            continue
        if confidence not in VALID_CONFIDENCE:
            print(f"[signal_logger] WARNING: skipped {ticker}; invalid confidence: {confidence!r}", file=sys.stderr)
            continue

        if ticker not in price_cache:
            price_cache[ticker] = fetch_price_for_ticker(ticker)
        price = price_cache[ticker]
        log_signal(ticker, action, confidence, price, report_type, reasoning)
        count += 1

    print(f"[signal_logger] Logged {count} signals this run")
    return count
