"""Phase 3: news aggregation + Claude analysis.

This script fetches basic market data (equities + crypto) and recent market headlines,
asks Claude for a concise briefing/recap, and posts the result to a Discord webhook on a
schedule via GitHub Actions.

Phase 1 was a pipeline test; Phase 2 added market data + AI; Phase 3 adds news context.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pytz
import requests

from claude_analysis import generate_analysis
from market_data import fetch_market_data
from news_fetcher import fetch_top_headlines


ET_TZ = pytz.timezone("America/New_York")


def _label_for_run(now_et: datetime) -> str:
    # Requirement: distinguish runs by checking the current hour in ET.
    return "pre-market" if now_et.hour < 12 else "post-market"


def _arrow(pct: float) -> str:
    return "▲" if pct >= 0 else "▼"


def _fmt_price_usd(v: float) -> str:
    return f"${v:,.2f}"


def _fmt_line(label: str, price: float | None, pct: float | None) -> str:
    if price is None or pct is None:
        return f"{label}: n/a"
    return f"{label}: {_fmt_price_usd(price)} ({_arrow(pct)} {abs(pct):.2f}%)"


def _all_none(section: dict) -> bool:
    return all(v is None for v in section.values())


def main() -> int:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print(
            "ERROR: DISCORD_WEBHOOK_URL is not set. Add it as a GitHub Actions secret named DISCORD_WEBHOOK_URL.",
            file=sys.stderr,
        )
        return 0

    now_et = datetime.now(ET_TZ)
    report_type = _label_for_run(now_et)
    date_et = now_et.strftime("%Y-%m-%d")

    print(f"Report type: {report_type} ({date_et} ET)")

    market_data = None
    try:
        market_data = fetch_market_data()
    except Exception as exc:
        print(f"ERROR: Market data fetch failed: {exc}", file=sys.stderr)
        market_data = None

    if not market_data or _all_none(market_data.get("equities", {})) and _all_none(market_data.get("crypto", {})):
        ts = now_et.strftime("%Y-%m-%d %H:%M ET")
        content = f"⚠️ Market data fetch failed at {ts}."
        print("Sending Discord fallback message...", file=sys.stdout)
        try:
            resp = requests.post(webhook_url, json={"content": content}, timeout=15)
        except requests.RequestException as exc:
            print(f"ERROR: Webhook POST failed: {exc}", file=sys.stderr)
            return 1
        if not (200 <= resp.status_code < 300):
            print(f"ERROR: Webhook POST failed with {resp.status_code}: {resp.text}", file=sys.stderr)
            return 1
        print(content)
        return 0

    headlines = []
    try:
        headlines = fetch_top_headlines()
    except Exception as exc:
        print(f"WARNING: News fetch failed: {exc}", file=sys.stderr)
        headlines = []

    print("Generating Claude analysis...", file=sys.stdout)
    analysis = generate_analysis(market_data, report_type, headlines)
    analysis = (analysis or "Analysis unavailable at this time.").strip()
    if len(analysis) > 4000:
        analysis = analysis[:4000] + "…"

    equities = market_data.get("equities", {})
    crypto = market_data.get("crypto", {})

    eq_lines = [
        _fmt_line("SPY", (equities.get("SPY") or {}).get("price") if equities.get("SPY") else None,
                  (equities.get("SPY") or {}).get("pct_change") if equities.get("SPY") else None),
        _fmt_line("QQQ", (equities.get("QQQ") or {}).get("price") if equities.get("QQQ") else None,
                  (equities.get("QQQ") or {}).get("pct_change") if equities.get("QQQ") else None),
        _fmt_line("DIA", (equities.get("DIA") or {}).get("price") if equities.get("DIA") else None,
                  (equities.get("DIA") or {}).get("pct_change") if equities.get("DIA") else None),
        _fmt_line("VIX", (equities.get("^VIX") or {}).get("price") if equities.get("^VIX") else None,
                  (equities.get("^VIX") or {}).get("pct_change") if equities.get("^VIX") else None),
    ]

    cr_lines = [
        _fmt_line("BTC", (crypto.get("BTC-USD") or {}).get("price") if crypto.get("BTC-USD") else None,
                  (crypto.get("BTC-USD") or {}).get("pct_change") if crypto.get("BTC-USD") else None),
        _fmt_line("ETH", (crypto.get("ETH-USD") or {}).get("price") if crypto.get("ETH-USD") else None,
                  (crypto.get("ETH-USD") or {}).get("pct_change") if crypto.get("ETH-USD") else None),
        _fmt_line("SOL", (crypto.get("SOL-USD") or {}).get("price") if crypto.get("SOL-USD") else None,
                  (crypto.get("SOL-USD") or {}).get("pct_change") if crypto.get("SOL-USD") else None),
    ]

    if report_type == "pre-market":
        title = f"📈 Pre-Market Briefing — {date_et} ET"
        color = 3066993
    else:
        title = f"📉 Post-Market Recap — {date_et} ET"
        color = 15158332

    fetched_at_et = market_data.get("fetched_at_et", now_et.strftime("%Y-%m-%d %H:%M ET"))

    if headlines:
        hl_lines = [
            f"[{h.get('headline','').strip()}]({h.get('url','').strip()}) — {h.get('source','').strip()}"
            for h in headlines[:5]
            if (h.get("headline") and h.get("url"))
        ]
        headlines_value = "\n".join(hl_lines) if hl_lines else "No headlines available at this time."
    else:
        headlines_value = "No headlines available at this time."

    embed = {
        "title": title,
        "color": color,
        "description": analysis,
        "fields": [
            {"name": "🇺🇸 Equities", "value": "\n".join(eq_lines), "inline": True},
            {"name": "₿ Crypto", "value": "\n".join(cr_lines), "inline": True},
            {"name": "📰 Top Headlines", "value": headlines_value, "inline": False},
        ],
        "footer": {"text": f"Data fetched at {fetched_at_et} | Personal use only"},
    }

    payload = {"embeds": [embed]}

    print("Sending Discord embed...", file=sys.stdout)
    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
    except requests.RequestException as exc:
        print(f"ERROR: Webhook POST failed: {exc}", file=sys.stderr)
        return 1

    if not (200 <= resp.status_code < 300):
        print(f"ERROR: Webhook POST failed with {resp.status_code}: {resp.text}", file=sys.stderr)
        return 1

    print("Discord embed sent successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
