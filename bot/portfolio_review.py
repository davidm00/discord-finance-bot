"""Recommend-only periodic review for the forward paper portfolio."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from paper_portfolio import DEFAULT_STATE_DIR, ET, _atomic_write_csv, _read_csv, _safe_float
from portfolio_reporting import _closed_trades, build_portfolio_summary


REVIEW_HEADERS = [
    "reviewed_at_et",
    "closed_trade_count",
    "new_closed_trades",
    "status",
    "forward_return_pct",
    "max_drawdown_pct",
]


def build_review(
    state_dir: Path = DEFAULT_STATE_DIR,
    minimum_new_closed_trades: int = 10,
) -> dict[str, Any]:
    state_dir = Path(state_dir)
    summary = build_portfolio_summary(state_dir)
    ledger = _read_csv(state_dir / "ledger.csv")
    orders = _read_csv(state_dir / "orders.csv")
    reviews_path = state_dir / "review_checkpoints.csv"
    checkpoints = _read_csv(reviews_path)
    prior_substantive = [
        row for row in checkpoints if row.get("status") == "recommendation-ready"
    ]
    baseline_count = (
        int(prior_substantive[-1].get("closed_trade_count") or 0)
        if prior_substantive
        else 0
    )
    closed = _closed_trades(ledger)
    new_closed = max(0, len(closed) - baseline_count)
    ready = new_closed >= minimum_new_closed_trades

    rejection_counts = Counter(
        row.get("reason", "unknown")
        for row in orders
        if row.get("status") == "rejected"
    )
    by_exit: dict[str, list[float]] = defaultdict(list)
    for trade in closed:
        by_exit[trade["exit_type"]].append(float(trade["return_pct"]))

    evidence: list[str] = []
    recommendations: list[str] = []
    if not ready:
        recommendations.append(
            f"Keep policy unchanged: {new_closed}/{minimum_new_closed_trades} "
            "new closed trades are available."
        )
    else:
        if summary["max_drawdown_pct"] <= -10:
            recommendations.append(
                "Review position allocation or exposure limits because drawdown exceeded 10%."
            )
        if summary["closed_win_rate"] is not None and summary["closed_win_rate"] < 45:
            recommendations.append(
                "Review entry filters because the closed-trade win rate is below 45%."
            )
        stop_returns = by_exit.get("STOP", [])
        if len(stop_returns) >= 3:
            recommendations.append(
                "Inspect stopped trades by catalyst before changing the 4% stop; do not widen it globally without evidence."
            )
        gap_rejections = sum(
            count for reason, count in rejection_counts.items() if reason.startswith("opening gap")
        )
        if gap_rejections >= 3:
            recommendations.append(
                "Review rejected opening gaps as a shadow cohort before changing the 2% gap limit."
            )
        if not recommendations:
            recommendations.append(
                "No risk-policy change is supported by the current forward metrics."
            )

    for exit_type, returns in sorted(by_exit.items()):
        evidence.append(
            f"{exit_type}: n={len(returns)}, avg={sum(returns) / len(returns):+.2f}%"
        )

    return {
        "reviewed_at_et": datetime.now(ET).strftime("%Y-%m-%d %H:%M ET"),
        "status": "recommendation-ready" if ready else "insufficient-new-sample",
        "minimum_new_closed_trades": minimum_new_closed_trades,
        "new_closed_trades": new_closed,
        "closed_trade_count": len(closed),
        "summary": {
            key: summary[key]
            for key in (
                "as_of",
                "equity",
                "all_time_pnl",
                "all_time_return_pct",
                "weekly_return_pct",
                "max_drawdown_pct",
                "closed_trades",
                "closed_win_rate",
            )
        },
        "exit_evidence": evidence,
        "top_rejection_reasons": rejection_counts.most_common(8),
        "recommendations": recommendations,
        "approval_required": True,
    }


def write_review(
    review: dict[str, Any],
    state_dir: Path = DEFAULT_STATE_DIR,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    state_dir = Path(state_dir)
    output_dir = Path(output_dir or state_dir / "reviews")
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = review["reviewed_at_et"][:10]
    json_path = output_dir / f"portfolio-review-{stamp}.json"
    markdown_path = output_dir / f"portfolio-review-{stamp}.md"
    json_path.write_text(json.dumps(review, indent=2, sort_keys=True), encoding="utf-8")

    summary = review["summary"]
    lines = [
        f"# Paper Portfolio Review — {stamp}",
        "",
        f"**Status:** {review['status']}",
        "",
        f"- Forward equity: ${summary['equity']:,.2f}",
        f"- All-time return: {summary['all_time_return_pct']:+.2f}%",
        f"- Maximum drawdown: {summary['max_drawdown_pct']:.2f}%",
        f"- Closed trades: {summary['closed_trades']}",
        f"- New closed trades since substantive review: {review['new_closed_trades']}",
        "",
        "## Recommendations",
        "",
    ]
    lines.extend(f"- {item}" for item in review["recommendations"])
    lines.extend(["", "## Evidence", ""])
    lines.extend(f"- {item}" for item in review["exit_evidence"])
    if review["top_rejection_reasons"]:
        lines.extend(["", "## Top rejection reasons", ""])
        lines.extend(
            f"- {reason}: {count}"
            for reason, count in review["top_rejection_reasons"]
        )
    lines.extend(
        [
            "",
            "**No parameters, prompts, or code were changed. Human approval is required.**",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")

    checkpoints_path = state_dir / "review_checkpoints.csv"
    checkpoints = _read_csv(checkpoints_path)
    checkpoints.append(
        {
            "reviewed_at_et": review["reviewed_at_et"],
            "closed_trade_count": str(review["closed_trade_count"]),
            "new_closed_trades": str(review["new_closed_trades"]),
            "status": review["status"],
            "forward_return_pct": str(summary["all_time_return_pct"]),
            "max_drawdown_pct": str(summary["max_drawdown_pct"]),
        }
    )
    _atomic_write_csv(checkpoints_path, REVIEW_HEADERS, checkpoints)
    return markdown_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Review forward paper-portfolio performance")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--minimum-new-trades", type=int, default=10)
    args = parser.parse_args()
    try:
        review = build_review(args.state_dir, args.minimum_new_trades)
        markdown_path, json_path = write_review(review, args.state_dir)
        print(markdown_path.read_text(encoding="utf-8"))
        print(f"[portfolio-review] JSON: {json_path}")
        return 0
    except Exception as exc:
        print(f"[portfolio-review] ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
