"""Workflow entry point for isolated paper-portfolio processing and reporting."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

from paper_portfolio import (
    DEFAULT_SIGNALS_PATH,
    DEFAULT_STATE_DIR,
    ET,
    PaperPortfolio,
    _parse_date,
    load_signals,
)
from portfolio_reporting import (
    build_portfolio_embed,
    build_portfolio_summary,
    generate_portfolio_chart,
    send_portfolio_card,
    write_portfolio_preview,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Process and report the paper portfolio")
    parser.add_argument("--report-type", choices=("daily", "weekly"), required=True)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS_PATH)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--force-post", action="store_true")
    args = parser.parse_args()

    if not _enabled(os.getenv("PAPER_TRADING_ENABLED")):
        print("[portfolio] PAPER_TRADING_ENABLED is false; skipping")
        return 0

    dry_run = _enabled(os.getenv("DRY_RUN"))
    as_of = _parse_date(args.as_of) if args.as_of else datetime.now(ET).date()
    if as_of is None:
        print(f"[portfolio] ERROR: invalid --as-of value {args.as_of!r}", file=sys.stderr)
        return 1

    state_dir = args.state_dir
    if dry_run:
        state_dir = REPO_ROOT / "local-output" / "paper_portfolio_preview_state"
        if state_dir.exists():
            shutil.rmtree(state_dir)
        if args.state_dir.exists():
            shutil.copytree(args.state_dir, state_dir)

    try:
        engine = PaperPortfolio(state_dir)
        engine.process(load_signals(args.signals), as_of)
        summary = build_portfolio_summary(state_dir)
        output_dir = REPO_ROOT / "local-output"
        chart_path = output_dir / "portfolio-7d.png"
        chart = None
        try:
            chart = generate_portfolio_chart(summary, chart_path)
        except Exception as exc:
            engine._diagnose("chart", "ERROR", str(exc))

        embed = build_portfolio_embed(summary, args.report_type, include_image=chart is not None)
        preview = write_portfolio_preview(summary, embed, output_dir)
        print(f"[portfolio] Wrote preview: {preview}")

        is_post_market = datetime.now(ET).hour >= 12
        should_post = args.force_post or args.report_type == "weekly" or is_post_market
        if dry_run or not should_post:
            reason = "dry run" if dry_run else "pre-market daily run"
            print(f"[portfolio] Not posting portfolio card: {reason}")
            return 0

        send_portfolio_card(os.getenv("DISCORD_WEBHOOK_URL", ""), embed, chart)
        print("[portfolio] Portfolio card sent successfully")
        return 0
    except Exception as exc:
        print(f"[portfolio] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
