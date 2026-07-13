"""Outcome tracker for logged signals.

Reads data/signals.csv and writes data/signal_outcomes.csv with deterministic
1/5/10-trading-day returns. BUY/SELL get directional signal returns; WATCH/HOLD
keep raw ticker returns only because they are not explicit trade directions.
"""

from __future__ import annotations

import csv
import hashlib
import math
import os
from datetime import datetime, time, timedelta
from typing import Any

import pytz
import yfinance as yf

from signal_logger import CRYPTO_YFINANCE_SYMBOLS, CSV_PATH, VALID_ACTIONS


ET = pytz.timezone("America/New_York")
OUTCOMES_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "signal_outcomes.csv")

OUTCOME_HEADERS = [
    "signal_id",
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
    "expected_direction",
    "actionable",
    "idea_key",
    "is_repeat_5d",
    "repeat_of_signal_id",
    "price_1d",
    "return_1d_pct",
    "signal_return_1d_pct",
    "price_5d",
    "return_5d_pct",
    "signal_return_5d_pct",
    "price_10d",
    "return_10d_pct",
    "signal_return_10d_pct",
    "spy_return_5d_pct",
    "qqq_return_5d_pct",
    "status",
    "updated_at_et",
]


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _fmt_num(value: float | None) -> str:
    return f"{value:.2f}" if value is not None and math.isfinite(value) else ""


def _parse_signal_dt(row: dict[str, str]) -> datetime | None:
    raw = f"{row.get('date_et', '').strip()} {row.get('time_et', '').strip()}".strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return ET.localize(parsed)
        except ValueError:
            continue
    return None


def _market_symbol(ticker: str) -> str:
    ticker = str(ticker or "").strip().upper()
    return CRYPTO_YFINANCE_SYMBOLS.get(ticker, ticker)


