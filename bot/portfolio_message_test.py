"""Send isolated, clearly labeled portfolio-card examples to Discord."""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from paper_portfolio import ET, REPO_ROOT
from portfolio_reporting import (
    build_portfolio_embed,
    generate_portfolio_chart,
    send_portfolio_card,
)
from portfolio_policy import DEFAULT_POLICY


def build_sample_summary() -> dict:
    today = datetime.now(ET).date()
    equity_values = [10_000.00, 9_978.50, 10_012.10, 10_041.75, 10_030.20, 10_098.40, 10_146.80]
    spy_values = [0.00, -0.12, 0.08, 0.22, 0.18, 0.31, 0.45]
    snapshots = []
    for offset, (equity, spy_return) in enumerate(zip(equity_values, spy_values)):
        day = today - timedelta(days=len(equity_values) - offset - 1)
        snapshots.append(
            {
                "date_et": day.isoformat(),
                "equity": f"{equity:.2f}",
                "spy_return_pct": f"{spy_return:.2f}",
            }
        )

    return {
        "as_of": today.isoformat(),
        "equity": 10_146.80,
        "cash": 6_090.40,
        "market_value": 4_056.40,
        "all_time_pnl": 146.80,
        "all_time_return_pct": 1.47,
        "weekly_pnl": 146.80,
        "weekly_return_pct": 1.47,
        "weekly_realized_pnl": 61.25,
        "weekly_opened": 2,
        "weekly_closed": 3,
        "realized_pnl": 61.25,
        "unrealized_pnl": 85.55,
        "max_drawdown_pct": -0.44,
        "positions": [
            {
                "ticker": "XOM",
                "purchase_date": (today - timedelta(days=4)).isoformat(),
                "shares": 11.9622,
                "average_entry": 167.19,
                "current_price": 172.30,
                "market_value": 2061.08,
                "pnl_pct": 3.06,
            },
            {
                "ticker": "LMT",
                "purchase_date": (today - timedelta(days=4)).isoformat(),
                "shares": 3.3448,
                "average_entry": 598.04,
                "current_price": 596.55,
                "market_value": 1995.32,
                "pnl_pct": -0.25,
            },
        ],
        "pending_orders": [
            {
                "ticker": "CVX",
                "side": "BUY",
                "eligible_date": (today + timedelta(days=2)).isoformat(),
            }
        ],
        "recent_orders": [
            {
                "ticker": "DAL",
                "action": "SELL",
                "status": "ignored",
                "reason": "no held long position",
            },
            {
                "ticker": "QQQ",
                "action": "BUY",
                "status": "rejected",
                "reason": "opening gap exceeded 2.00%",
            },
            {
                "ticker": "XOM",
                "action": "BUY",
                "status": "filled",
                "reason": "next eligible open with adverse slippage",
            },
        ],
        "closed_trades": 3,
        "closed_win_rate": 66.7,
        "policy_version": DEFAULT_POLICY.version,
        "snapshots": snapshots,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Send portfolio message examples")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = build_sample_summary()
    output_dir = REPO_ROOT / "local-output" / "portfolio-message-test"
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_path = output_dir / "portfolio-7d.png"
    chart = generate_portfolio_chart(summary, chart_path)
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()

    payloads = []
    for report_type in ("daily", "weekly"):
        embed = build_portfolio_embed(summary, report_type, include_image=chart is not None)
        embed["title"] = f"TEST — {embed['title']}"
        embed["description"] = (
            "Example message using hypothetical data. The live forward account was not changed.\n"
            + embed["description"]
        )
        payloads.append(embed)

    (output_dir / "payloads.json").write_text(
        json.dumps(payloads, indent=2),
        encoding="utf-8",
    )
    if args.dry_run:
        print(f"[portfolio-test] Wrote payload preview to {output_dir}")
        return 0
    if not webhook_url:
        raise ValueError("DISCORD_WEBHOOK_URL is not set")

    for index, embed in enumerate(payloads):
        send_portfolio_card(webhook_url, embed, chart)
        print(f"[portfolio-test] Sent message {index + 1}/{len(payloads)}")
        if index < len(payloads) - 1:
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
