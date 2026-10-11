"""Portfolio analytics, chart generation, and isolated Discord rendering."""

from __future__ import annotations

import csv
import json
import math
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytz
import requests

from paper_portfolio import (
    DEFAULT_STATE_DIR,
    ET,
    LEDGER_HEADERS,
    ORDER_HEADERS,
    SNAPSHOT_HEADERS,
    _read_csv,
    _safe_float,
)
from portfolio_policy import DEFAULT_POLICY


PORTFOLIO_DISCLAIMER = "Paper portfolio with simulated fills. Not financial advice."


def _latest_snapshot(state_dir: Path) -> dict[str, str]:
    snapshots = _read_csv(Path(state_dir) / "snapshots.csv")
    if not snapshots:
        raise ValueError("No portfolio snapshots are available")
    return max(snapshots, key=lambda row: row.get("date_et", ""))


def _closed_trades(ledger: list[dict[str, str]]) -> list[dict[str, Any]]:
    opened: dict[str, dict[str, str]] = {}
    closed: list[dict[str, Any]] = []
    for event in sorted(ledger, key=lambda row: row.get("occurred_at_et", "")):
        ticker = event.get("ticker", "")
        event_type = event.get("event_type", "")
        if event_type == "BUY":
            opened[ticker] = event
            continue
        if event_type not in {"SELL", "STOP", "TIME_EXIT"} or ticker not in opened:
            continue
        buy = opened.pop(ticker)
        buy_price = _safe_float(buy.get("price"))
        sell_price = _safe_float(event.get("price"))
        shares = _safe_float(event.get("shares"))
        if buy_price is None or sell_price is None or shares is None:
            continue
        closed.append(
            {
                "ticker": ticker,
                "opened_at": buy.get("occurred_at_et", ""),
                "closed_at": event.get("occurred_at_et", ""),
                "exit_type": event_type,
                "pnl": (sell_price - buy_price) * shares,
                "return_pct": ((sell_price - buy_price) / buy_price) * 100,
            }
        )
    return closed


def build_portfolio_summary(state_dir: Path = DEFAULT_STATE_DIR) -> dict[str, Any]:
    state_dir = Path(state_dir)
    snapshots = sorted(_read_csv(state_dir / "snapshots.csv"), key=lambda row: row.get("date_et", ""))
    latest = _latest_snapshot(state_dir)
    ledger = _read_csv(state_dir / "ledger.csv")
    orders = _read_csv(state_dir / "orders.csv")
    positions = json.loads(latest.get("positions_json") or "[]")
    closed = _closed_trades(ledger)

    equity = _safe_float(latest.get("equity")) or DEFAULT_POLICY.initial_capital
    cash = _safe_float(latest.get("cash")) or 0.0
    return_pct = _safe_float(latest.get("return_pct")) or 0.0
    week_cutoff = datetime.strptime(latest["date_et"], "%Y-%m-%d").date() - timedelta(days=7)
    week_candidates = [
        row
        for row in snapshots
        if datetime.strptime(row["date_et"], "%Y-%m-%d").date() <= week_cutoff
    ]
    week_base = week_candidates[-1] if week_candidates else snapshots[0]
    week_equity = _safe_float(week_base.get("equity")) or DEFAULT_POLICY.initial_capital
    weekly_return = ((equity / week_equity) - 1) * 100 if week_equity else 0.0

    equities = [_safe_float(row.get("equity")) for row in snapshots]
    peak = -math.inf
    max_drawdown = 0.0
    for value in (number for number in equities if number is not None):
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, ((value / peak) - 1) * 100)

    recent_orders = [
        row
        for row in orders
        if row.get("status") in {"filled", "rejected", "cancelled"}
    ][-5:]
    pending_orders = [row for row in orders if row.get("status") == "pending"]
    wins = sum(1 for trade in closed if trade["pnl"] > 0)

    return {
        "as_of": latest.get("date_et", ""),
        "equity": equity,
        "cash": cash,
        "market_value": _safe_float(latest.get("market_value")) or 0.0,
        "all_time_pnl": equity - DEFAULT_POLICY.initial_capital,
        "all_time_return_pct": return_pct,
        "weekly_return_pct": weekly_return,
        "realized_pnl": _safe_float(latest.get("realized_pnl")) or 0.0,
        "unrealized_pnl": _safe_float(latest.get("unrealized_pnl")) or 0.0,
        "max_drawdown_pct": max_drawdown,
        "positions": positions,
        "pending_orders": pending_orders,
        "recent_orders": recent_orders,
        "closed_trades": len(closed),
        "closed_win_rate": (wins / len(closed) * 100) if closed else None,
        "policy_version": latest.get("policy_version", DEFAULT_POLICY.version),
        "snapshots": snapshots,
    }


