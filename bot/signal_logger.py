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
ERRORS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "signal_errors.csv")

HEADERS = [
    "date_et",
    "time_et",
    "ticker",
    "action",
    "confidence",
    "price_at_signal",
    "report_type",
    "catalyst_type",
    "catalyst_detail",
    "catalyst_horizon",
    "risk_trigger",
    "reasoning_summary",
]

ERROR_HEADERS = [
    "logged_at_et",
    "stage",
    "ticker",
    "action",
    "confidence",
    "report_type",
    "error",
    "catalyst_type",
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


def _clean_cell(value: str, limit: int = 200) -> str:
    return str(value or "").replace("\n", " ").replace("\r", " ").strip()[:limit]


def _ensure_signal_header(path: str) -> bool:
    """Ensure signals.csv exists with current headers. Returns true if file already existed."""
    if not os.path.isfile(path):
        return False

    try:
        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            existing_headers = reader.fieldnames or []
            rows = list(reader)
    except Exception as exc:
        print(f"[signal_logger] WARNING: failed to inspect signal CSV headers: {exc}", file=sys.stderr)
        return True

    if existing_headers == HEADERS:
        return True
    if all(h in existing_headers for h in HEADERS):
        return True

    data_dir = os.path.dirname(path)
    os.makedirs(data_dir, exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        for row in rows:
            writer.writerow({h: row.get(h, "") for h in HEADERS})
    os.replace(tmp_path, path)
    print("[signal_logger] Migrated signals.csv headers for structured catalysts")
    return True


def log_signal_error(
    stage: str,
    ticker: str,
    action: str,
    confidence: str,
    report_type: str,
    error: str,
    reasoning: str = "",
    catalyst_type: str = "",
) -> None:
    """Append rejected recommendation details to a separate diagnostics CSV."""
    data_dir = os.path.dirname(ERRORS_PATH)
    os.makedirs(data_dir, exist_ok=True)

    file_exists = os.path.isfile(ERRORS_PATH)
    now_et = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    row = [
        now_et,
        _clean_cell(stage, 50),
        _clean_cell(ticker, 20).upper(),
        _clean_cell(action, 80).upper(),
        _clean_cell(confidence, 40).upper(),
        _clean_cell(report_type, 40),
        _clean_cell(error, 200),
        _clean_cell(catalyst_type, 80).lower(),
        _clean_cell(reasoning, 200),
    ]

    try:
        with open(ERRORS_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(ERROR_HEADERS)
            writer.writerow(row)
    except Exception as exc:
        print(f"[signal_logger] WARNING: failed to write signal error: {exc}", file=sys.stderr)


def log_signal(
    ticker: str,
    action: str,
    confidence: str,
    price: float | None,
    report_type: str,
    reasoning: str,
    catalyst_type: str = "",
    catalyst_detail: str = "",
    catalyst_horizon: str = "",
    risk_trigger: str = "",
) -> None:
    """Append one signal row to the CSV file."""
    action = _normalize_action(action)
    confidence = _normalize_confidence(confidence)
    ticker = str(ticker or "").strip().upper()

    if not ticker:
        print("[signal_logger] WARNING: skipped signal with empty ticker", file=sys.stderr)
        log_signal_error("log_signal", ticker, action, confidence, report_type, "empty ticker", reasoning, catalyst_type)
        return
    if action not in VALID_ACTIONS:
        print(f"[signal_logger] WARNING: skipped {ticker}; invalid action: {action!r}", file=sys.stderr)
        log_signal_error("log_signal", ticker, action, confidence, report_type, "invalid action", reasoning, catalyst_type)
        return
    if confidence not in VALID_CONFIDENCE:
        print(f"[signal_logger] WARNING: skipped {ticker}; invalid confidence: {confidence!r}", file=sys.stderr)
        log_signal_error("log_signal", ticker, action, confidence, report_type, "invalid confidence", reasoning, catalyst_type)
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

    file_exists = _ensure_signal_header(CSV_PATH)
    if not file_exists:
        print(f"[signal_logger] Initializing signals.csv at {CSV_PATH}")

    now_et = datetime.now(ET)
    date_et = now_et.strftime("%Y-%m-%d")
    time_et = now_et.strftime("%H:%M")

    price_str = f"{price:.2f}" if price is not None else "N/A"
    reason_clean = _clean_cell(reasoning, 100)

    row = [
        date_et,
        time_et,
        ticker,
        action,
        confidence,
        price_str,
        report_type,
        _clean_cell(catalyst_type, 80).lower() or "other",
        _clean_cell(catalyst_detail, 160),
        _clean_cell(catalyst_horizon, 80),
        _clean_cell(risk_trigger, 160),
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
        catalyst_type = str(r.get("catalyst_type") or "other").strip().lower()
        catalyst_detail = str(r.get("catalyst_detail") or "").strip()
        catalyst_horizon = str(r.get("catalyst_horizon") or "").strip()
        risk_trigger = str(r.get("risk_trigger") or "").strip()

        if not ticker:
            print("[signal_logger] WARNING: skipped recommendation with empty ticker", file=sys.stderr)
            log_signal_error("log_recommendations", ticker, action, confidence, report_type, "empty ticker", reasoning, catalyst_type)
            continue
        if action not in VALID_ACTIONS:
            print(f"[signal_logger] WARNING: skipped {ticker}; invalid action: {action!r}", file=sys.stderr)
            log_signal_error("log_recommendations", ticker, action, confidence, report_type, "invalid action", reasoning, catalyst_type)
            continue
        if confidence not in VALID_CONFIDENCE:
            print(f"[signal_logger] WARNING: skipped {ticker}; invalid confidence: {confidence!r}", file=sys.stderr)
            log_signal_error("log_recommendations", ticker, action, confidence, report_type, "invalid confidence", reasoning, catalyst_type)
            continue

        if ticker not in price_cache:
            price_cache[ticker] = fetch_price_for_ticker(ticker)
        price = price_cache[ticker]
        log_signal(
            ticker,
            action,
            confidence,
            price,
            report_type,
            reasoning,
            catalyst_type,
            catalyst_detail,
            catalyst_horizon,
            risk_trigger,
        )
        count += 1

    print(f"[signal_logger] Logged {count} signals this run")
    return count
