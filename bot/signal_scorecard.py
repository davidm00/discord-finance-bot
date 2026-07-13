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
    measured_5d = [
        _safe_float(r.get("signal_return_5d_pct"))
        for r in actionable
        if _safe_float(r.get("signal_return_5d_pct")) is not None
    ]
    measured_5d = [v for v in measured_5d if v is not None]

    lines = [
        f"SIGNAL SCORECARD (last {days} days; measured from signal_outcomes.csv):",
        f"Actionable BUY/SELL 5D directional performance: {_summarize_returns(measured_5d)}",
    ]

    by_action: dict[str, list[float]] = defaultdict(list)
    by_confidence: dict[str, list[float]] = defaultdict(list)
    for row in actionable:
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
        r for r in actionable
        if _safe_float(r.get("signal_return_5d_pct")) is not None
    ]
    measured_rows.sort(key=lambda r: (r.get("date_et", ""), r.get("time_et", "")), reverse=True)
    if measured_rows:
        lines.append("Recent measured BUY/SELL calls:")
        for row in measured_rows[:max_recent]:
            lines.append(
                f"- {row.get('date_et','')} {row.get('ticker','')} {row.get('action','')} "
                f"({row.get('confidence','')}): 5D signal return "
                f"{_fmt_pct(_safe_float(row.get('signal_return_5d_pct')))}; status={row.get('status','')}"
            )

    lines.append(
        "Use this scorecard to calibrate conviction: repeat what is working, acknowledge misses, "
        "and avoid forcing BUY/SELL calls when evidence is weak."
    )
    return "\n".join(lines)
