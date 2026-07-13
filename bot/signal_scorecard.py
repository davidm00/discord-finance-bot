"""Compact prompt-ready scorecards derived from signal_outcomes.csv."""

from __future__ import annotations

import csv
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Any

import pytz

from signal_outcomes import OUTCOMES_PATH


ET = pytz.timezone("America/New_York")

THEME_TICKERS = {
    "defense": {"LMT", "RTX", "NOC", "GD", "BA", "LDOS", "SAIC", "BAH", "HII", "TDG"},
    "cyber": {"CRWD", "PANW", "ZS", "FTNT", "S", "CYBR", "PLTR"},
    "energy": {"XOM", "CVX", "COP", "SLB", "HAL", "EOG", "MPC"},
    "tech": {"NVDA", "AMD", "MSFT", "GOOGL", "META", "AMZN", "AAPL", "QQQ", "MU", "ORCL", "CRM"},
    "crypto": {"BTC", "ETH", "SOL"},
}


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: str) -> datetime | None:
    try:
        return ET.localize(datetime.strptime(str(value or "").strip(), "%Y-%m-%d"))
    except ValueError:
        return None


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%"


def _summarize_returns(values: list[float]) -> str:
    if not values:
        return "n=0"
    wins = sum(1 for v in values if v > 0)
    return (
        f"n={len(values)}, avg={_fmt_pct(mean(values))}, "
        f"median={_fmt_pct(median(values))}, win={wins / len(values) * 100:.0f}%"
    )


def _theme_for_ticker(ticker: str) -> str:
    ticker = str(ticker or "").strip().upper()
    for theme, tickers in THEME_TICKERS.items():
        if ticker in tickers:
            return theme
    return "other"


def _bucket_summary(
    rows: list[dict[str, str]],
    field: str,
    label: str,
    limit: int | None = None,
) -> str:
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        value = _safe_float(row.get("signal_return_5d_pct"))
        if value is None:
            continue
        if field == "theme":
            key = _theme_for_ticker(row.get("ticker", ""))
        else:
            key = str(row.get(field, "") or "unknown").strip() or "unknown"
        buckets[key].append(value)

    if not buckets:
        return ""

    items = sorted(
        buckets.items(),
        key=lambda item: (len(item[1]), mean(item[1])),
        reverse=True,
    )
    if limit is not None:
        items = items[:limit]

    return label + ": " + " | ".join(
        f"{key}: {_summarize_returns(vals)}" for key, vals in items
    )


def _load_outcomes(path: str) -> list[dict[str, str]]:
    if not os.path.isfile(path):
        return []
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_signal_scorecard(
    days: int = 14,
    outcomes_path: str = OUTCOMES_PATH,
    max_recent: int = 6,
) -> str:
    """Return a compact scorecard for prompt input, or an empty string."""
    rows = _load_outcomes(outcomes_path)
    if not rows:
        return ""

    cutoff = datetime.now(ET) - timedelta(days=days)
    recent = []
    for row in rows:
        dt = _parse_date(row.get("date_et", ""))
        if dt is None or dt < cutoff:
            continue
        recent.append(row)

    if not recent:
        return ""

    actionable = [r for r in recent if str(r.get("actionable", "")).lower() == "true"]
    raw_measured_5d = [
        _safe_float(r.get("signal_return_5d_pct"))
        for r in actionable
        if _safe_float(r.get("signal_return_5d_pct")) is not None
    ]
    raw_measured_5d = [v for v in raw_measured_5d if v is not None]

    unique_actionable = [
        r for r in actionable
        if str(r.get("is_repeat_5d", "false")).lower() != "true"
    ]
    unique_measured_5d = [
        _safe_float(r.get("signal_return_5d_pct"))
        for r in unique_actionable
        if _safe_float(r.get("signal_return_5d_pct")) is not None
    ]
    unique_measured_5d = [v for v in unique_measured_5d if v is not None]
    repeat_count = max(0, len(actionable) - len(unique_actionable))

    lines = [
        f"SIGNAL SCORECARD (last {days} days; measured from signal_outcomes.csv):",
        f"Unique actionable BUY/SELL ideas, 5D directional performance: {_summarize_returns(unique_measured_5d)}",
        f"Raw actionable calls, including repeats: {_summarize_returns(raw_measured_5d)}; repeats excluded from unique score: {repeat_count}",
    ]

    by_action: dict[str, list[float]] = defaultdict(list)
    by_confidence: dict[str, list[float]] = defaultdict(list)
    for row in unique_actionable:
        value = _safe_float(row.get("signal_return_5d_pct"))
        if value is None:
            continue
        by_action[str(row.get("action", "")).upper()].append(value)
        by_confidence[str(row.get("confidence", "")).upper()].append(value)

    if by_action:
        parts = [f"{action}: {_summarize_returns(vals)}" for action, vals in sorted(by_action.items())]
        lines.append("By action: " + " | ".join(parts))

    if by_confidence:
        order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        parts = [
            f"{confidence}: {_summarize_returns(vals)}"
            for confidence, vals in sorted(by_confidence.items(), key=lambda item: order.get(item[0], 99))
        ]
        lines.append("By confidence: " + " | ".join(parts))

    for bucket_line in (
        _bucket_summary(unique_actionable, "report_type", "By report type"),
        _bucket_summary(unique_actionable, "theme", "By theme"),
        _bucket_summary(unique_actionable, "ticker", "Top ticker buckets", limit=5),
    ):
        if bucket_line:
            lines.append(bucket_line)

    non_actionable_counts = Counter(
        str(r.get("action", "")).upper()
        for r in recent
        if str(r.get("actionable", "")).lower() != "true"
    )
    if non_actionable_counts:
        lines.append(
            "Non-actionable calls tracked: "
            + ", ".join(f"{k}={v}" for k, v in sorted(non_actionable_counts.items()))
        )

    measured_rows = [
        r for r in unique_actionable
        if _safe_float(r.get("signal_return_5d_pct")) is not None
    ]
    measured_rows.sort(key=lambda r: (r.get("date_et", ""), r.get("time_et", "")), reverse=True)
    if measured_rows:
        lines.append("Recent measured unique BUY/SELL ideas:")
        for row in measured_rows[:max_recent]:
            lines.append(
                f"- {row.get('date_et','')} {row.get('ticker','')} {row.get('action','')} "
                f"({row.get('confidence','')}): 5D signal return "
                f"{_fmt_pct(_safe_float(row.get('signal_return_5d_pct')))}; status={row.get('status','')}"
            )

    lines.append(
        "Use this scorecard to calibrate conviction: repeat what is working, acknowledge misses, "
        "avoid forcing BUY/SELL calls when evidence is weak, and avoid hiding actionable conviction behind WATCH."
    )
    return "\n".join(lines)