def _signal_id(row: dict[str, str]) -> str:
    raw = "|".join(
        [
            row.get("date_et", "").strip(),
            row.get("time_et", "").strip(),
            row.get("ticker", "").strip().upper(),
            row.get("action", "").strip().upper(),
            row.get("confidence", "").strip().upper(),
            row.get("price_at_signal", "").strip(),
            row.get("report_type", "").strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _history_points(ticker: str, period: str = "6mo") -> list[tuple[datetime.date, float]]:
    symbol = _market_symbol(ticker)
    hist = yf.Ticker(symbol).history(period=period, interval="1d")
    if hist is None or hist.empty or "Close" not in hist:
        return []

    points: list[tuple[datetime.date, float]] = []
    closes = hist["Close"]
    for idx, close in closes.items():
        price = _safe_float(close)
        if price is None:
            continue
        if hasattr(idx, "date"):
            d = idx.date()
        else:
            try:
                d = datetime.fromisoformat(str(idx)[:10]).date()
            except ValueError:
                continue
        points.append((d, price))
    return points


def _price_after_bars(points: list[tuple[datetime.date, float]], signal_dt: datetime, bars: int) -> float | None:
    if not points or bars <= 0:
        return None

    signal_date = signal_dt.date()
    use_next_session = signal_dt.time() >= time(16, 0)

    first_idx = None
    for i, (d, _) in enumerate(points):
        eligible = d > signal_date if use_next_session else d >= signal_date
        if eligible:
            first_idx = i
            break

    if first_idx is None:
        return None

    target_idx = first_idx + bars - 1
    if target_idx >= len(points):
        return None
    return points[target_idx][1]


def _return_pct(entry: float | None, exit_price: float | None) -> float | None:
    if entry is None or exit_price is None or entry == 0:
        return None
    return ((exit_price - entry) / entry) * 100.0


def _signal_return(action: str, raw_return: float | None) -> float | None:
    if raw_return is None:
        return None
    if action == "BUY":
        return raw_return
    if action == "SELL":
        return -raw_return
    return None


def _expected_direction(action: str) -> str:
    if action == "BUY":
        return "long"
    if action == "SELL":
        return "short"
    return "neutral"


def _idea_key(ticker: str, action: str) -> str:
    return f"{ticker.upper()}:{action.upper()}"


def _benchmark_return(
    benchmark_points: list[tuple[datetime.date, float]],
    signal_dt: datetime,
    bars: int,
) -> float | None:
    entry = _price_after_bars(benchmark_points, signal_dt, 1)
    exit_price = _price_after_bars(benchmark_points, signal_dt, bars)
    return _return_pct(entry, exit_price)


def _get_history(
    history_cache: dict[str, list[tuple[datetime.date, float]]],
    ticker: str,
) -> list[tuple[datetime.date, float]]:
    ticker = ticker.upper()
    if ticker not in history_cache:
        history_cache[ticker] = _history_points(ticker)
    return history_cache[ticker]


def build_outcome_row(
    row: dict[str, str],
    history_cache: dict[str, list[tuple[datetime.date, float]]],
) -> dict[str, str] | None:
    ticker = str(row.get("ticker") or "").strip().upper()
    action = str(row.get("action") or "").strip().upper()
    entry = _safe_float(row.get("price_at_signal"))
    signal_dt = _parse_signal_dt(row)

    if not ticker or action not in VALID_ACTIONS or entry is None or signal_dt is None:
        return None

    points = _get_history(history_cache, ticker)
    spy_points = _get_history(history_cache, "SPY")
    qqq_points = _get_history(history_cache, "QQQ")

    prices = {
        "1d": _price_after_bars(points, signal_dt, 1),
        "5d": _price_after_bars(points, signal_dt, 5),
        "10d": _price_after_bars(points, signal_dt, 10),
    }
    raw_returns = {k: _return_pct(entry, price) for k, price in prices.items()}
    signal_returns = {k: _signal_return(action, ret) for k, ret in raw_returns.items()}

    if prices["1d"] is None:
        status = "pending"
    elif prices["10d"] is None:
        status = "partial"
    else:
        status = "complete"

    return {
        "signal_id": _signal_id(row),
        "date_et": row.get("date_et", "").strip(),
        "time_et": row.get("time_et", "").strip(),
        "ticker": ticker,
        "action": action,
        "confidence": row.get("confidence", "").strip().upper(),
        "price_at_signal": _fmt_num(entry),
        "report_type": row.get("report_type", "").strip(),
        "catalyst_type": row.get("catalyst_type", "").strip().lower() or "unknown",
        "catalyst_detail": row.get("catalyst_detail", "").strip(),
        "catalyst_horizon": row.get("catalyst_horizon", "").strip(),
        "risk_trigger": row.get("risk_trigger", "").strip(),
        "expected_direction": _expected_direction(action),
        "actionable": "true" if action in {"BUY", "SELL"} else "false",
        "idea_key": _idea_key(ticker, action) if action in {"BUY", "SELL"} else "",
        "is_repeat_5d": "false",
        "repeat_of_signal_id": "",
        "price_1d": _fmt_num(prices["1d"]),
        "return_1d_pct": _fmt_num(raw_returns["1d"]),
        "signal_return_1d_pct": _fmt_num(signal_returns["1d"]),
        "price_5d": _fmt_num(prices["5d"]),
        "return_5d_pct": _fmt_num(raw_returns["5d"]),
        "signal_return_5d_pct": _fmt_num(signal_returns["5d"]),
        "price_10d": _fmt_num(prices["10d"]),
        "return_10d_pct": _fmt_num(raw_returns["10d"]),
        "signal_return_10d_pct": _fmt_num(signal_returns["10d"]),
        "spy_return_5d_pct": _fmt_num(_benchmark_return(spy_points, signal_dt, 5)),
        "qqq_return_5d_pct": _fmt_num(_benchmark_return(qqq_points, signal_dt, 5)),
        "status": status,
        "updated_at_et": datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
    }


def _outcome_dt(row: dict[str, str]) -> datetime | None:
    return _parse_signal_dt({"date_et": row.get("date_et", ""), "time_et": row.get("time_et", "")})


def annotate_repeated_ideas(rows: list[dict[str, str]], window_days: int = 5) -> None:
    """Mark repeated actionable ticker/action ideas within a rolling calendar window."""
    last_primary_by_key: dict[str, tuple[datetime, str]] = {}
    window = timedelta(days=window_days)

    for row in rows:
        row["is_repeat_5d"] = "false"
        row["repeat_of_signal_id"] = ""

    for row in sorted(rows, key=lambda r: (r.get("date_et", ""), r.get("time_et", ""), r.get("signal_id", ""))):
        if str(row.get("actionable", "")).lower() != "true":
            continue
        key = row.get("idea_key") or _idea_key(row.get("ticker", ""), row.get("action", ""))
        row["idea_key"] = key
        dt = _outcome_dt(row)
        if dt is None:
            continue

        prior = last_primary_by_key.get(key)
        if prior and dt - prior[0] <= window:
            row["is_repeat_5d"] = "true"
            row["repeat_of_signal_id"] = prior[1]
            continue

        row["is_repeat_5d"] = "false"
        row["repeat_of_signal_id"] = ""
        last_primary_by_key[key] = (dt, row.get("signal_id", ""))


def update_signal_outcomes(
    signals_path: str = CSV_PATH,
    outcomes_path: str = OUTCOMES_PATH,
) -> int:
    """Rewrite signal_outcomes.csv from signals.csv. Returns outcome row count."""
    if not os.path.isfile(signals_path):
        print(f"[outcomes] No signals file found at {signals_path}; skipping outcome update")
        return 0

    with open(signals_path, "r", newline="", encoding="utf-8") as f:
        signals = list(csv.DictReader(f))

    history_cache: dict[str, list[tuple[datetime.date, float]]] = {}
    rows: list[dict[str, str]] = []
    skipped = 0
    for signal in signals:
        outcome = build_outcome_row(signal, history_cache)
        if outcome is None:
            skipped += 1
            continue
        rows.append(outcome)

    annotate_repeated_ideas(rows)

    os.makedirs(os.path.dirname(outcomes_path), exist_ok=True)
    tmp_path = outcomes_path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTCOME_HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp_path, outcomes_path)

    print(f"[outcomes] Wrote {len(rows)} outcome rows to {outcomes_path} (skipped {skipped})")
    return len(rows)


if __name__ == "__main__":
    raise SystemExit(0 if update_signal_outcomes() >= 0 else 1)
