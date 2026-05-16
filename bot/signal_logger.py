"""Signal logger — logs every BUY/SELL/HOLD/WATCH recommendation to CSV."""

from __future__ import annotations

import csv
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


def fetch_price_for_ticker(ticker: str) -> float | None:
    """Fetch current/last close price for a ticker via yfinance. Returns float or None."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if hist is not None and not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2)
    except Exception as exc:
        print(f"[signal_logger] WARNING: price fetch failed for {ticker}: {exc}")
    return None


def log_signal(
    ticker: str,
    action: str,
    confidence: str,
    price: float | None,
    report_type: str,
    reasoning: str,
) -> None:
    """Append one signal row to the CSV file."""
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
        ticker.upper(),
        action.upper(),
        confidence.upper(),
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
        print(f"[signal_logger] Logged: {ticker.upper()} {action.upper()} ({confidence.upper()}) @ {price_str}")
    except Exception as exc:
        print(f"[signal_logger] WARNING: failed to write signal: {exc}", file=sys.stderr)


def log_recommendations(recs: list[dict], report_type: str) -> int:
    """Log a list of parsed recommendations. Returns count logged."""
    count = 0
    for r in recs:
        ticker = r.get("ticker", "").strip()
        action = r.get("rating", "").strip()
        confidence = r.get("confidence", "").strip()
        reasoning = r.get("reason", "").strip()

        if not ticker or not action:
            continue

        price = fetch_price_for_ticker(ticker)
        log_signal(ticker, action, confidence, price, report_type, reasoning)
        count += 1

    print(f"[signal_logger] Logged {count} signals this run")
    return count