def generate_portfolio_chart(
    summary: dict[str, Any],
    output_path: Path,
    days: int = 7,
) -> Path | None:
    snapshots = summary.get("snapshots") or []
    if not snapshots:
        return None
    end = datetime.strptime(summary["as_of"], "%Y-%m-%d").date()
    cutoff = end - timedelta(days=days)
    rows = [
        row
        for row in snapshots
        if datetime.strptime(row["date_et"], "%Y-%m-%d").date() >= cutoff
    ]
    if not rows:
        return None

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("matplotlib is required to generate the portfolio chart") from exc

    dates = [datetime.strptime(row["date_et"], "%Y-%m-%d").date() for row in rows]
    equity = [_safe_float(row.get("equity")) or DEFAULT_POLICY.initial_capital for row in rows]
    portfolio_base = equity[0]
    portfolio_returns = [((value / portfolio_base) - 1) * 100 for value in equity]
    spy_values = [_safe_float(row.get("spy_return_pct")) for row in rows]
    spy_base = next((value for value in spy_values if value is not None), None)

    fig, axis = plt.subplots(figsize=(8, 4.2), dpi=140)
    axis.plot(dates, portfolio_returns, marker="o", linewidth=2.2, label="Paper portfolio")
    if spy_base is not None and sum(value is not None for value in spy_values) >= 2:
        normalized_spy = [
            (value - spy_base) if value is not None else math.nan
            for value in spy_values
        ]
        axis.plot(dates, normalized_spy, linestyle="--", linewidth=1.6, label="SPY")
    axis.axhline(0, color="#777777", linewidth=0.8)
    axis.set_title("Trailing 7-Day Paper Portfolio Performance")
    axis.set_ylabel("Cumulative return (%)")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)
    return output_path


def _signed_money(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    return f"{sign}${abs(value):,.2f}"


def _signed_pct(value: float) -> str:
    return f"{value:+.2f}%"


def _clamp(value: str, limit: int) -> str:
    value = str(value or "")
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def build_portfolio_embed(summary: dict[str, Any], report_type: str, include_image: bool) -> dict[str, Any]:
    positions = summary["positions"]
    if positions:
        position_lines = [
            (
                f"**{position['ticker']}** — {position['shares']:.4f} shares | "
                f"bought {position['purchase_date']} @ ${position['average_entry']:,.2f} | "
                f"${position['current_price']:,.2f} ({position['pnl_pct']:+.2f}%)"
            )
            for position in positions[:10]
        ]
        if len(positions) > 10:
            position_lines.append(f"+{len(positions) - 10} more positions")
        position_text = "\n".join(position_lines)
    else:
        position_text = "No open positions."

    pending = summary["pending_orders"]
    pending_text = (
        "\n".join(
            f"{order['ticker']} {order['side']} — eligible {order['eligible_date']}"
            for order in pending[:8]
        )
        if pending
        else "No pending orders."
    )
    win_rate = (
        f"{summary['closed_win_rate']:.0f}%"
        if summary["closed_win_rate"] is not None
        else "n/a"
    )
    fields = [
        {
            "name": "Account",
            "value": (
                f"Equity: **${summary['equity']:,.2f}**\n"
                f"All time: **{_signed_money(summary['all_time_pnl'])} "
                f"({_signed_pct(summary['all_time_return_pct'])})**\n"
                f"Cash: ${summary['cash']:,.2f} | Invested: ${summary['market_value']:,.2f}"
            ),
            "inline": True,
        },
        {
            "name": "Risk & Results",
            "value": (
                f"7D: **{_signed_pct(summary['weekly_return_pct'])}**\n"
                f"Max drawdown: {summary['max_drawdown_pct']:.2f}%\n"
                f"Closed trades: {summary['closed_trades']} | Win rate: {win_rate}"
            ),
            "inline": True,
        },
        {"name": "Open Positions", "value": _clamp(position_text, 1024), "inline": False},
        {"name": "Pending Orders", "value": _clamp(pending_text, 1024), "inline": False},
    ]
    if report_type == "weekly" and summary["recent_orders"]:
        activity = "\n".join(
            f"{row['ticker']} {row['action']} — {row['status']}: {row['reason']}"
            for row in summary["recent_orders"]
        )
        fields.append({"name": "Recent Activity", "value": _clamp(activity, 1024), "inline": False})

    embed: dict[str, Any] = {
        "title": f"Paper Portfolio Performance — {summary['as_of']} ET",
        "description": PORTFOLIO_DISCLAIMER,
        "color": 3066993 if summary["all_time_pnl"] >= 0 else 15158332,
        "fields": fields[:25],
        "footer": {
            "text": f"Internal simulation | Policy {summary['policy_version']} | $10,000 starting capital"
        },
    }
    if include_image:
        embed["image"] = {"url": "attachment://portfolio-7d.png"}
    return embed


def send_portfolio_card(
    webhook_url: str,
    embed: dict[str, Any],
    chart_path: Path | None,
) -> None:
    if not webhook_url:
        raise ValueError("DISCORD_WEBHOOK_URL is not set")
    if chart_path and Path(chart_path).is_file():
        with Path(chart_path).open("rb") as image:
            response = requests.post(
                webhook_url,
                data={"payload_json": json.dumps({"embeds": [embed]})},
                files={"files[0]": ("portfolio-7d.png", image, "image/png")},
                timeout=30,
            )
    else:
        response = requests.post(webhook_url, json={"embeds": [embed]}, timeout=20)
    if not 200 <= response.status_code < 300:
        raise RuntimeError(
            f"Portfolio webhook failed with {response.status_code}: {response.text[:500]}"
        )


def write_portfolio_preview(
    summary: dict[str, Any],
    embed: dict[str, Any],
    output_dir: Path,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "paper_portfolio.md"
    fields = embed.get("fields") or []
    lines = [f"# {embed['title']}", "", embed["description"], ""]
    for field in fields:
        lines.extend([f"## {field['name']}", "", field["value"], ""])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    (output_dir / "paper_portfolio.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return path
