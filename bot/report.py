"""Phase 6: tone rewrite + history + earnings + recommendations.

This script fetches equity market data, crypto data (CoinGecko), headlines (Finnhub+RSS),
political/contract context, previous reports from Discord, and upcoming earnings.
It then asks Claude for a plain-English briefing/recap with tickers to watch, and posts
an embed to Discord.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime

import pytz
import requests

from claude_analysis import DISCLAIMER_LINE, generate_analysis
from crypto_data import fetch_crypto_data
from earnings_fetcher import fetch_upcoming_earnings
from history_fetcher import fetch_previous_reports
from market_data import fetch_market_data
from news_fetcher import fetch_top_headlines
from political_data import fetch_political_data
from recommendation_parser import parse_recommendations


ET_TZ = pytz.timezone("America/New_York")


def _load_env_local() -> None:
    """Load repo-root .env.local for local testing (gitignored).

    - Does nothing in GitHub Actions unless you also create that file there (you shouldn't).
    - Never overwrites real environment variables.
    """

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    path = os.path.join(repo_root, ".env.local")
    if not os.path.exists(path):
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        print("[report] Loaded .env.local for local testing")
    except Exception as exc:
        print(f"[report] WARNING: failed to load .env.local: {exc}")


def _label_for_run(now_et: datetime) -> str:
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


def _enforce_disclaimer(text: str) -> str:
    text = (text or "").strip()
    if DISCLAIMER_LINE in text:
        return text

    # Keep within embed limits and always include disclaimer.
    base = text
    if len(base) > 3900:
        base = base[:3900].rstrip() + "…"
    return base + "\n" + DISCLAIMER_LINE


def main() -> int:
    start = time.monotonic()

    _load_env_local()

    dry_run = (os.getenv("DRY_RUN") or "").strip().lower() in {"1", "true", "yes"}

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("ERROR: DISCORD_WEBHOOK_URL is not set.", file=sys.stderr)
        return 0

    now_et = datetime.now(ET_TZ)
    report_type = _label_for_run(now_et)
    date_et = now_et.strftime("%Y-%m-%d")

    print(f"[report] Report type: {report_type} ({date_et} ET)")

    print("[report] Fetching previous Discord reports...")
    previous_reports = []
    try:
        previous_reports = fetch_previous_reports()
    except Exception as exc:
        print(f"[report] WARNING: history fetch failed: {exc}")
        previous_reports = []
    print(f"[report] Previous reports found: {len(previous_reports)}")

    print("[report] Fetching earnings calendar...")
    earnings = []
    try:
        earnings = fetch_upcoming_earnings()
    except Exception as exc:
        print(f"[report] WARNING: earnings fetch failed: {exc}")
        earnings = []
    print(f"[report] Earnings found: {len(earnings)}")

    print("[report] Fetching market data...")
    market_data = None
    try:
        market_data = fetch_market_data()
    except Exception as exc:
        print(f"[report] WARNING: market data fetch failed: {exc}")
        market_data = None

    if not market_data or _all_none(market_data.get("equities", {})):
        ts = now_et.strftime("%Y-%m-%d %H:%M ET")
        content = f"⚠️ Market data fetch failed at {ts}."
        print("[report] Sending Discord fallback message...")
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

    print("[report] Fetching crypto data...")
    crypto_data = None
    try:
        crypto_data = fetch_crypto_data()
    except Exception as exc:
        print(f"[report] WARNING: crypto fetch failed: {exc}")
        crypto_data = None

    print("[report] Fetching news...")
    headlines = []
    try:
        headlines = fetch_top_headlines()
    except Exception as exc:
        print(f"[report] WARNING: news fetch failed: {exc}")
        headlines = []

    print("[report] Fetching political data...")
    political_data = {}
    try:
        political_data = fetch_political_data()
    except Exception as exc:
        print(f"[report] WARNING: political data fetch failed: {exc}")
        political_data = {}

    print("[report] All data fetched. Starting Claude analysis...")
    analysis = generate_analysis(
        market_data=market_data,
        crypto_data=crypto_data,
        news_items=headlines,
        political_data=political_data,
        previous_reports=previous_reports,
        earnings=earnings,
        report_type=report_type,
    )

    analysis = _enforce_disclaimer(analysis)
    print(f"[report] Claude response length: {len(analysis)} chars")

    print("[report] Parsing ticker recommendations...")
    recs = parse_recommendations(analysis)
    print(f"[report] Recommendations parsed: {len(recs)}")

    equities = market_data.get("equities", {})

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

    if crypto_data is None:
        cr_lines = ["Crypto data unavailable."]
    else:
        major = crypto_data.get("major", {}) if isinstance(crypto_data, dict) else {}
        movers = crypto_data.get("notable_movers", []) if isinstance(crypto_data, dict) else []

        cr_lines = [
            _fmt_line("BTC", (major.get("BTC") or {}).get("price") if major.get("BTC") else None,
                      (major.get("BTC") or {}).get("pct_change_24h") if major.get("BTC") else None),
            _fmt_line("ETH", (major.get("ETH") or {}).get("price") if major.get("ETH") else None,
                      (major.get("ETH") or {}).get("pct_change_24h") if major.get("ETH") else None),
            _fmt_line("SOL", (major.get("SOL") or {}).get("price") if major.get("SOL") else None,
                      (major.get("SOL") or {}).get("pct_change_24h") if major.get("SOL") else None),
        ]

        if movers:
            movers_str = ", ".join(
                f"{m.get('symbol','').upper()} {_arrow(float(m.get('pct_change_24h',0.0)))}{abs(float(m.get('pct_change_24h',0.0))):.2f}%"
                for m in movers
                if m.get("symbol") and m.get("pct_change_24h") is not None
            )
            if movers_str:
                cr_lines.append("")
                cr_lines.append(f"📢 Movers: {movers_str}")

    # Headlines field
    if headlines:
        hl_lines = [
            f"[{h.get('headline','').strip()}]({h.get('url','').strip()}) — {h.get('source','').strip()}"
            for h in headlines[:5]
            if (h.get("headline") and h.get("url"))
        ]
        headlines_value = "\n".join(hl_lines) if hl_lines else "No headlines available at this time."
    else:
        headlines_value = "No headlines available at this time."

    # Political fields
    trades = (political_data or {}).get("trades", []) if isinstance(political_data, dict) else []
    contracts = (political_data or {}).get("contracts", []) if isinstance(political_data, dict) else []
    correlations = (political_data or {}).get("correlations", []) if isinstance(political_data, dict) else []

    if trades:
        trade_lines = [
            f"{t.get('politician','').strip()} ({t.get('party','?').strip()}): {str(t.get('trade_type','?')).upper()} ${str(t.get('ticker','')).upper()} | {t.get('amount_range','').strip()} | {t.get('trade_date','').strip()}"
            for t in trades[:5]
        ]
        trades_value = "\n".join(trade_lines) if trade_lines else "No recent trades above $25K."
    else:
        trades_value = "No recent trades above $25K."

    if contracts:
        contract_lines = [
            f"{c.get('recipient','').strip()}: {c.get('amount_human', c.get('amount',''))} | {c.get('agency','').strip()}"
            for c in contracts[:3]
        ]
        contracts_value = "\n".join(contract_lines) if contract_lines else "No major contracts found."
        if correlations:
            contracts_value += f"\n\n⚠️ {len(correlations)} correlation(s) detected — see analysis above"
    else:
        contracts_value = "No major contracts found."

    # Earnings field
    if earnings:
        e_lines = []
        for e in earnings:
            sym = str(e.get("symbol") or "").upper()
            d = str(e.get("date") or "")
            t = str(e.get("time") or "Unknown")
            eps = e.get("eps_estimate")
            eps_str = str(eps) if eps is not None else "Unknown"
            e_lines.append(f"{sym}: {d} ({t}) | EPS est: {eps_str}")
        earnings_value = "\n".join(e_lines) if e_lines else "No major earnings in the next 3 days."
    else:
        earnings_value = "No major earnings in the next 3 days."

    # Recommendations field
    if recs:
        parts = []
        for r in recs[:5]:
            parts.append(
                f"{r.get('ticker','').strip()} — {r.get('rating','').strip()} ({r.get('confidence','').strip()})"
            )
            parts.append(str(r.get("reason") or "").strip())
            parts.append("")
        parts.append("⚠️ Not financial advice. For informational purposes only.")
        rec_value = "\n".join(parts).strip()
    else:
        rec_value = "No strong signals identified today."

    if report_type == "pre-market":
        title = f"📈 Pre-Market Briefing — {date_et} ET"
        color = 3066993
    else:
        title = f"📉 Post-Market Recap — {date_et} ET"
        color = 15158332

    fetched_at_et = market_data.get("fetched_at_et", now_et.strftime("%Y-%m-%d %H:%M ET"))

    print("[report] Building Discord embed...")
    embed = {
        "title": title,
        "color": color,
        "description": analysis[:4096],
        "fields": [
            {"name": "🇺🇸 Equities", "value": "\n".join(eq_lines), "inline": True},
            {"name": "₿ Crypto", "value": "\n".join(cr_lines), "inline": True},
            {"name": "🏛️ Political Trades", "value": trades_value, "inline": False},
            {"name": "📋 Gov Contracts", "value": contracts_value, "inline": False},
            {"name": "📰 Top Headlines", "value": headlines_value, "inline": False},
            {"name": "📅 Upcoming Earnings", "value": earnings_value, "inline": False},
            {"name": "🎯 Tickers to Watch", "value": rec_value, "inline": False},
        ],
        "footer": {"text": f"Data fetched at {fetched_at_et} | Personal use only"},
    }

    payload = {"embeds": [embed]}

    if dry_run:
        print("[report] DRY_RUN=1 set — not sending to Discord.")
        # Avoid dumping huge payloads in logs; show only a small preview.
        preview = {
            "title": embed.get("title"),
            "fields": [f.get("name") for f in embed.get("fields") or []],
            "description_chars": len(embed.get("description") or ""),
        }
        print(f"[report] Embed preview: {preview}")
        elapsed = time.monotonic() - start
        print(f"[report] Done. Total runtime: {elapsed:.1f}s")
        return 0

    print("[report] Sending to Discord...")
    try:
        resp = requests.post(webhook_url, json=payload, timeout=15)
    except requests.RequestException as exc:
        print(f"ERROR: Webhook POST failed: {exc}", file=sys.stderr)
        return 1

    if not (200 <= resp.status_code < 300):
        print(f"ERROR: Webhook POST failed with {resp.status_code}: {resp.text}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - start
    print(f"[report] Done. Total runtime: {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
